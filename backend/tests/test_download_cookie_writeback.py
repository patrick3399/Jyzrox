"""Cookie writeback follows the account a job started with (ADR 0019)."""

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from db.models import Credential
from plugins.builtin.gallery_dl._sites import cookie_writeback_path, get_site_config
from services import credential as cred
from worker.download import _load_credentials, _writeback_cookies


@pytest.fixture
def cred_db(db_session_factory):
    with patch("services.credential.AsyncSessionLocal", db_session_factory):
        yield db_session_factory


def _write_cookie_export(job_id: str, source: str, name: str, value: str) -> Path:
    path = Path(cookie_writeback_path(job_id, source))
    path.write_text(f"# Netscape HTTP Cookie File\n.x.com\tTRUE\t/\tTRUE\t2147483647\t{name}\t{value}\n")
    return path


async def _value(factory, source: str, account: str) -> str | None:
    async with factory() as session:
        raw = (
            await session.execute(
                select(Credential.value_encrypted).where(Credential.source == source, Credential.account == account)
            )
        ).scalar_one_or_none()
    return None if raw is None else cred.decrypt(bytes(raw))


async def _seed_twitter_accounts() -> None:
    await cred.set_credential("twitter", json.dumps({"auth_token": "a-old"}), "cookies", account="a")
    await cred.set_credential("twitter", json.dumps({"auth_token": "b-old"}), "cookies", account="b")


async def test_writeback_cookies_targets_account_job_started_with_after_active_account_switched(cred_db):
    assert get_site_config("twitter").credential_type == "cookies"
    await _seed_twitter_accounts()
    job_id = str(uuid.uuid4())

    started_with = await cred.get_active_credential("twitter")  # account "a"
    await cred.activate_account("twitter", "b")  # the admin switches while the job runs
    export = _write_cookie_export(job_id, "twitter", "auth_token", "a-new")

    await _writeback_cookies({"twitter": started_with.value}, job_id, {"twitter": started_with.account})

    assert json.loads(await _value(cred_db, "twitter", "a")) == {"auth_token": "a-new"}
    assert json.loads(await _value(cred_db, "twitter", "b")) == {"auth_token": "b-old"}
    assert (await cred.get_active_credential("twitter")).account == "b"
    assert not export.exists()


async def test_writeback_cookies_drops_update_when_account_was_deleted_during_job(cred_db):
    await _seed_twitter_accounts()
    job_id = str(uuid.uuid4())

    started_with = await cred.get_active_credential("twitter")
    await cred.activate_account("twitter", "b")
    assert await cred.delete_account("twitter", "a") == "deleted"
    _write_cookie_export(job_id, "twitter", "auth_token", "a-new")

    await _writeback_cookies({"twitter": started_with.value}, job_id, {"twitter": started_with.account})

    assert await _value(cred_db, "twitter", "a") is None
    assert json.loads(await _value(cred_db, "twitter", "b")) == {"auth_token": "b-old"}


async def test_load_credentials_records_the_account_each_value_came_from(cred_db):
    await cred.set_credential("twitter", "tw-a", "cookies", account="a")
    await cred.set_credential("twitter", "tw-b", "cookies", account="b")
    await cred.activate_account("twitter", "b")
    plugin = SimpleNamespace(meta=SimpleNamespace(source_id="gallery_dl", needs_all_credentials=True))

    values, accounts = await _load_credentials(plugin)

    assert values == {"twitter": "tw-b"}
    assert accounts == {"twitter": "b"}
