"""Multi-account credentials (ADR 0019): services/credential.py on the SQLite test schema.

The schema in conftest mirrors the partial unique index
``uq_credentials_active_per_source``. What SQLite cannot show — PostgreSQL
checking a unique index row by row during the swap — is rehearsed on a real
database before deploy.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.models import Credential
from services import credential as cred


@pytest.fixture
def cred_db(db_session_factory):
    with patch("services.credential.AsyncSessionLocal", db_session_factory):
        yield db_session_factory


async def _accounts(factory, source: str) -> dict[str, tuple[bool, str]]:
    """{account: (is_active, decrypted value)} for a source."""
    async with factory() as session:
        rows = (await session.execute(select(Credential).where(Credential.source == source))).scalars().all()
        return {row.account: (bool(row.is_active), cred.decrypt(bytes(row.value_encrypted))) for row in rows}


class TestSetCredential:
    async def test_set_credential_without_account_creates_active_default(self, cred_db):
        assert await cred.set_credential("twitter", "v1", "cookie") == "default"

        assert await _accounts(cred_db, "twitter") == {"default": (True, "v1")}

    async def test_set_credential_without_account_overwrites_active_account_not_default(self, cred_db):
        await cred.set_credential("twitter", "v-default", "cookie")
        await cred.set_credential("twitter", "v-alt", "cookie", account="alt")
        await cred.activate_account("twitter", "alt")

        assert await cred.set_credential("twitter", "v-new", "cookie") == "alt"

        assert await _accounts(cred_db, "twitter") == {"default": (False, "v-default"), "alt": (True, "v-new")}

    async def test_set_credential_named_account_on_configured_source_stays_inactive(self, cred_db):
        await cred.set_credential("twitter", "v-default", "cookie")
        await cred.set_credential("twitter", "v-alt", "cookie", account="alt")

        assert await cred.get_credential("twitter") == "v-default"
        assert await _accounts(cred_db, "twitter") == {"default": (True, "v-default"), "alt": (False, "v-alt")}

    async def test_set_credential_named_account_is_activated_when_source_has_none(self, cred_db):
        assert await cred.set_credential("twitter", "v-alt", "cookie", account="alt") == "alt"

        assert await cred.get_credential("twitter") == "v-alt"

    async def test_set_credential_activates_written_account_when_source_lost_its_active_one(self, cred_db):
        async with cred_db() as session:
            session.add(
                Credential(
                    source="twitter",
                    account="default",
                    is_active=False,
                    credential_type="cookie",
                    value_encrypted=cred.encrypt("stale"),
                )
            )
            await session.commit()

        await cred.set_credential("twitter", "fresh", "cookie")

        assert await _accounts(cred_db, "twitter") == {"default": (True, "fresh")}

    @pytest.mark.parametrize("name", ["", "   ", "two words", "-leading-dash", "slash/name", "x" * 41])
    async def test_set_credential_rejects_invalid_account_name(self, cred_db, name):
        with pytest.raises(ValueError, match="account"):
            await cred.set_credential("twitter", "v", "cookie", account=name)

        assert await _accounts(cred_db, "twitter") == {}

    async def test_set_credential_stores_ciphertext_not_plaintext(self, cred_db):
        await cred.set_credential("pixiv", "plain-token", "oauth_token")

        async with cred_db() as session:
            raw = (
                await session.execute(select(Credential.value_encrypted).where(Credential.source == "pixiv"))
            ).scalar_one()
        assert b"plain-token" not in bytes(raw)


class TestActivateAccount:
    async def test_activate_account_switches_which_value_readers_get(self, cred_db):
        await cred.set_credential("ehentai", "cookies-a", "cookie")
        await cred.set_credential("ehentai", "cookies-b", "cookie", account="b")

        assert await cred.activate_account("ehentai", "b") is True

        assert await cred.get_credential("ehentai") == "cookies-b"
        active = await cred.get_active_credential("ehentai")
        assert (active.account, active.value) == ("b", "cookies-b")

    async def test_activate_account_leaves_exactly_one_active_row(self, cred_db):
        await cred.set_credential("ehentai", "a", "cookie")
        await cred.set_credential("ehentai", "b", "cookie", account="b")
        await cred.set_credential("ehentai", "c", "cookie", account="c")

        await cred.activate_account("ehentai", "c")
        await cred.activate_account("ehentai", "b")

        states = await _accounts(cred_db, "ehentai")
        assert [name for name, (is_active, _) in states.items() if is_active] == ["b"]

    async def test_activate_account_unknown_account_returns_false_and_keeps_active(self, cred_db):
        await cred.set_credential("ehentai", "a", "cookie")

        assert await cred.activate_account("ehentai", "ghost") is False

        assert await cred.get_credential("ehentai") == "a"

    async def test_activate_account_does_not_touch_other_sources(self, cred_db):
        await cred.set_credential("ehentai", "eh", "cookie")
        await cred.set_credential("twitter", "tw-a", "cookie")
        await cred.set_credential("twitter", "tw-b", "cookie", account="b")

        await cred.activate_account("twitter", "b")

        assert await cred.get_credential("ehentai") == "eh"


class TestDeleteAccount:
    async def test_delete_account_refuses_active_account_while_other_accounts_exist(self, cred_db):
        await cred.set_credential("twitter", "a", "cookie")
        await cred.set_credential("twitter", "b", "cookie", account="b")

        assert await cred.delete_account("twitter", "default") == "active_in_use"
        assert await cred.delete_account("twitter") == "active_in_use"

        assert set(await _accounts(cred_db, "twitter")) == {"default", "b"}

    async def test_delete_account_removes_last_account_of_source(self, cred_db):
        await cred.set_credential("twitter", "a", "cookie")

        assert await cred.delete_account("twitter") == "deleted"

        assert await cred.get_credential("twitter") is None
        assert await cred.list_credentials() == []

    async def test_delete_account_removes_inactive_account_and_keeps_active(self, cred_db):
        await cred.set_credential("twitter", "a", "cookie")
        await cred.set_credential("twitter", "b", "cookie", account="b")

        assert await cred.delete_account("twitter", "b") == "deleted"

        assert await _accounts(cred_db, "twitter") == {"default": (True, "a")}

    async def test_delete_account_unknown_returns_not_found(self, cred_db):
        assert await cred.delete_account("twitter") == "not_found"
        assert await cred.delete_account("twitter", "ghost") == "not_found"

    async def test_delete_account_without_name_clears_a_lone_inactive_account(self, cred_db):
        async with cred_db() as session:
            session.add(Credential(source="twitter", account="default", is_active=False, credential_type="cookie"))
            await session.commit()

        assert await cred.delete_account("twitter") == "deleted"

        assert await _accounts(cred_db, "twitter") == {}


class TestSetCredentialForAccount:
    async def test_set_credential_for_account_does_not_recreate_deleted_account(self, cred_db):
        await cred.set_credential("twitter", "a", "cookie")

        assert await cred.set_credential_for_account("twitter", "gone", "late", "cookies") is False

        assert set(await _accounts(cred_db, "twitter")) == {"default"}

    async def test_set_credential_for_account_does_not_change_active_account(self, cred_db):
        await cred.set_credential("twitter", "a", "cookie")
        await cred.set_credential("twitter", "b", "cookie", account="b")

        assert await cred.set_credential_for_account("twitter", "b", "b2", "cookies") is True

        assert await _accounts(cred_db, "twitter") == {"default": (True, "a"), "b": (False, "b2")}


class TestListing:
    async def test_list_credentials_returns_one_entry_per_source_with_account_count(self, cred_db):
        await cred.set_credential("twitter", "a", "cookie")
        await cred.set_credential("twitter", "b", "cookie", account="b")
        await cred.set_credential("pixiv", "tok", "oauth_token")

        listed = {entry["source"]: entry for entry in await cred.list_credentials()}

        assert set(listed) == {"twitter", "pixiv"}
        assert (listed["twitter"]["account"], listed["twitter"]["accounts"]) == ("default", 2)
        assert (listed["pixiv"]["account"], listed["pixiv"]["accounts"]) == ("default", 1)
        assert all(entry["configured"] is True for entry in listed.values())

    async def test_list_accounts_puts_active_first_and_exposes_no_values(self, cred_db):
        await cred.set_credential("twitter", "secret-a", "cookie", account="zeta")
        await cred.set_credential("twitter", "secret-b", "cookie", account="alpha")

        assert await cred.list_accounts("twitter") == [
            {"account": "zeta", "credential_type": "cookie", "is_active": True},
            {"account": "alpha", "credential_type": "cookie", "is_active": False},
        ]


class TestSchemaInvariant:
    async def test_schema_rejects_two_active_accounts_for_one_source(self, cred_db):
        async with cred_db() as session:
            session.add(Credential(source="twitter", account="a", is_active=True, credential_type="cookie"))
            session.add(Credential(source="twitter", account="b", is_active=True, credential_type="cookie"))
            with pytest.raises(IntegrityError):
                await session.commit()
