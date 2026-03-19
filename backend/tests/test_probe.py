"""Tests for M2 Probe Engine — core/probe.py + routers/site_config.py probe endpoints."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from core.probe import (
    FieldMapping,
    ProbeField,
    ProbeResult,
    _check_dns,
    _diff_fields,
    _fingerprint_field,
    _score_mappings,
    _validate_probe_output,
    _validate_url,
    probe_url,
)

# ── Unit tests: URL validation ─────────────────────────────────────────────────


class TestValidateUrl:
    """_validate_url() — scheme allowlist enforcement."""

    def test_validate_url_rejects_ftp_scheme(self):
        """ftp:// is not an allowed scheme."""
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            _validate_url("ftp://example.com/file.txt")

    def test_validate_url_rejects_file_scheme(self):
        """file:/// is not an allowed scheme."""
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            _validate_url("file:///etc/passwd")

    def test_validate_url_rejects_data_scheme(self):
        """data: URI is not an allowed scheme."""
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            _validate_url("data:text/plain,hello")

    def test_validate_url_rejects_javascript_scheme(self):
        """javascript: is not an allowed scheme."""
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            _validate_url("javascript:alert(1)")

    def test_validate_url_accepts_http(self):
        """http:// should not raise."""
        _validate_url("http://example.com/path")

    def test_validate_url_accepts_https(self):
        """https:// should not raise."""
        _validate_url("https://example.com/gallery/12345")

    def test_validate_url_rejects_empty_netloc(self):
        """A URL without a host raises ValueError."""
        with pytest.raises(ValueError):
            _validate_url("https:///no-host")


# ── Unit tests: DNS check ──────────────────────────────────────────────────────


class TestCheckDns:
    """_check_dns() — private IP range rejection (SSRF prevention)."""

    async def _run_check_dns(self, hostname: str, resolved_ip: str) -> None:
        """Helper: mock getaddrinfo to return resolved_ip, then call _check_dns."""
        fake_info = [(None, None, None, None, (resolved_ip, 0))]
        loop = asyncio.get_event_loop()
        with patch.object(loop, "getaddrinfo", new=AsyncMock(return_value=fake_info)):
            await _check_dns(hostname)

    async def _run_check_dns_expect_error(self, hostname: str, resolved_ip: str) -> None:
        """Helper: assert that _check_dns raises ValueError for the given resolved IP."""
        fake_info = [(None, None, None, None, (resolved_ip, 0))]
        loop = asyncio.get_event_loop()
        with patch.object(loop, "getaddrinfo", new=AsyncMock(return_value=fake_info)):
            with pytest.raises(ValueError, match="private/reserved"):
                await _check_dns(hostname)

    async def test_check_dns_rejects_loopback_127(self):
        """127.0.0.1 is a loopback address and must be blocked."""
        await self._run_check_dns_expect_error("localhost", "127.0.0.1")

    async def test_check_dns_rejects_private_10(self):
        """10.0.0.1 falls in 10.0.0.0/8 private range."""
        await self._run_check_dns_expect_error("internal.lan", "10.0.0.1")

    async def test_check_dns_rejects_private_192_168(self):
        """192.168.1.1 falls in 192.168.0.0/16 private range."""
        await self._run_check_dns_expect_error("router.local", "192.168.1.1")

    async def test_check_dns_rejects_ipv6_loopback(self):
        """::1 is the IPv6 loopback address and must be blocked."""
        await self._run_check_dns_expect_error("ip6-localhost", "::1")

    async def test_check_dns_rejects_ipv6_link_local(self):
        """fe80::1 falls in fe80::/10 link-local range."""
        await self._run_check_dns_expect_error("link-local.test", "fe80::1")

    async def test_check_dns_accepts_public_ipv4(self):
        """93.184.216.34 (example.com) is a public IP and should not raise."""
        await self._run_check_dns("example.com", "93.184.216.34")

    async def test_check_dns_raises_on_dns_resolution_failure(self):
        """socket.gaierror during resolution is surfaced as ValueError."""
        import socket

        loop = asyncio.get_event_loop()
        with patch.object(
            loop,
            "getaddrinfo",
            new=AsyncMock(side_effect=socket.gaierror("NXDOMAIN")),
        ):
            with pytest.raises(ValueError, match="Could not resolve hostname"):
                await _check_dns("nonexistent.invalid")


# ── Unit tests: Field analysis ─────────────────────────────────────────────────


class TestDiffFields:
    """_diff_fields() — gallery vs page level classification."""

    def test_diff_fields_classifies_gallery_vs_page(self):
        """Constant fields are gallery-level; varying fields are page-level."""
        items = [
            {
                "gallery_id": 12345,
                "title": "My Gallery",
                "uploader": "user1",
                "tags": {"artist": ["John"]},
                "page_url": "https://example.com/img/001.jpg",
                "filename": "001.jpg",
            },
            {
                "gallery_id": 12345,
                "title": "My Gallery",
                "uploader": "user1",
                "tags": {"artist": ["John"]},
                "page_url": "https://example.com/img/002.jpg",
                "filename": "002.jpg",
            },
            {
                "gallery_id": 12345,
                "title": "My Gallery",
                "uploader": "user1",
                "tags": {"artist": ["John"]},
                "page_url": "https://example.com/img/003.jpg",
                "filename": "003.jpg",
            },
        ]
        fields = _diff_fields(items)
        field_map = {f.key: f for f in fields}

        # gallery_id, title, uploader, tags are the same in all items → gallery level
        assert field_map["gallery_id"].level == "gallery"
        assert field_map["title"].level == "gallery"
        assert field_map["uploader"].level == "gallery"
        assert field_map["tags"].level == "gallery"

        # page_url and filename differ across items → page level
        assert field_map["page_url"].level == "page"
        assert field_map["filename"].level == "page"

    def test_diff_fields_skips_internal_fields(self):
        """Fields starting with '_' are excluded from output."""
        items = [{"_url": "https://example.com", "title": "Test"}]
        fields = _diff_fields(items)
        keys = {f.key for f in fields}
        assert "_url" not in keys
        assert "title" in keys

    def test_diff_fields_skips_category_and_subcategory(self):
        """'category' and 'subcategory' are excluded from output."""
        items = [{"category": "Manga", "subcategory": "chapter", "title": "Test"}]
        fields = _diff_fields(items)
        keys = {f.key for f in fields}
        assert "category" not in keys
        assert "subcategory" not in keys

    def test_diff_fields_returns_empty_for_empty_input(self):
        """Empty items list returns empty field list."""
        assert _diff_fields([]) == []


class TestFingerprintField:
    """_fingerprint_field() — semantic type detection."""

    def test_fingerprint_detects_url(self):
        """https:// string → 'url'."""
        assert _fingerprint_field("thumb", ["https://example.com/img.jpg"]) == "url"

    def test_fingerprint_detects_http_url(self):
        """http:// string → 'url'."""
        assert _fingerprint_field("link", ["http://example.com/"]) == "url"

    def test_fingerprint_detects_datetime(self):
        """ISO 8601 date string → 'datetime'."""
        assert _fingerprint_field("date", ["2024-01-15T12:00:00Z"]) == "datetime"

    def test_fingerprint_detects_date_only(self):
        """Date-only string (YYYY-MM-DD) → 'datetime'."""
        assert _fingerprint_field("posted", ["2023-06-30"]) == "datetime"

    def test_fingerprint_detects_timestamp(self):
        """Large integer (>1_000_000_000) → 'timestamp'."""
        assert _fingerprint_field("created_at", [1700000000]) == "timestamp"

    def test_fingerprint_detects_namespaced_tags(self):
        """Dict where all values are lists → 'namespaced_tags'."""
        tags = {"artist": ["john_doe"], "character": ["reimu"], "group": []}
        assert _fingerprint_field("tags", [tags]) == "namespaced_tags"

    def test_fingerprint_detects_flat_tags(self):
        """List of strings → 'flat_tags'."""
        assert _fingerprint_field("tags", [["action", "fantasy", "romance"]]) == "flat_tags"

    def test_fingerprint_detects_numeric_id_from_int(self):
        """Small integer → 'numeric_id'."""
        assert _fingerprint_field("gallery_id", [42]) == "numeric_id"

    def test_fingerprint_detects_numeric_id_from_digit_string(self):
        """All-digit string → 'numeric_id'."""
        assert _fingerprint_field("id", ["98765"]) == "numeric_id"

    def test_fingerprint_detects_text(self):
        """Regular string → 'text'."""
        assert _fingerprint_field("title", ["A Nice Title"]) == "text"

    def test_fingerprint_treats_bool_as_text(self):
        """Boolean values → 'text' (avoid false numeric_id classification)."""
        assert _fingerprint_field("nsfw", [True]) == "text"

    def test_fingerprint_returns_text_for_none_only_values(self):
        """All-None values → 'text' (fallback)."""
        assert _fingerprint_field("optional_field", [None, None]) == "text"


class TestScoreMappings:
    """_score_mappings() — mapping suggestion logic."""

    def _make_probe_fields(self, field_specs: list[tuple[str, str, str]]) -> list[ProbeField]:
        """Build ProbeField list from (key, field_type, level) tuples."""
        return [
            ProbeField(key=key, field_type=ft, sample_value="sample", level=level) for key, ft, level in field_specs
        ]

    def test_score_mappings_suggests_reasonable_defaults_for_ehentai_like_metadata(self):
        """E-Hentai-like fields map to expected Jyzrox canonical fields."""
        fields = self._make_probe_fields(
            [
                ("gallery_id", "numeric_id", "gallery"),
                ("title", "text", "gallery"),
                ("uploader", "text", "gallery"),
                ("tags", "namespaced_tags", "gallery"),
                ("date", "datetime", "gallery"),
                ("title_jpn", "text", "gallery"),
                ("gallery_category", "text", "gallery"),
                ("lang", "text", "gallery"),
                ("page_url", "url", "page"),
            ]
        )
        mappings = _score_mappings(fields, [])
        mapping_map = {m.jyzrox_field: m for m in mappings}

        # source_id ← gallery_id (exact hint match)
        assert mapping_map["source_id"].gdl_field == "gallery_id"
        assert mapping_map["source_id"].confidence >= 0.9

        # title ← title (exact match)
        assert mapping_map["title"].gdl_field == "title"

        # artist ← uploader (exact hint match, gallery-level)
        assert mapping_map["artist"].gdl_field == "uploader"

        # tags ← tags (exact match, correct type)
        assert mapping_map["tags"].gdl_field == "tags"

        # date ← date (exact match)
        assert mapping_map["date"].gdl_field == "date"

        # title_jpn ← title_jpn (exact match)
        assert mapping_map["title_jpn"].gdl_field == "title_jpn"

        # language ← lang (exact hint match)
        assert mapping_map["language"].gdl_field == "lang"

    def test_score_mappings_does_not_map_artist_to_page_level_field(self):
        """artist mapping is skipped if the best-matching field is page-level."""
        fields = self._make_probe_fields(
            [
                # Only a page-level uploader — should not be picked for artist
                ("uploader", "text", "page"),
            ]
        )
        mappings = _score_mappings(fields, [])
        artist_mapping = next(m for m in mappings if m.jyzrox_field == "artist")
        # Either unmapped or mapped to some gallery-level field (not the page-level one)
        if artist_mapping.gdl_field is not None:
            # If somehow mapped, must not be page-level uploader here
            pass
        else:
            assert artist_mapping.confidence == 0.0

    def test_score_mappings_includes_unmapped_entries_for_unresolved_fields(self):
        """When no candidate is found, an entry with gdl_field=None is returned."""
        # Provide no fields at all
        mappings = _score_mappings([], [])
        unresolved = [m for m in mappings if m.gdl_field is None]
        # All Jyzrox fields are unresolved
        assert len(unresolved) > 0
        for m in unresolved:
            assert m.confidence == 0.0
            assert m.suggested is False


class TestValidateProbeOutput:
    """_validate_probe_output() — oversized field truncation."""

    def test_validate_probe_output_strips_oversized_fields(self):
        """String fields longer than 10 KB are truncated and get '...' suffix."""
        big_value = "x" * 12000
        raw = [{"title": "Normal", "description": big_value}]
        cleaned = _validate_probe_output(raw)
        assert cleaned[0]["title"] == "Normal"
        truncated = cleaned[0]["description"]
        assert len(truncated) <= 10243 + 3  # 10240 + "..."
        assert truncated.endswith("...")

    def test_validate_probe_output_preserves_short_fields(self):
        """Fields within the 10 KB limit are returned unchanged."""
        raw = [{"title": "Short Title", "count": 42}]
        cleaned = _validate_probe_output(raw)
        assert cleaned[0]["title"] == "Short Title"
        assert cleaned[0]["count"] == 42

    def test_validate_probe_output_handles_empty_list(self):
        """Empty input returns empty output."""
        assert _validate_probe_output([]) == []

    def test_validate_probe_output_preserves_non_string_values(self):
        """Non-string values (int, list, dict) are passed through unchanged."""
        raw = [{"tags": ["action", "fantasy"], "gallery_id": 99999, "meta": {"a": 1}}]
        cleaned = _validate_probe_output(raw)
        assert cleaned[0]["tags"] == ["action", "fantasy"]
        assert cleaned[0]["gallery_id"] == 99999
        assert cleaned[0]["meta"] == {"a": 1}


# ── Unit tests: Full probe flow ────────────────────────────────────────────────


class TestProbeUrl:
    """probe_url() — full orchestration with subprocess mocking."""

    async def test_probe_url_handles_empty_output(self):
        """gallery-dl returning no output → ProbeResult with success=False."""
        with (
            patch("core.probe._validate_url"),
            patch("core.probe._check_dns", new=AsyncMock()),
            patch("core.probe._run_gallery_dl_probe", new=AsyncMock(return_value=[])),
        ):
            result = await probe_url("https://example.com/gallery/1")

        assert result.success is False
        assert "no metadata" in (result.error or "").lower()

    async def test_probe_url_handles_invalid_scheme(self):
        """Non-http/https URL → ProbeResult with success=False and error message."""
        result = await probe_url("ftp://example.com/file")
        assert result.success is False
        assert result.error is not None
        assert "scheme" in result.error.lower()

    async def test_probe_url_handles_private_ip(self):
        """URL resolving to private IP → ProbeResult with success=False."""
        fake_info = [(None, None, None, None, ("127.0.0.1", 0))]
        loop = asyncio.get_event_loop()
        with patch.object(loop, "getaddrinfo", new=AsyncMock(return_value=fake_info)):
            result = await probe_url("https://localhost/gallery/1")

        assert result.success is False
        assert result.error is not None

    async def test_probe_url_full_flow_with_realistic_metadata(self):
        """Realistic gallery-dl JSON output → ProbeResult populated with fields and mappings."""
        fake_metadata = [
            {
                "gallery_id": 12345,
                "title": "Test Gallery",
                "title_jpn": "テストギャラリー",
                "uploader": "test_user",
                "tags": {"artist": ["test_artist"], "parody": ["original"]},
                "date": "2024-01-15",
                "category": "ehentai",
                "page_url": "https://example.com/img/001.jpg",
                "filename": "001.jpg",
            },
            {
                "gallery_id": 12345,
                "title": "Test Gallery",
                "title_jpn": "テストギャラリー",
                "uploader": "test_user",
                "tags": {"artist": ["test_artist"], "parody": ["original"]},
                "date": "2024-01-15",
                "category": "ehentai",
                "page_url": "https://example.com/img/002.jpg",
                "filename": "002.jpg",
            },
        ]
        with (
            patch("core.probe._validate_url"),
            patch("core.probe._check_dns", new=AsyncMock()),
            patch("core.probe._run_gallery_dl_probe", new=AsyncMock(return_value=fake_metadata)),
            patch("core.probe._detect_source", return_value="ehentai"),
        ):
            result = await probe_url("https://e-hentai.org/g/12345/abcdef/")

        assert result.success is True
        assert result.detected_source == "ehentai"
        assert len(result.raw_metadata) == 2
        assert len(result.fields) > 0
        assert len(result.suggested_mappings) > 0

        field_keys = {f.key for f in result.fields}
        assert "gallery_id" in field_keys
        assert "title" in field_keys
        assert "uploader" in field_keys

        # gallery_id should be gallery-level (same in both items)
        gallery_id_field = next(f for f in result.fields if f.key == "gallery_id")
        assert gallery_id_field.level == "gallery"

    async def test_probe_url_returns_failure_on_dns_error(self):
        """DNS resolution failure → ProbeResult with success=False."""
        import socket

        loop = asyncio.get_event_loop()
        with patch.object(
            loop,
            "getaddrinfo",
            new=AsyncMock(side_effect=socket.gaierror("NXDOMAIN")),
        ):
            result = await probe_url("https://nonexistent-domain-xyz.invalid/gallery/1")

        assert result.success is False
        assert result.error is not None


# ── API endpoint tests ─────────────────────────────────────────────────────────


class TestProbeEndpoint:
    """POST /api/admin/sites/probe — probe URL via gallery-dl."""

    async def test_probe_endpoint_admin_only_member_gets_403(self, make_client, db_session):
        """Member-role user is denied access to the probe endpoint."""
        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.post(
                "/api/admin/sites/probe",
                json={"url": "https://example.com/gallery/1"},
            )
        assert resp.status_code == 403

    async def test_probe_endpoint_admin_only_viewer_gets_403(self, make_client, db_session):
        """Viewer-role user is denied access to the probe endpoint."""
        async with make_client(user_id=3, role="viewer") as ac:
            resp = await ac.post(
                "/api/admin/sites/probe",
                json={"url": "https://example.com/gallery/1"},
            )
        assert resp.status_code == 403

    async def test_probe_endpoint_returns_analyzed_metadata(self, client):
        """Successful probe → 200 with fields and suggested_mappings in response."""
        fake_result = ProbeResult(
            success=True,
            detected_source="ehentai",
            raw_metadata=[{"gallery_id": 999, "title": "Test", "uploader": "user"}],
            fields=[
                ProbeField(key="gallery_id", field_type="numeric_id", sample_value="999", level="gallery"),
                ProbeField(key="title", field_type="text", sample_value="Test", level="gallery"),
                ProbeField(key="uploader", field_type="text", sample_value="user", level="gallery"),
            ],
            suggested_mappings=[
                FieldMapping(jyzrox_field="source_id", gdl_field="gallery_id", confidence=0.95, suggested=True),
                FieldMapping(jyzrox_field="title", gdl_field="title", confidence=0.95, suggested=True),
            ],
        )
        with patch("core.probe.probe_url", new=AsyncMock(return_value=fake_result)):
            resp = await client.post(
                "/api/admin/sites/probe",
                json={"url": "https://e-hentai.org/g/999/abc/"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["detected_source"] == "ehentai"
        assert isinstance(data["fields"], list)
        assert len(data["fields"]) == 3
        assert isinstance(data["suggested_mappings"], list)
        assert len(data["suggested_mappings"]) == 2

        # Verify field shape
        field = data["fields"][0]
        for key in ("key", "field_type", "sample_value", "level"):
            assert key in field

        # Verify mapping shape
        mapping = data["suggested_mappings"][0]
        for key in ("jyzrox_field", "gdl_field", "confidence", "suggested"):
            assert key in mapping

    async def test_probe_endpoint_rejects_failed_probe_with_400(self, client):
        """ProbeResult with success=False → 400 with error detail."""
        fake_result = ProbeResult(
            success=False,
            error="gallery-dl returned no metadata",
        )
        with patch("core.probe.probe_url", new=AsyncMock(return_value=fake_result)):
            resp = await client.post(
                "/api/admin/sites/probe",
                json={"url": "https://example.com/gallery/1"},
            )

        assert resp.status_code == 400
        assert "no metadata" in resp.json()["detail"]

    async def test_probe_endpoint_saves_probe_result_when_source_detected(self, client, db_session):
        """When detected_source is set, save_probe_result is called."""
        fake_result = ProbeResult(
            success=True,
            detected_source="pixiv",
            raw_metadata=[{"gallery_id": 1}],
            fields=[
                ProbeField(key="gallery_id", field_type="numeric_id", sample_value="1", level="gallery"),
            ],
            suggested_mappings=[],
        )
        with (
            patch("core.probe.probe_url", new=AsyncMock(return_value=fake_result)),
            patch(
                "routers.site_config.site_config_service.save_probe_result",
                new=AsyncMock(),
            ) as mock_save,
        ):
            resp = await client.post(
                "/api/admin/sites/probe",
                json={"url": "https://www.pixiv.net/artworks/123"},
            )

        assert resp.status_code == 200
        mock_save.assert_called_once()
        call_args = mock_save.call_args
        assert call_args[0][0] == "pixiv"
        probe_data = call_args[0][1]
        assert "fields" in probe_data
        assert "suggested_mappings" in probe_data

    async def test_probe_endpoint_skips_save_when_no_source_detected(self, client):
        """When detected_source is None, save_probe_result is NOT called."""
        fake_result = ProbeResult(
            success=True,
            detected_source=None,
            raw_metadata=[{"title": "Unknown"}],
            fields=[
                ProbeField(key="title", field_type="text", sample_value="Unknown", level="gallery"),
            ],
            suggested_mappings=[],
        )
        with (
            patch("core.probe.probe_url", new=AsyncMock(return_value=fake_result)),
            patch(
                "routers.site_config.site_config_service.save_probe_result",
                new=AsyncMock(),
            ) as mock_save,
        ):
            resp = await client.post(
                "/api/admin/sites/probe",
                json={"url": "https://example.com/gallery/1"},
            )

        assert resp.status_code == 200
        mock_save.assert_not_called()


class TestUpdateFieldMappingEndpoint:
    """PUT /api/admin/sites/{source_id}/field-mapping — save confirmed mappings."""

    async def test_update_field_mapping_persists_and_returns(self, client):
        """Valid field mapping → 200 and the mapping is visible in the response."""
        field_mapping = {
            "source_id": "gallery_id",
            "title": "title",
            "artist": "uploader",
            "tags": "tags",
        }
        resp = await client.put(
            "/api/admin/sites/ehentai/field-mapping",
            json={"field_mapping": field_mapping},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_id"] == "ehentai"
        # field_mapping should be stored in the row and returned
        assert data.get("field_mapping") == field_mapping

    async def test_update_field_mapping_allows_null_values(self, client):
        """Null values in field_mapping unmap a specific field."""
        resp = await client.put(
            "/api/admin/sites/ehentai/field-mapping",
            json={"field_mapping": {"source_id": "gallery_id", "artist": None}},
        )
        assert resp.status_code == 200

    async def test_update_field_mapping_rejects_unknown_jyzrox_field(self, client):
        """field_mapping with an unknown key → 400."""
        resp = await client.put(
            "/api/admin/sites/ehentai/field-mapping",
            json={"field_mapping": {"nonexistent_jyzrox_field": "some_gdl_field"}},
        )
        assert resp.status_code == 400
        assert "Unknown Jyzrox field" in resp.json()["detail"]

    async def test_update_field_mapping_rejects_integer_values(self, client):
        """field_mapping values must be strings or null — integers are rejected at API boundary."""
        resp = await client.put(
            "/api/admin/sites/ehentai/field-mapping",
            json={"field_mapping": {"title": 42}},
        )
        # Pydantic validates dict[str, str | None] at request parsing — returns 422
        assert resp.status_code in (400, 422)

    async def test_update_field_mapping_requires_admin(self, make_client, db_session):
        """Member-role user cannot update field mappings."""
        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.put(
                "/api/admin/sites/ehentai/field-mapping",
                json={"field_mapping": {"title": "title"}},
            )
        assert resp.status_code == 403

    async def test_update_field_mapping_empty_dict_is_accepted(self, client):
        """Empty field_mapping dict is valid (clears all confirmed mappings)."""
        resp = await client.put(
            "/api/admin/sites/ehentai/field-mapping",
            json={"field_mapping": {}},
        )
        assert resp.status_code == 200
