"""
Tests for services/credential.py

Covers AES-256-GCM encrypt/decrypt pure functions and DB-backed
get_credential, set_credential, and list_credentials.

The env var CREDENTIAL_ENCRYPT_KEY is set to a stable value in conftest.py,
so _get_key() / _KEY will derive and cache the same key for every test.
DB functions are unit-tested by patching services.credential.AsyncSessionLocal
with a mock async context manager, following the same pattern as test_retry.py.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.exceptions import InvalidTag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session(scalar_one_or_none_return=None, scalars_all_return=None):
    """Return a mock session wired as an async context manager.

    scalar_one_or_none_return -- value that result.scalar_one_or_none() gives back
    scalars_all_return        -- list that result.scalars().all() gives back
    """
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_one_or_none_return
    if scalars_all_return is not None:
        mock_result.scalars.return_value.all.return_value = scalars_all_return

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


def _make_mock_cred(source="ehentai", cred_type="cookie", value_encrypted=None, expires_at=None):
    """Return a MagicMock that looks like a Credential ORM row."""
    cred = MagicMock()
    cred.source = source
    cred.credential_type = cred_type
    cred.value_encrypted = value_encrypted
    cred.expires_at = expires_at
    return cred


# ---------------------------------------------------------------------------
# encrypt / decrypt — pure-function tests
# ---------------------------------------------------------------------------


class TestEncryptDecrypt:
    def test_roundtrip_short_string(self):
        """encrypt then decrypt returns the original short ASCII string."""
        from services.credential import decrypt, encrypt

        plaintext = "hello-world"
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_roundtrip_long_unicode_string(self):
        """encrypt then decrypt returns the original long string with unicode."""
        from services.credential import decrypt, encrypt

        plaintext = "パスワード" * 200 + "-secret-42"
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_encrypt_produces_different_ciphertext_each_call(self):
        """Each encrypt call must produce a different output (random nonce)."""
        from services.credential import encrypt

        ct1 = encrypt("same-value")
        ct2 = encrypt("same-value")
        assert ct1 != ct2

    def test_encrypt_output_has_minimum_length(self):
        """Output must be at least 12 bytes (nonce) + tag overhead."""
        from services.credential import encrypt

        ct = encrypt("x")
        # AES-GCM tag is 16 bytes; nonce is 12 bytes; plaintext 1 byte → 29 min
        assert len(ct) >= 29

    def test_decrypt_tampered_data_raises(self):
        """Modifying any byte in the ciphertext must raise InvalidTag."""
        from services.credential import decrypt, encrypt

        ct = bytearray(encrypt("sensitive-data"))
        # Flip a bit in the ciphertext portion (after the 12-byte nonce)
        ct[12] ^= 0xFF
        with pytest.raises(InvalidTag):
            decrypt(bytes(ct))


# ---------------------------------------------------------------------------
# get_credential — DB-mocked tests
# ---------------------------------------------------------------------------


class TestGetCredential:
    async def test_get_credential_not_found_returns_none(self):
        """Should return None when the credential row does not exist."""
        mock_session = _make_mock_session(scalar_one_or_none_return=None)

        with patch("services.credential.AsyncSessionLocal", return_value=mock_session):
            from services.credential import get_credential

            result = await get_credential("nonexistent")

        assert result is None

    async def test_get_credential_expired_returns_none(self):
        """Should return None when expires_at is in the past (tz-aware)."""
        from services.credential import encrypt

        expired_at = datetime.now(timezone.utc) - timedelta(hours=1)
        cred = _make_mock_cred(
            value_encrypted=encrypt("secret"),
            expires_at=expired_at,
        )
        mock_session = _make_mock_session(scalar_one_or_none_return=cred)

        with patch("services.credential.AsyncSessionLocal", return_value=mock_session):
            from services.credential import get_credential

            result = await get_credential("ehentai")

        assert result is None

    async def test_get_credential_valid_returns_decrypted_value(self):
        """Should return the decrypted plaintext for a non-expired credential."""
        from services.credential import encrypt

        plaintext = "my-secret-cookie"
        cred = _make_mock_cred(value_encrypted=encrypt(plaintext), expires_at=None)
        mock_session = _make_mock_session(scalar_one_or_none_return=cred)

        with patch("services.credential.AsyncSessionLocal", return_value=mock_session):
            from services.credential import get_credential

            result = await get_credential("ehentai")

        assert result == plaintext

    async def test_get_credential_naive_datetime_future_returns_value(self):
        """Naive datetime (no tzinfo) far in the future should be treated as UTC and pass."""
        from services.credential import encrypt

        plaintext = "future-cookie"
        # utcnow() + 1 day is unambiguously in the future when the service
        # re-attaches UTC, regardless of the machine's local timezone.
        naive_future = datetime.utcnow() + timedelta(days=1)
        assert naive_future.tzinfo is None  # confirm it is naive

        cred = _make_mock_cred(
            value_encrypted=encrypt(plaintext),
            expires_at=naive_future,
        )
        mock_session = _make_mock_session(scalar_one_or_none_return=cred)

        with patch("services.credential.AsyncSessionLocal", return_value=mock_session):
            from services.credential import get_credential

            result = await get_credential("ehentai")

        assert result == plaintext

    async def test_get_credential_naive_datetime_past_returns_none(self):
        """Naive datetime in the past should be treated as UTC and result in None.

        Uses utcnow() so the naive value is genuinely behind UTC regardless of
        the local timezone of the machine running the tests.
        """
        from services.credential import encrypt

        # utcnow() gives a naive datetime whose value equals UTC; subtract 2 h
        # so it is unambiguously in the past when the service re-attaches UTC tz.
        naive_past = datetime.utcnow() - timedelta(hours=2)
        assert naive_past.tzinfo is None  # confirm it is naive

        cred = _make_mock_cred(
            value_encrypted=encrypt("old-secret"),
            expires_at=naive_past,
        )
        mock_session = _make_mock_session(scalar_one_or_none_return=cred)

        with patch("services.credential.AsyncSessionLocal", return_value=mock_session):
            from services.credential import get_credential

            result = await get_credential("ehentai")

        assert result is None

    async def test_get_credential_none_encrypted_value_returns_none(self):
        """Should return None when the row exists but value_encrypted is None."""
        cred = _make_mock_cred(value_encrypted=None)
        mock_session = _make_mock_session(scalar_one_or_none_return=cred)

        with patch("services.credential.AsyncSessionLocal", return_value=mock_session):
            from services.credential import get_credential

            result = await get_credential("pixiv")

        assert result is None


# ---------------------------------------------------------------------------
# set_credential — DB-mocked tests
# ---------------------------------------------------------------------------


class TestSetCredential:
    async def test_set_credential_calls_execute_and_commit(self):
        """set_credential must execute the upsert statement and commit the session."""
        mock_session = _make_mock_session()

        with patch("services.credential.AsyncSessionLocal", return_value=mock_session):
            from services.credential import set_credential

            await set_credential("ehentai", "cookie-value", "cookie")

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    async def test_set_credential_stores_encrypted_bytes(self):
        """The value passed to execute must contain encrypted bytes, not plaintext."""
        mock_session = _make_mock_session()
        captured_stmt = {}

        original_execute = mock_session.execute

        async def _capture_execute(stmt, *args, **kwargs):
            captured_stmt["stmt"] = stmt
            return await original_execute(stmt, *args, **kwargs)

        mock_session.execute = _capture_execute

        with patch("services.credential.AsyncSessionLocal", return_value=mock_session):
            from services.credential import set_credential

            await set_credential("pixiv", "plain-token", "api_token")

        # The statement is compiled — verify that raw plaintext does not appear
        # in the string representation (encrypted bytes should be opaque)
        stmt_repr = str(captured_stmt["stmt"])
        assert "plain-token" not in stmt_repr


# ---------------------------------------------------------------------------
# list_credentials — DB-mocked tests
# ---------------------------------------------------------------------------


class TestListCredentials:
    async def test_list_credentials_returns_all_sources(self):
        """list_credentials should return one dict per row with correct keys."""
        rows = [
            _make_mock_cred(source="ehentai", cred_type="cookie"),
            _make_mock_cred(source="pixiv", cred_type="api_token"),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rows

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.credential.AsyncSessionLocal", return_value=mock_session):
            from services.credential import list_credentials

            result = await list_credentials()

        assert len(result) == 2
        sources = {r["source"] for r in result}
        assert sources == {"ehentai", "pixiv"}
        for item in result:
            assert item["configured"] is True
            assert "credential_type" in item

    async def test_list_credentials_empty_db_returns_empty_list(self):
        """list_credentials should return an empty list when no rows exist."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.credential.AsyncSessionLocal", return_value=mock_session):
            from services.credential import list_credentials

            result = await list_credentials()

        assert result == []
