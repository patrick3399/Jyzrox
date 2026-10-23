"""Regression: non-account galleries must not become their own artist.

E-Hentai cosplay galleries carry ``cosplayer:`` but no ``artist:`` tag, so the
metadata parsers returned no artist and the import paths fell back to
``{source}:{source_id}``. That fallback exists for account galleries (the URL
*is* the artist), but it fired for every gallery with a ``source_url`` and
turned each E-Hentai gallery id into a one-gallery "artist" (134 of 201 in
production; ``cosplayer:urumibunny`` alone was split into 11 artists).
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from plugins.builtin.gallery_dl._identity import UrlIdentity
from plugins.models import GalleryImportData

_EH_URL = "https://e-hentai.org/g/3565356/abcdef1234/"
_ACCOUNT_URL = "https://x.com/foo/media"
_EH_IDENTITY = UrlIdentity("ehentai", "gallery=e-/3565356/abcdef1234", False, "exhentai")
_ACCOUNT_IDENTITY = UrlIdentity("twitter", "foo", True, "twitter")


def _identity_for(identity: UrlIdentity | None):
    return patch("plugins.builtin.gallery_dl._identity.resolve_url_identity", return_value=identity)


# ── metadata parsers: cosplayer tag is the artist when no artist tag exists ──


def _eh_meta(tags: list[str]) -> dict:
    return {"gid": 3565356, "title": "ELY - Kafka", "tags": tags}


def test_eh_import_without_artist_tag_uses_cosplayer_tag(tmp_path: Path):
    from plugins.builtin.ehentai._metadata import parse_eh_import

    data = parse_eh_import(tmp_path, _eh_meta(["cosplayer:ely cosplay", "female:stockings"]))

    assert data.artist_id == "ehentai:ely cosplay"


def test_eh_import_prefers_artist_tag_over_earlier_cosplayer_tag(tmp_path: Path):
    from plugins.builtin.ehentai._metadata import parse_eh_import

    data = parse_eh_import(tmp_path, _eh_meta(["cosplayer:ely cosplay", "artist:someone"]))

    assert data.artist_id == "ehentai:someone"


def test_eh_import_without_artist_or_cosplayer_tag_has_no_artist(tmp_path: Path):
    from plugins.builtin.ehentai._metadata import parse_eh_import

    data = parse_eh_import(tmp_path, _eh_meta(["female:stockings"]))

    assert data.artist_id is None


def test_gallery_dl_tag_strategy_without_artist_tag_uses_cosplayer_tag():
    from plugins.builtin.gallery_dl._metadata import _extract_artist

    assert _extract_artist("ehentai", {}, ["cosplayer:urumibunny"]) == "ehentai:urumibunny"
    assert _extract_artist("ehentai", {}, ["cosplayer:urumibunny", "artist:x"]) == "ehentai:x"


# ── import fallbacks: source:source_id only for account URLs ──


def test_importer_non_account_url_without_artist_does_not_use_gallery_id_as_artist():
    from worker.importer import _subscription_artist_id

    with _identity_for(_EH_IDENTITY):
        assert _subscription_artist_id("ehentai", "3565356", None, _EH_URL) is None


def test_importer_unresolvable_url_without_artist_has_no_artist():
    from worker.importer import _subscription_artist_id

    with _identity_for(None):
        assert _subscription_artist_id("ehentai", "3565356", None, _EH_URL) is None


def test_importer_account_url_without_artist_uses_account_as_artist():
    from worker.importer import _subscription_artist_id

    with _identity_for(_ACCOUNT_IDENTITY):
        assert _subscription_artist_id("twitter", "foo", None, _ACCOUNT_URL) == "twitter:foo"


def test_importer_metadata_artist_wins_without_resolving_url():
    from worker.importer import _subscription_artist_id

    with _identity_for(_EH_IDENTITY) as resolve:
        assert _subscription_artist_id("ehentai", "3565356", "ehentai:x", _EH_URL) == "ehentai:x"
    resolve.assert_not_called()


def _import_data(source: str, source_id: str, artist_id: str | None) -> GalleryImportData:
    return GalleryImportData(source=source, source_id=source_id, title="t", artist_id=artist_id)


def test_progressive_non_account_url_without_artist_does_not_use_gallery_id_as_artist():
    from worker.progressive import _subscription_artist_id

    with _identity_for(_EH_IDENTITY):
        assert _subscription_artist_id(_import_data("ehentai", "3565356", None), _EH_URL) is None


def test_progressive_account_url_without_artist_uses_account_as_artist():
    from worker.progressive import _subscription_artist_id

    with _identity_for(_ACCOUNT_IDENTITY):
        assert _subscription_artist_id(_import_data("twitter", "foo", None), _ACCOUNT_URL) == "twitter:foo"


@pytest.mark.parametrize("identity", [_EH_IDENTITY, _ACCOUNT_IDENTITY, None])
def test_progressive_without_source_url_has_no_artist(identity):
    from worker.progressive import _subscription_artist_id

    with _identity_for(identity):
        assert _subscription_artist_id(_import_data("ehentai", "3565356", None), None) is None


# ── import_job re-import: a NULL artist must not erase an existing one ──


@pytest.mark.asyncio
async def test_import_job_reimport_without_artist_keeps_existing_artist_id(tmp_path: Path):
    """Now that non-account galleries may resolve to no artist, the import_job
    upsert must keep the stored artist_id (e.g. a workbench edit) instead of
    overwriting it with NULL — the same rule the progressive upserts follow."""
    import json
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.dialects import postgresql
    from sqlalchemy.sql.dml import Insert

    from worker.importer import import_job

    gallery_dir = tmp_path / "g"
    gallery_dir.mkdir()
    (gallery_dir / "001.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    (gallery_dir / "metadata.json").write_text(json.dumps({"category": "ehentai", "title": "T", "gid": 3565356}))

    session = AsyncMock()
    result = MagicMock()
    result.scalar_one = MagicMock(return_value=1)
    result.scalar_one_or_none = MagicMock(return_value=1)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.all = MagicMock(return_value=[])
    session.execute = AsyncMock(return_value=result)
    session.get = AsyncMock(return_value=MagicMock())

    @asynccontextmanager
    async def _ctx():
        yield session

    blob = MagicMock()
    blob.sha256 = "ab" * 32
    with (
        patch("worker.importer.AsyncSessionLocal", return_value=_ctx()),
        patch("worker.importer.store_blob", AsyncMock(return_value=blob)),
        patch("worker.importer.create_library_symlink", AsyncMock()),
        patch("worker.helpers._sha256", return_value="ab" * 32),
        patch("worker.importer._validate_image_magic", return_value=True),
        patch("worker.importer._normalize_tags", side_effect=lambda t, s: t),
        patch(
            "plugins.builtin.gallery_dl._sites.get_site_config",
            return_value=MagicMock(source_id="ehentai", source_id_fields=("gid",), category="gallery"),
        ),
        patch("plugins.registry.plugin_registry.get_parser", return_value=None),
        patch("plugins.builtin.gallery_dl._metadata._extract_artist", return_value=None),
        patch("worker.importer.rebuild_gallery_tags_array", AsyncMock()),
        patch("worker.importer.upsert_tag_translations", AsyncMock()),
        patch("shutil.rmtree"),
        _identity_for(_EH_IDENTITY),
    ):
        ctx = {"redis": AsyncMock()}
        await import_job(ctx, path=str(gallery_dir), user_id=1, source_url=_EH_URL)

    inserts = [
        c.args[0]
        for c in session.execute.call_args_list
        if c.args and isinstance(c.args[0], Insert) and c.args[0].table.name == "galleries"
    ]
    assert inserts, "import_job did not upsert the gallery"
    compiled = inserts[0].compile(dialect=postgresql.dialect())
    assert compiled.params["artist_id"] is None
    set_clause = str(compiled).split("DO UPDATE SET", 1)[1]
    assert "artist_id = coalesce(excluded.artist_id, galleries.artist_id)" in set_clause
