# Download System v3.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Offload rate limiting, archive management, content integrity, and media conversion from custom Python to gallery-dl native config parameters.

**Architecture:** All changes center on `_build_gallery_dl_config()` — a single function that generates the per-job JSON config. gallery-dl's postprocessors produce sidecar files (`.sha256`, updated cookies) consumed by the import pipeline. The adaptive engine shrinks from a 300-line Lua state machine to an 80-line credential-warning tracker.

**Tech Stack:** gallery-dl config JSON, PostgreSQL archive backend, psycopg[binary], gallery-dl postprocessors (hash, mtime, ugoira)

**Spec:** `docs/ref/download-system-v3.0-design.md`

---

## File Map

### Modified files

| File | Changes |
|------|---------|
| `backend/core/config.py` | Remove `data_archive_path`; add `gdl_archive_dsn` helper property |
| `backend/core/adaptive.py` | Rewrite: delete Lua 429/503/timeout/success branches, shrink AdaptiveState to 3 fields, simplify AdaptiveSignal enum |
| `backend/plugins/builtin/gallery_dl/source.py` | Rewrite `_build_gallery_dl_config()` with all N1-N9 features; simplify `_read_stderr()`; delete adaptive overlay; simplify `_validate_download_content()` |
| `backend/plugins/builtin/gallery_dl/_sites.py` | No changes (archive format uses gallery-dl defaults) |
| `backend/plugins/models.py` | Add `unsupported_urls` field to `DownloadResult` |
| `backend/worker/progressive.py` | Read `.sha256` sidecar; use `st_mtime` for `added_at` |
| `backend/worker/download.py` | Forward `job_context` + `last_completed_at` to config builder; add cookie writeback in finally; capture `unsupported_urls` |
| `backend/worker/gallery_dl_venv.py` | Install `psycopg[binary]` alongside gallery-dl |
| `backend/routers/library.py` | Rewrite `_cleanup_archive_entries()` to use PostgreSQL |
| `backend/core/site_config.py` | Add `browser_profile`, `proxy_url`, `rate_limit` to `DownloadParams`; update `_DOWNLOAD_FIELDS` whitelist and `_merge()` |
| `backend/worker/__init__.py` | Simplify adaptive startup load; remove archive-related references |
| `backend/worker/subscription.py` | Inject `job_context="subscription"` and `last_completed_at` into download options |
| `backend/tests/test_adaptive.py` | Rewrite for simplified adaptive engine |
| `backend/tests/test_gallery_dl_config.py` | Add tests for all new config features |
| `backend/tests/test_progressive.py` | Add sidecar + mtime tests |

### No new files created

All changes modify existing files. No new modules.

---

## Task 1: Simplify AdaptiveSignal Enum and AdaptiveState

**Files:**
- Modify: `backend/core/adaptive.py:31-64`
- Test: `backend/tests/test_adaptive.py`

- [ ] **Step 1: Write failing tests for simplified AdaptiveState**

```python
# In test_adaptive.py — replace existing AdaptiveState/Signal tests

def test_adaptive_state_v3_has_three_fields():
    from core.adaptive import AdaptiveState
    s = AdaptiveState()
    assert s.credential_warning is False
    assert s.last_signal is None
    assert s.last_signal_at is None
    assert not hasattr(s, "sleep_multiplier")
    assert not hasattr(s, "http_timeout_add")
    assert not hasattr(s, "consecutive_success")


def test_adaptive_signal_v3_only_credential_signals():
    from core.adaptive import AdaptiveSignal
    assert AdaptiveSignal.HTTP_403
    assert AdaptiveSignal.HTML_RESPONSE
    # These should NOT exist
    for removed in ("HTTP_429", "HTTP_503", "TIMEOUT", "CONNECTION_ERROR", "SUCCESS", "EMPTY_FILE"):
        assert not hasattr(AdaptiveSignal, removed)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_adaptive.py::test_adaptive_state_v3_has_three_fields tests/test_adaptive.py::test_adaptive_signal_v3_only_credential_signals -v`
Expected: FAIL (old fields still exist)

- [ ] **Step 3: Rewrite AdaptiveSignal enum and AdaptiveState**

In `backend/core/adaptive.py`, replace lines 31-64:

```python
class AdaptiveSignal(str, Enum):
    HTTP_403 = "http_403"
    HTML_RESPONSE = "html_response"


@dataclass
class AdaptiveState:
    credential_warning: bool = False
    last_signal: str | None = None
    last_signal_at: str | None = None

    @staticmethod
    def from_dict(data: dict) -> AdaptiveState:
        try:
            return AdaptiveState(
                credential_warning=bool(data.get("credential_warning", False)),
                last_signal=data.get("last_signal") or None,
                last_signal_at=data.get("last_signal_at") or None,
            )
        except (ValueError, TypeError, AttributeError):
            return AdaptiveState()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_adaptive.py::test_adaptive_state_v3_has_three_fields tests/test_adaptive.py::test_adaptive_signal_v3_only_credential_signals -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/patrick339/Jyzrox && git add backend/core/adaptive.py backend/tests/test_adaptive.py && git commit -m "feat(v3): simplify AdaptiveSignal enum and AdaptiveState to credential-only"
```

---

## Task 2: Rewrite Lua Script and AdaptiveEngine

**Files:**
- Modify: `backend/core/adaptive.py:70-300`
- Test: `backend/tests/test_adaptive.py`

- [ ] **Step 1: Write failing tests for simplified engine**

```python
@pytest.mark.asyncio
async def test_record_403_sets_credential_warning():
    from core.adaptive import AdaptiveEngine, AdaptiveSignal
    engine = AdaptiveEngine()
    mock_redis = MagicMock()
    mock_redis.eval = AsyncMock(return_value=b'{"credential_warning":true,"last_signal":"http_403","last_signal_at":"2026-01-01T00:00:00"}')
    with patch("core.redis_client.get_redis", return_value=mock_redis):
        state = await engine.record_signal("ehentai", AdaptiveSignal.HTTP_403)
    assert state.credential_warning is True
    assert state.last_signal == "http_403"


@pytest.mark.asyncio
async def test_record_html_response_sets_credential_warning():
    from core.adaptive import AdaptiveEngine, AdaptiveSignal
    engine = AdaptiveEngine()
    mock_redis = MagicMock()
    mock_redis.eval = AsyncMock(return_value=b'{"credential_warning":true,"last_signal":"html_response","last_signal_at":"2026-01-01T00:00:00"}')
    with patch("core.redis_client.get_redis", return_value=mock_redis):
        state = await engine.record_signal("ehentai", AdaptiveSignal.HTML_RESPONSE)
    assert state.credential_warning is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_adaptive.py::test_record_403_sets_credential_warning tests/test_adaptive.py::test_record_html_response_sets_credential_warning -v`
Expected: FAIL

- [ ] **Step 3: Rewrite Lua script and AdaptiveEngine**

Replace `_SIGNAL_LUA`, `parse_adaptive_signal()`, delete `_RE_429`, `_RE_503`, `_RE_TIMEOUT`, `_RE_CONN`. Keep `_RE_403`. Replace engine methods.

New Lua script (in `core/adaptive.py`):

```python
_SIGNAL_LUA = """
local key = KEYS[1]
local source_id = ARGV[1]
local signal = ARGV[2]
local ttl = tonumber(ARGV[3])
local now_str = ARGV[4]
local dirty_key = "adaptive:dirty"

local raw = redis.call('GET', key)
local state
if raw then
    state = cjson.decode(raw)
else
    state = {credential_warning = false, last_signal = false, last_signal_at = false}
end

if signal == 'http_403' or signal == 'html_response' then
    state['credential_warning'] = true
end

state['last_signal'] = signal
state['last_signal_at'] = now_str

local new_raw = cjson.encode(state)
redis.call('SET', key, new_raw, 'EX', ttl)
redis.call('SADD', dirty_key, source_id)
return new_raw
"""
```

Delete `parse_adaptive_signal()` function entirely.
Delete regex patterns `_RE_429`, `_RE_503`, `_RE_TIMEOUT`, `_RE_CONN`.
Keep `_RE_403` for use in `source.py:_read_stderr()`.

Update `record_signal()` — remove `count` parameter:

```python
async def record_signal(self, source_id: str, signal: AdaptiveSignal) -> AdaptiveState:
    from core.redis_client import get_redis
    r = get_redis()
    key = f"adaptive:{source_id}"
    now_str = datetime.now(UTC).isoformat()
    raw = await r.eval(self._SIGNAL_LUA, 1, key, source_id, signal.value, str(_ADAPTIVE_TTL), now_str)
    return self._parse_raw(raw)
```

Rewrite `persist_dirty()` — only persists `credential_warning`:

```python
async def persist_dirty(self) -> int:
    """Flush dirty credential_warning states to DB. Cron every 5 min."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from core.database import AsyncSessionLocal
    from core.redis_client import get_redis
    from db.models import SiteConfig

    r = get_redis()
    raw_items = await r.spop(self._DIRTY_KEY, _MAX_PERSIST_PER_RUN)
    if not raw_items:
        return 0
    items = raw_items if isinstance(raw_items, list) else [raw_items]

    persisted = 0
    async with AsyncSessionLocal() as session:
        for raw_sid in items:
            source_id = raw_sid.decode() if isinstance(raw_sid, bytes) else raw_sid
            try:
                state = await self.get_state(source_id)
                stmt = (
                    pg_insert(SiteConfig)
                    .values(source_id=source_id, overrides={},
                            adaptive={"credential_warning": state.credential_warning})
                    .on_conflict_do_update(
                        index_elements=["source_id"],
                        set_={"adaptive": {"credential_warning": state.credential_warning}},
                    )
                )
                await session.execute(stmt)
                persisted += 1
            except Exception:
                await r.sadd(self._DIRTY_KEY, source_id)
                logger.exception("[adaptive] persist failed for %s", source_id)
        await session.commit()
    return persisted
```

- [ ] **Step 4: Delete old test functions, run all adaptive tests**

Delete all tests that reference `sleep_multiplier`, `http_timeout_add`, `consecutive_success`, `parse_adaptive_signal`, `SUCCESS`, `HTTP_429`, `HTTP_503`, `TIMEOUT`, `CONNECTION_ERROR`, `EMPTY_FILE`.

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_adaptive.py -v`
Expected: PASS (all remaining tests)

- [ ] **Step 5: Commit**

```bash
cd /home/patrick339/Jyzrox && git add backend/core/adaptive.py backend/tests/test_adaptive.py && git commit -m "feat(v3): rewrite adaptive engine to credential-only Lua script, delete rate-limit state machine"
```

---

## Task 3: Rewrite `_read_stdout()` with `--Print`, Simplify `_read_stderr()` and `_validate_download_content()`

**Files:**
- Modify: `backend/plugins/builtin/gallery_dl/source.py:34-36,205-289,390-481`
- Test: `backend/tests/test_gallery_dl_source.py`

This task combines N11 (structured stdout) with N3/N4 simplifications.
`_read_stdout()` is completely rewritten from regex-based to prefix-based parsing.

- [ ] **Step 1: Delete regex constants and write test for structured stdout**

Delete `_FILE_PATH_RE`, `_FILE_PATH_EXTRACT_RE`, `_IMAGE_EXT_RE` at source.py:34-36.
Add new prefix constants:

```python
_PRINT_FILE_PREFIX = "JYZROX_FILE\t"
_PRINT_SKIP_PREFIX = "JYZROX_SKIP"
_PROGRESS_EVERY_N = 5
_PROGRESS_EVERY_S = 10.0
_MAX_STDERR_LINES = 10000
```

Write test:

```python
@pytest.mark.asyncio
async def test_read_stdout_parses_print_file_with_sha256():
    """N11: _read_stdout parses JYZROX_FILE lines with path + sha256."""
    from plugins.builtin.gallery_dl.source import _read_stdout, _DownloadState

    state = _DownloadState()
    captured_files = []

    async def on_file(path, sha256=None):
        captured_files.append((str(path), sha256))

    stdout_lines = [
        b"JYZROX_FILE\t/data/gallery/123/001.jpg\tabc123\n",
        b"JYZROX_FILE\t/data/gallery/123/002.jpg\tdef456\n",
        b"JYZROX_SKIP\n",
        b"JYZROX_SKIP\n",
    ]

    proc = MagicMock()
    proc.stdout = AsyncMock()
    proc.stdout.__aiter__ = MagicMock(return_value=iter(stdout_lines))

    # Mock _on_file_with_validation to pass through
    with patch("plugins.builtin.gallery_dl.source._on_file_with_validation") as mock_validate:
        mock_validate.side_effect = lambda fp, sha, state, proc, cb: cb(fp, sha) if cb else None
        await _read_stdout(proc, state, on_file, None)

    assert state.downloaded == 2
    assert state.skipped_count == 2
    assert len(captured_files) == 2
    assert captured_files[0] == ("/data/gallery/123/001.jpg", "abc123")
    assert captured_files[1] == ("/data/gallery/123/002.jpg", "def456")
```

- [ ] **Step 2: Rewrite `_read_stdout()` with prefix matching**

Replace the entire function (source.py:205-270) with the N11 design:

```python
async def _read_stdout(
    proc: asyncio.subprocess.Process,
    state: _DownloadState,
    on_file: Callable[[Path, str | None], Awaitable[None]] | None,
    on_progress: Callable[[int, int], Awaitable[None]] | None,
    timing_ctx: dict | None = None,
) -> None:
    """Parse structured --Print output. No regex needed."""
    assert proc.stdout is not None

    async for raw_line in proc.stdout:
        now = asyncio.get_event_loop().time()
        if timing_ctx is not None:
            timing_ctx["idle_ms"] = round((now - state.last_activity) * 1000) if state.last_activity > 0 else 0
            timing_ctx["total_pause_ms"] = round(state.total_paused * 1000)
        state.last_activity = now
        line = raw_line.decode("utf-8", errors="replace").rstrip()

        if line.startswith(_PRINT_FILE_PREFIX):
            parts = line[len(_PRINT_FILE_PREFIX):].split("\t", 1)
            file_path = Path(parts[0])
            sha256 = parts[1] if len(parts) > 1 and parts[1] else None

            state.downloaded += 1
            if timing_ctx is not None:
                if state.last_page_time > 0:
                    timing_ctx["last_page_ms"] = round((now - state.last_page_time) * 1000)
                state.last_page_time = now

            if on_file:
                try:
                    await _on_file_with_validation(file_path, sha256, state, proc, on_file)
                except Exception as exc:
                    logger.warning("[gallery_dl] import error: %s", exc)

        elif line.startswith(_PRINT_SKIP_PREFIX):
            state.skipped_count += 1

        total_seen = state.downloaded + state.skipped_count
        if total_seen > 0 and (total_seen % _PROGRESS_EVERY_N == 0 or (now - state.last_progress_update) >= _PROGRESS_EVERY_S):
            state.last_progress_update = now
            if on_progress:
                try:
                    await on_progress(total_seen, 0)
                except Exception:
                    pass
```

- [ ] **Step 3: Update `_on_file_with_validation()` signature to accept sha256**

Add `sha256: str | None` parameter. Pass through to `inner_on_file`:

```python
async def _on_file_with_validation(
    file_path: Path,
    sha256: str | None,
    state: _DownloadState,
    proc: asyncio.subprocess.Process,
    inner_on_file: Callable[[Path, str | None], Awaitable[None]] | None,
) -> None:
    # ... HTML check unchanged ...
    if inner_on_file:
        await inner_on_file(file_path, sha256)
```

Also fix the HTML_RESPONSE ×3 block (remove `HTTP_429` references, keep only
`ADAPTIVE_BLOCKED` event) and simplify empty file branch as described below.

- [ ] **Step 4: Remove `pending_file` from `_DownloadState`**

Delete `pending_file: Path | None = None` field. N11's `--Print "after:..."` fires
once per completed file — no "current file is next line's context" ambiguity.

- [ ] **Step 5: Write failing test for simplified stderr**

```python
@pytest.mark.asyncio
async def test_read_stderr_ignores_429_only_detects_403():
    """v3: _read_stderr should not call adaptive for 429, only 403."""
    from plugins.builtin.gallery_dl.source import _read_stderr, _DownloadState
    import asyncio

    state = _DownloadState()
    state.source_id = "ehentai"

    # Create a mock process with stderr lines
    stderr_lines = [
        b"HTTP Error 429 Too Many Requests\n",
        b"HTTP Error 403 Forbidden\n",
    ]
    proc = MagicMock()
    proc.stderr = AsyncMock()
    proc.stderr.__aiter__ = MagicMock(return_value=iter(stderr_lines))

    mock_engine = MagicMock()
    mock_engine.record_signal = AsyncMock()

    with patch("core.adaptive.adaptive_engine", mock_engine):
        await _read_stderr(proc, state)

    # Only 403 should trigger a signal, not 429
    assert mock_engine.record_signal.call_count == 1
    call_args = mock_engine.record_signal.call_args
    assert call_args[0][1].value == "http_403"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_gallery_dl_source.py::test_read_stderr_ignores_429_only_detects_403 -v`
Expected: FAIL (currently detects 429 too)

- [ ] **Step 3: Rewrite `_read_stderr()`**

In `source.py`, replace lines 272-289:

```python
async def _read_stderr(
    proc: asyncio.subprocess.Process,
    state: _DownloadState,
) -> None:
    """Accumulate stderr for error reporting. Detect 403 for credential warnings only.

    v3.0: rate-limit signals (429/503/timeout) offloaded to gallery-dl's
    native sleep-429 and sleep-retries config. Only credential-related
    signals (403) are still tracked by the adaptive engine.
    """
    assert proc.stderr is not None
    from core.adaptive import _RE_403, AdaptiveSignal, adaptive_engine

    async for raw_line in proc.stderr:
        line = raw_line.decode("utf-8", errors="replace").rstrip()
        if line and len(state.stderr_lines) < _MAX_STDERR_LINES:
            state.stderr_lines.append(line)
        if state.source_id and _RE_403.search(line):
            try:
                await adaptive_engine.record_signal(state.source_id, AdaptiveSignal.HTTP_403)
            except Exception:
                pass
```

- [ ] **Step 4: Simplify `_validate_download_content()` — keep empty file safety net**

gallery-dl's `filesize-min` checks HTTP `Content-Length` header, but doesn't catch:
chunked transfer (no header), incorrect Content-Length, or write failures producing
0-byte files. Keep the empty file check as defense-in-depth, but remove the
`EMPTY_FILE` adaptive signal (no rate-limit adjustment needed for disk I/O failures):

```python
def _validate_download_content(file_path: Path) -> str | None:
    """Check for HTML masquerading as media, plus empty file safety net."""
    try:
        size = file_path.stat().st_size
    except OSError:
        return None
    if size == 0:
        return "empty"
    if size < 102400:  # < 100KB — possible HTML error page
        try:
            head = file_path.read_bytes()[:512]
            text = head.decode("utf-8", errors="replace").lower()
            if "<!doctype" in text or "<html" in text or "cf-browser-verification" in text:
                return "html"
        except OSError:
            pass
    return None
```

In `_on_file_with_validation()`, change the `elif result == "empty":` branch to
simply skip the file (delete it) without recording an adaptive signal:

```python
    elif result == "empty":
        # Safety net: gallery-dl's filesize-min may miss this (chunked transfer)
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
        return
```

In `_on_file_with_validation()`:
- Simplify the `elif result == "empty":` branch (lines 479-481): keep the file
  deletion but remove the `AdaptiveSignal.EMPTY_FILE` recording (signal no longer exists).
- **Critical**: Remove the `HTTP_429` references at lines 462-465. The v2.3 design sent
  two `HTTP_429` signals when `html_response_count == 3` to trigger `sleep_multiplier *= 4`.
  v3.0 no longer has `HTTP_429` in the enum or `sleep_multiplier` in the state. Replace
  the entire `elif state.html_response_count >= 3:` block — keep only the
  `ADAPTIVE_BLOCKED` event emission:

```python
        elif state.html_response_count >= 3:
            from core.events import EventType, emit_safe
            await emit_safe(
                EventType.ADAPTIVE_BLOCKED,
                resource_type="download",
                source_id=state.source_id,
                html_response_count=state.html_response_count,
            )
```

- [ ] **Step 5: Delete adaptive sleep overlay in `_build_gallery_dl_config()`**

Delete source.py lines 122-151 (the block that reads `adaptive:{source_id}` from Redis and multiplies `sleep-request`).

Delete source.py lines 569-575 (adaptive `http_timeout` calculation). Replace with static `http_timeout` from `DownloadParams`:

```python
if _dl_params.http_timeout != 30:
    cmd += ["--http-timeout", str(_dl_params.http_timeout)]
```

- [ ] **Step 6: Delete success signal flushing**

Remove `_flush_success_signals()` function and all calls to it in `_read_stdout()`. Remove `pending_success_count` from `_DownloadState`.

- [ ] **Step 7: Run full test suite**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_gallery_dl_source.py tests/test_adaptive.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
cd /home/patrick339/Jyzrox && git add backend/plugins/builtin/gallery_dl/source.py backend/core/adaptive.py backend/tests/ && git commit -m "feat(v3): simplify _read_stderr to 403-only, delete adaptive sleep overlay and success flushing"
```

---

## Task 4: Create CASCADE Archive Tables in init.sql

**Files:**
- Modify: `db/init.sql`
- Modify: `backend/worker/progressive.py` (add `_link_archive_entries`)
- Modify: `backend/routers/library.py` (delete archive cleanup)
- Modify: `backend/worker/subscription.py` (remove `skip_archive`)
- Test: `backend/tests/test_gallery_dl_config.py`

This is the core N1 deep-integration task: pre-create archive tables with
`gallery_id FK → galleries(id) ON DELETE CASCADE`, link entries after import,
and delete all manual archive cleanup code.

- [ ] **Step 1: Add archive tables to init.sql**

Append to `db/init.sql`:

```sql
-- ── gallery-dl archive tables (v3.0) ────────────────────────────────
-- gallery-dl only reads/writes the 'entry' column.
-- Jyzrox adds gallery_id FK for CASCADE lifecycle management.
-- Tables are named by gallery-dl category (archive-table: "{category}").

CREATE TABLE IF NOT EXISTS exhentai (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    job_id      UUID,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_exhentai_unlinked ON exhentai (job_id) WHERE gallery_id IS NULL;

CREATE TABLE IF NOT EXISTS pixiv (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    job_id      UUID,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pixiv_unlinked ON pixiv (job_id) WHERE gallery_id IS NULL;

CREATE TABLE IF NOT EXISTS twitter (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    job_id      UUID,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_twitter_unlinked ON twitter (job_id) WHERE gallery_id IS NULL;

CREATE TABLE IF NOT EXISTS instagram (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS danbooru (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gelbooru (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Add remaining sources from GDL_SITES as needed.
-- Pattern: CREATE TABLE IF NOT EXISTS {source_id_or_extractor} (
--     entry TEXT PRIMARY KEY,
--     gallery_id BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
--     created_at TIMESTAMPTZ DEFAULT now()
-- );
```

Generate one table per unique `extractor or source_id` in `GDL_SITES`.
gallery-dl uses `{category}` which maps to the extractor name.

- [ ] **Step 2: Add `_link_archive_entries()` to ProgressiveImporter**

In `backend/worker/progressive.py`, add `_job_started_at` to `__init__()`:

```python
self._job_started_at = datetime.now(UTC)
```

Add the linking method with dual-strategy matching (prefix + job_id):

```python
async def _link_archive_entries(self, session) -> None:
    """Link gallery-dl archive entries to this gallery via gallery_id FK.

    Strategy 1: LIKE by source_id prefix (E-Hentai, Pixiv, booru).
    Strategy 2: job_id + time window (Twitter, etc. where source_id != archive key prefix).
    job_id IS NULL prevents race conditions between concurrent downloads.
    """
    if not (self.gallery_id and self.source):
        return
    from plugins.builtin.gallery_dl._sites import get_site_config
    from sqlalchemy import text

    cfg = get_site_config(self.source)
    table = cfg.extractor or cfg.source_id

    try:
        exists = (await session.execute(
            text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :t)"),
            {"t": table},
        )).scalar()
        if not exists:
            return

        # Strategy 1: LIKE match by source_id prefix
        if self.source_id:
            prefix = f"{self.source_id}%"
            result = await session.execute(
                text(f'UPDATE "{table}" SET gallery_id = :gid '
                     f'WHERE gallery_id IS NULL AND entry LIKE :prefix'),
                {"gid": self.gallery_id, "prefix": prefix},
            )
            if result.rowcount:
                logger.info("[progressive] linked %d entries (prefix)", result.rowcount)
                return

        # Strategy 2: time window + job_id exclusion (race-safe)
        if self.db_job_id:
            result = await session.execute(
                text(f'UPDATE "{table}" SET gallery_id = :gid, job_id = :jid '
                     f'WHERE gallery_id IS NULL AND job_id IS NULL '
                     f'AND created_at BETWEEN :start AND :end'),
                {
                    "gid": self.gallery_id,
                    "jid": self.db_job_id,
                    "start": self._job_started_at,
                    "end": datetime.now(UTC),
                },
            )
            if result.rowcount:
                logger.info("[progressive] linked %d entries (job_id)", result.rowcount)

    except Exception as exc:
        logger.warning("[progressive] failed to link archive entries: %s", exc)
```

Call in `finalize()` inside the existing session block, before `session.commit()`.

- [ ] **Step 3: Delete `_cleanup_archive_entries()` and all callers**

In `backend/routers/library.py`:
- Delete `_cleanup_archive_entries()` function (lines 50-61)
- Delete archive key reconstruction (lines 1531-1536)
- Delete archive cleanup call (lines 1581-1585)
- Remove `sqlite3` import

- [ ] **Step 4: Remove `skip_archive` logic from subscription.py**

In `backend/worker/subscription.py`, delete lines 96-115 (the entire
`skip_archive` decision block). Replace with:

```python
options = None  # v3.0: archive always active, lifecycle via CASCADE
```

- [ ] **Step 5: Write test for archive lifecycle**

```python
@pytest.mark.asyncio
async def test_v3_config_does_not_set_archive_format():
    """v3.0: archive-format uses gallery-dl defaults, not overridden."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config
    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    # archive-table is set, but archive-format is NOT (gallery-dl defaults)
    assert config["extractor"]["archive-table"] == "{category}"
    assert "archive-format" not in config["extractor"]
```

- [ ] **Step 6: Run tests**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_gallery_dl_config.py tests/test_download_worker.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /home/patrick339/Jyzrox && git add db/init.sql backend/worker/progressive.py backend/routers/library.py backend/worker/subscription.py backend/tests/test_gallery_dl_config.py && git commit -m "feat(v3): CASCADE-linked archive tables, delete manual archive cleanup, link entries in finalize()"
```

---

## Task 5: Expand DownloadParams with v3.0 Fields

**Files:**
- Modify: `backend/core/site_config.py` (DownloadParams dataclass + validation)

- [ ] **Step 1: Add fields to DownloadParams**

```python
@dataclass
class DownloadParams:
    retries: int = 4
    http_timeout: int = 30
    sleep_request: float | tuple[float, float] | None = None
    concurrency: int = 2
    inactivity_timeout: int = 300
    # v3.0
    browser_profile: str | None = None
    proxy_url: str | None = None
    rate_limit: str | None = None
```

- [ ] **Step 2: Update `_DOWNLOAD_FIELDS` whitelist**

In `backend/core/site_config.py`, update the whitelist at line 27:

```python
_DOWNLOAD_FIELDS = {
    "retries", "http_timeout", "sleep_request", "concurrency", "inactivity_timeout",
    "browser_profile", "proxy_url", "rate_limit",  # v3.0
}
```

This is **critical** — without this, `_merge()` will silently ignore DB overrides for
the new v3.0 fields. The `_merge()` function at lines 316-326 iterates `_DOWNLOAD_FIELDS`
when applying both adaptive and manual override layers.

- [ ] **Step 3: Add validation in `_validate_overrides()`**

```python
if "browser_profile" in dl:
    bp = dl["browser_profile"]
    if bp is not None and bp not in ("chrome", "firefox"):
        raise ValueError("browser_profile must be 'chrome', 'firefox', or null")
if "proxy_url" in dl:
    pu = dl["proxy_url"]
    if pu is not None and not pu.startswith(("http://", "https://", "socks5://")):
        raise ValueError("proxy_url must start with http://, https://, or socks5://")
```

- [ ] **Step 4: Run existing site config tests**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/ -k "site_config" -v`
Expected: PASS (new fields have defaults, backward compatible)

- [ ] **Step 5: Commit**

```bash
cd /home/patrick339/Jyzrox && git add backend/core/site_config.py && git commit -m "feat(v3): expand DownloadParams with browser_profile, proxy_url, rate_limit"
```

---

## Task 6: Rewrite `_build_gallery_dl_config()` with All v3.0 Features

**Files:**
- Modify: `backend/plugins/builtin/gallery_dl/source.py:88-184`
- Modify: `backend/core/config.py`
- Test: `backend/tests/test_gallery_dl_config.py`

This is the core task. All N1-N9 features converge here.

- [ ] **Step 1: Write failing tests for new config output**

```python
@pytest.mark.asyncio
async def test_v3_config_has_pg_archive(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config
    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert "archive" in config["extractor"]
    assert config["extractor"]["archive"].startswith("postgresql://")
    assert config["extractor"]["archive-table"] == "{category}"


@pytest.mark.asyncio
async def test_v3_config_has_native_rate_limiting(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config
    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert "sleep-429" in config["extractor"]
    assert "sleep-retries" in config["extractor"]


@pytest.mark.asyncio
async def test_v3_config_has_file_unique(mock_config_path):
    """N10b: file-unique prevents duplicate URLs within a single run."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config
    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["file-unique"] is True


@pytest.mark.asyncio
async def test_v3_subscription_has_archive_mode_memory(mock_config_path):
    """N10a: subscription jobs use archive-mode memory for batch writes."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config
    await _build_gallery_dl_config({}, job_context="subscription")
    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["archive-mode"] == "memory"


@pytest.mark.asyncio
async def test_v3_manual_no_archive_mode_memory(mock_config_path):
    """Manual downloads keep default archive-mode (file)."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config
    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert "archive-mode" not in config["extractor"]


@pytest.mark.asyncio
async def test_v3_metadata_pp_with_include_filter(mock_config_path):
    """N10d: metadata PP with include filter replaces --write-metadata --write-tags."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config
    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    meta_pps = [pp for pp in config["postprocessors"] if pp["name"] == "metadata"]
    assert len(meta_pps) == 1
    assert "include" in meta_pps[0]
    assert "title" in meta_pps[0]["include"]
    assert "tags" in meta_pps[0]["include"]


@pytest.mark.asyncio
async def test_v3_config_has_postprocessors(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config
    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    pp_names = [pp["name"] for pp in config.get("postprocessors", [])]
    assert "hash" in pp_names
    assert "mtime" in pp_names


@pytest.mark.asyncio
async def test_v3_config_has_content_integrity(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config
    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["filesize-min"] == "1k"
    assert config["downloader"]["adjust-extensions"] is True


@pytest.mark.asyncio
async def test_v3_subscription_context_has_abort_and_date(mock_config_path):
    from datetime import datetime, UTC
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config
    last = datetime(2026, 3, 15, 8, 0, 0, tzinfo=UTC)
    await _build_gallery_dl_config({}, job_context="subscription", last_completed_at=last)
    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["skip"] == "abort:10"
    assert "date-after" in config["extractor"]


@pytest.mark.asyncio
async def test_v3_manual_context_no_abort(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config
    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert "skip" not in config["extractor"] or config["extractor"].get("skip") != "abort:10"


@pytest.mark.asyncio
async def test_v3_pixiv_has_ugoira_pp(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config
    await _build_gallery_dl_config({"pixiv": "token123"})
    config = json.loads(mock_config_path.read_text())
    pp_names = [pp["name"] for pp in config.get("postprocessors", [])]
    assert "ugoira" in pp_names


@pytest.mark.asyncio
async def test_v3_non_pixiv_no_ugoira(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config
    await _build_gallery_dl_config({"ehentai": '{"ipb_member_id": "1", "ipb_pass_hash": "x"}'})
    config = json.loads(mock_config_path.read_text())
    pp_names = [pp["name"] for pp in config.get("postprocessors", [])]
    assert "ugoira" not in pp_names


@pytest.mark.asyncio
async def test_v3_archive_format_not_overridden(mock_config_path):
    """v3.0 uses gallery-dl's per-extractor defaults — no archive-format in config."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config
    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert "archive-format" not in config["extractor"]
    assert config["extractor"]["archive-table"] == "{category}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_gallery_dl_config.py -k "v3" -v`
Expected: FAIL

- [ ] **Step 3: Add `gdl_archive_dsn` helper to config.py**

In `backend/core/config.py`, add a property that builds the PostgreSQL connection string for gallery-dl from the existing `database_url`:

```python
@property
def gdl_archive_dsn(self) -> str:
    """Build a psycopg-compatible DSN from the asyncpg database_url.

    Converts: postgresql+asyncpg://user:pass@host:port/db
    To:       postgresql://user:pass@host:port/db
    """
    return self.database_url.replace("+asyncpg", "")
```

Also delete `data_archive_path` line.

- [ ] **Step 4: Rewrite `_build_gallery_dl_config()`**

Replace the entire function with the v3.0 version from the design spec. Key changes:
- New signature: `async def _build_gallery_dl_config(credentials, config_id=None, job_context="manual", last_completed_at=None)`
- Config base includes: `archive`, `archive-table`, `sleep-retries`, `sleep-429`, `filesize-min`, postprocessors
- Per-site: `browser`, `proxy`
- Job context: `skip: "abort:10"` + `date-after` for subscriptions
- Pixiv: ugoira PP
- Cookie-based sources: `cookies-update`
- Delete: adaptive sleep overlay block (was lines 122-151)

- [ ] **Step 5: Update `mock_config_path` fixture**

The fixture needs to mock `gdl_archive_dsn`:

```python
@pytest.fixture
def mock_config_path(tmp_path):
    config_file = tmp_path / "gallery-dl.json"
    with patch("plugins.builtin.gallery_dl.source.settings") as mock_settings:
        mock_settings.data_gallery_path = "/data/gallery"
        mock_settings.gallery_dl_config = str(config_file)
        mock_settings.gdl_archive_dsn = "postgresql://test:test@localhost:5432/test"
        yield config_file
```

- [ ] **Step 6: Run all config tests**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_gallery_dl_config.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /home/patrick339/Jyzrox && git add backend/core/config.py backend/plugins/builtin/gallery_dl/source.py backend/tests/test_gallery_dl_config.py && git commit -m "feat(v3): rewrite _build_gallery_dl_config with PG archive, native rate-limiting, postprocessors, subscription optimization"
```

---

## Task 7: Update `download()` CLI Flags and `download_job()` Forwarding

**Files:**
- Modify: `backend/plugins/builtin/gallery_dl/source.py:520-600`
- Modify: `backend/worker/download.py`
- Modify: `backend/plugins/models.py:95-100`

- [ ] **Step 1: Add `unsupported_urls` to DownloadResult**

In `plugins/models.py`:

```python
class DownloadResult(BaseModel):
    status: Literal["done", "cancelled", "failed", "partial"]
    downloaded: int
    total: int
    failed_pages: list[int] = []
    error: str | None = None
    unsupported_urls: list[str] = []  # v3.0: N9
```

- [ ] **Step 2: Update `download()` method signature and CLI flags**

In `source.py` `download()` method:
- Remove `--download-archive` CLI flag (archive now in config file via N1)
- Remove `--write-metadata` and `--write-tags` CLI flags (replaced by N10d metadata PP)
- Add `--Print "after:JYZROX_FILE\t{_path}\t{sha256}"` (N11: structured file output)
- Add `--Print "skip:JYZROX_SKIP"` (N11: structured skip output)
- Add `--write-unsupported /tmp/gdl-unsupported-{config_id}.txt` (N9)
- Add `--error-file /tmp/gdl-errors-{config_id}.txt` (N12)
- Remove adaptive `http_timeout` adjustment (use static `DownloadParams.http_timeout`)
- Pass `job_context` and `last_completed_at` to `_build_gallery_dl_config()`

```python
config_path = await _build_gallery_dl_config(
    credentials,
    config_id=options.get("config_id") if options else None,
    job_context=(options or {}).get("job_context", "manual"),
    last_completed_at=...,  # parsed from options
)
```

- [ ] **Step 3: Update `download_job()` to forward context**

In `worker/download.py`, add to the options dict before calling `plugin.download()`:

```python
opts["job_context"] = (options or {}).get("job_context", "manual")
opts["last_completed_at"] = (options or {}).get("last_completed_at")
```

- [ ] **Step 4: Add unsupported URL + error URL capture in download result**

After process completes in `source.py`, read both files:

```python
def _read_url_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return [l.strip() for l in path.read_text().splitlines() if l.strip()]
    except OSError:
        return []
    finally:
        path.unlink(missing_ok=True)

unsupported_urls = _read_url_file(Path(f"/tmp/gdl-unsupported-{config_id}.txt"))
error_urls = _read_url_file(Path(f"/tmp/gdl-errors-{config_id}.txt"))
```

Include in `DownloadResult(unsupported_urls=unsupported_urls, error_urls=error_urls)`.

Add `error_urls: list[str] = []` field to `DownloadResult` in `plugins/models.py`.

- [ ] **Step 5: Add cookie writeback in download_job() finally block**

In `download.py`, after download completes successfully, read cookie update files and save:

```python
import http.cookiejar

def _cookiestxt_to_dict(path: Path) -> dict[str, str]:
    """Parse Netscape cookies.txt into {name: value} dict."""
    jar = http.cookiejar.MozillaCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=True)
    return {c.name: c.value for c in jar}

# N8: cookie writeback (Netscape cookies.txt → JSON dict → encrypted DB)
if db_job_id and result.status in ("done", "partial"):
    from plugins.builtin.gallery_dl._sites import get_site_config
    for src in (credentials if isinstance(credentials, dict) else {}):
        cfg_site = get_site_config(src)
        if cfg_site.credential_type != "cookies":
            continue
        cookie_path = Path(f"/tmp/gdl-cookies-{db_job_id}-{src}.txt")
        if cookie_path.exists():
            try:
                updated = _cookiestxt_to_dict(cookie_path)
                original_raw = credentials.get(src, "{}")
                original = json.loads(original_raw) if isinstance(original_raw, str) else {}
                if updated and updated != original:
                    from services.credential import set_credential
                    await set_credential(src, json.dumps(updated), "cookies")
                    logger.info("[download] cookies updated for %s (%d cookies)", src, len(updated))
            except Exception as exc:
                logger.warning("[download] failed to update cookies for %s: %s", src, exc)
            finally:
                cookie_path.unlink(missing_ok=True)
```

- [ ] **Step 6: Modify `subscription.py` to inject job_context and last_completed_at (N2)**

In `backend/worker/subscription.py`, find `_enqueue_for_subscription()` where it builds the
options dict for `download_job`. Add subscription context:

```python
# In the options dict passed to enqueue_job("download_job", ...)
opts = {
    ...,  # existing options
    "job_context": "subscription",
    "last_completed_at": group.last_completed_at.isoformat() if group and group.last_completed_at else None,
}
```

The `group` object (the `SubscriptionGroup` row) must be passed through to this function.
Check how `check_subscription_group()` in `worker/subscription_group.py` calls
`_enqueue_for_subscription()` and ensure the group's `last_completed_at` is available.

- [ ] **Step 7: Run download worker tests**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_download_worker.py tests/test_gallery_dl_source.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
cd /home/patrick339/Jyzrox && git add backend/plugins/models.py backend/plugins/builtin/gallery_dl/source.py backend/worker/download.py backend/worker/subscription.py && git commit -m "feat(v3): update download CLI flags, add cookie writeback, unsupported URL capture, subscription context injection"
```

---

## Task 8: (Absorbed into Task 4)

Task 4 now covers all library.py and subscription.py archive changes.
This task is a no-op — skip to Task 9.

---

## Task 9: Update Progressive Importer (SHA256 from stdout + mtime)

**Files:**
- Modify: `backend/worker/progressive.py:235-298`
- Modify: `backend/worker/download.py` (on_file callback signature)
- Test: `backend/tests/test_progressive.py` (create if absent)

N11's `--Print` streams SHA256 directly in stdout. Progressive importer receives
it via the `on_file(path, sha256)` callback — no sidecar reading needed.

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_progressive_uses_provided_sha256(tmp_path):
    """N5+N11: SHA256 from --Print stdout passed directly, no sidecar or self-compute."""
    img = tmp_path / "test.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    from worker.progressive import ProgressiveImporter
    importer = ProgressiveImporter(None, None)
    importer.gallery_id = 1
    importer.source = "test"
    importer.source_id = "1"

    with patch("worker.progressive.AsyncSessionLocal") as mock_session_cls:
        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=1)))
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch("worker.progressive.store_blob") as mock_store:
            mock_store.return_value = MagicMock(sha256="provided_hash", extension=".jpg", storage="cas", external_path=None)
            with patch("worker.progressive.create_library_symlink", new_callable=AsyncMock):
                with patch("worker.progressive.generate_single_thumbnail", new_callable=AsyncMock):
                    # sha256 provided directly (from --Print stdout)
                    await importer._import_single(img, 1, sha256="provided_hash")

        mock_store.assert_called_once()
        assert mock_store.call_args[0][1] == "provided_hash"


@pytest.mark.asyncio
async def test_progressive_computes_sha256_when_not_provided(tmp_path):
    """Fallback: compute SHA256 when not provided (e.g., manual import)."""
    img = tmp_path / "test.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    from worker.progressive import ProgressiveImporter
    importer = ProgressiveImporter(None, None)
    importer.gallery_id = 1
    importer.source = "test"
    importer.source_id = "1"

    with patch("worker.progressive.AsyncSessionLocal") as mock_session_cls:
        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=1)))
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch("worker.progressive.store_blob") as mock_store:
            mock_store.return_value = MagicMock(sha256="computed", extension=".jpg", storage="cas", external_path=None)
            with patch("worker.progressive._sha256", return_value="computed"):
                with patch("worker.progressive.create_library_symlink", new_callable=AsyncMock):
                    with patch("worker.progressive.generate_single_thumbnail", new_callable=AsyncMock):
                        # No sha256 provided — should self-compute
                        await importer._import_single(img, 1, sha256=None)

        mock_store.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_progressive.py -v`
Expected: FAIL (`_import_single` doesn't accept `sha256` parameter yet)

- [ ] **Step 3: Update `import_file()` and `_import_single()` signatures**

In `progressive.py`:

```python
async def import_file(self, file_path: Path, sha256: str | None = None) -> None:
    # ... page_num assignment (unchanged) ...
    async def _do_import():
        async with self._sem:
            await self._import_single(file_path, page_num, sha256=sha256)
    # ...

async def _import_single(self, file_path: Path, page_num: int, sha256: str | None = None) -> None:
    # ...
    # N5+N11: SHA256 from --Print stdout, fallback to self-compute
    final_sha256 = sha256 or await asyncio.to_thread(_sha256, file_path)

    # N5: mtime PP sets original upload date
    try:
        mtime = file_path.stat().st_mtime
        added_at = datetime.fromtimestamp(mtime, tz=UTC)
        if added_at.year < 2000 or added_at > datetime.now(UTC):
            added_at = datetime.now(UTC)
    except (OSError, ValueError, OverflowError):
        added_at = datetime.now(UTC)
```

- [ ] **Step 4: Update `on_file` callback in `download_job()`**

In `worker/download.py`, update the callback to accept and forward sha256:

```python
async def on_file(file_path: Path, sha256: str | None = None):
    # ... existing gallery creation logic (unchanged, reads metadata JSON) ...
    await importer.import_file(file_path, sha256=sha256)
```

- [ ] **Step 5: Run tests**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_progressive.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /home/patrick339/Jyzrox && git add backend/worker/progressive.py backend/worker/download.py backend/tests/test_progressive.py && git commit -m "feat(v3): receive SHA256 from --Print stdout, use mtime for added_at, fallback to self-compute"
```

---

## Task 10: Install psycopg in gallery-dl venv

**Files:**
- Modify: `backend/worker/gallery_dl_venv.py:170-172`

- [ ] **Step 1: Update ensure_venv() pip install**

Change line 172 from:

```python
rc, _, stderr = await _run([pip_bin, "install", "gallery-dl"], timeout=120)
```

To:

```python
rc, _, stderr = await _run([pip_bin, "install", "gallery-dl", "psycopg[binary]"], timeout=120)
```

- [ ] **Step 2: Update upgrade flow**

Find the upgrade pip install command (~line 242-243) and add `psycopg[binary]`:

```python
pip_cmd = [str(new_dir / "bin/pip"), "install"]
if version:
    pip_cmd.append(f"gallery-dl=={version}")
else:
    pip_cmd += ["-U", "gallery-dl"]
pip_cmd.append("psycopg[binary]")  # v3.0: PostgreSQL archive backend
```

- [ ] **Step 3: Run venv tests**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_gallery_dl_venv.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd /home/patrick339/Jyzrox && git add backend/worker/gallery_dl_venv.py && git commit -m "feat(v3): install psycopg[binary] alongside gallery-dl in isolated venv"
```

---

## Task 11: Simplify Worker Startup + Archive Table Auto-upgrade

**Files:**
- Modify: `backend/worker/__init__.py`

- [ ] **Step 1: Simplify adaptive startup load**

In the worker startup function, find the `adaptive_engine.load_all_from_db()` call and simplify it. The v3.0 adaptive state is much smaller (only `credential_warning`), so the bulk loading can be simplified or removed if the engine falls back to DB on cache miss.

- [ ] **Step 2: Add archive table auto-upgrade check**

Add a startup function that detects archive tables gallery-dl created without
the `gallery_id` FK column (happens when a new extractor is used that wasn't
in `init.sql`):

```python
async def _ensure_archive_table_schema():
    """Ensure all gallery-dl archive tables have the gallery_id FK column."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("""
            SELECT t.table_name
            FROM information_schema.columns t
            WHERE t.column_name = 'entry'
              AND t.table_schema = 'public'
              AND t.table_name NOT IN (
                  SELECT table_name FROM information_schema.columns
                  WHERE column_name = 'gallery_id' AND table_schema = 'public'
              )
        """))
        tables = [row[0] for row in result]
        for table in tables:
            col_count = (await session.execute(text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_name = :t AND table_schema = 'public'"
            ), {"t": table})).scalar()
            if col_count != 1:
                continue  # not a gallery-dl archive table
            await session.execute(text(f'''
                ALTER TABLE "{table}"
                ADD COLUMN IF NOT EXISTS gallery_id BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
                ADD COLUMN IF NOT EXISTS job_id UUID,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()
            '''))
            logger.info("[archive] upgraded table '%s' with gallery_id FK", table)
        await session.commit()
```

Call in `startup()` before `recover_stale_jobs()`.

- [ ] **Step 3: Remove any archive verification references**

Remove any references to `_verify_archive()` or archive integrity checking in startup.

- [ ] **Step 4: Run worker tests**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_worker_recovery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/patrick339/Jyzrox && git add backend/worker/__init__.py && git commit -m "feat(v3): simplify worker startup, add archive table auto-upgrade"
```

---

## Task 12: Integration Test — Full Config Generation

**Files:**
- Test: `backend/tests/test_gallery_dl_config.py`

- [ ] **Step 1: Write comprehensive integration test**

```python
@pytest.mark.asyncio
async def test_v3_full_config_integration(mock_config_path):
    """Verify complete v3.0 config output with all features enabled."""
    from datetime import datetime, timezone
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    last = datetime(2026, 3, 15, 8, 0, 0, tzinfo=timezone.utc)
    credentials = {
        "ehentai": '{"cookies": {"ipb_member_id": "1"}}',
        "pixiv": "refresh_token_123",
    }
    config_path = await _build_gallery_dl_config(
        credentials,
        config_id="test-job-123",
        job_context="subscription",
        last_completed_at=last,
    )

    config = json.loads(config_path.read_text())

    # N1: PostgreSQL archive (CASCADE tables, no format override)
    assert config["extractor"]["archive"].startswith("postgresql://")
    assert config["extractor"]["archive-table"] == "{category}"
    assert "archive-format" not in config["extractor"]  # use gallery-dl defaults

    # N10a: subscription has archive-mode memory
    assert config["extractor"]["archive-mode"] == "memory"

    # N10b: file-unique
    assert config["extractor"]["file-unique"] is True

    # N2: subscription optimization
    assert config["extractor"]["skip"] == "abort:10"
    assert "date-after" in config["extractor"]

    # N3: native rate limiting
    assert "sleep-429" in config["extractor"]
    assert "sleep-retries" in config["extractor"]

    # N4: content integrity
    assert config["extractor"]["filesize-min"] == "1k"
    assert config["downloader"]["adjust-extensions"] is True

    # N5: postprocessors
    pp_names = [pp["name"] for pp in config["postprocessors"]]
    assert "hash" in pp_names
    assert "mtime" in pp_names

    # N10d: metadata PP with include filter (replaces --write-metadata)
    assert "metadata" in pp_names
    meta_pp = next(pp for pp in config["postprocessors"] if pp["name"] == "metadata")
    assert "include" in meta_pp

    # N6: ugoira (pixiv present in credentials)
    assert "ugoira" in pp_names

    # N8: cookies-update for EH (cookie-based auth)
    assert "cookies-update" in config["extractor"]["ehentai"]

    # Credentials merged correctly
    assert config["extractor"]["ehentai"]["cookies"] == {"ipb_member_id": "1"}
    assert config["extractor"]["pixiv"]["refresh-token"] == "refresh_token_123"
```

- [ ] **Step 2: Run the integration test**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest tests/test_gallery_dl_config.py::test_v3_full_config_integration -v`
Expected: PASS

- [ ] **Step 3: Run full backend test suite**

Run: `cd /home/patrick339/Jyzrox/backend && python -m pytest --timeout=60 -x -q`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
cd /home/patrick339/Jyzrox && git add backend/tests/test_gallery_dl_config.py && git commit -m "test(v3): add comprehensive integration test for v3.0 config generation"
```

---

## Task 13: Build and Verify

**Files:** None (verification only)

- [ ] **Step 1: Run full backend test suite**

```bash
cd /home/patrick339/Jyzrox/backend && python -m pytest --timeout=60 -q
```

Expected: All tests pass, no regressions.

- [ ] **Step 2: Type check**

```bash
cd /home/patrick339/Jyzrox/backend && python -m mypy core/adaptive.py plugins/builtin/gallery_dl/source.py worker/progressive.py --ignore-missing-imports 2>&1 | head -20
```

Expected: No new errors.

- [ ] **Step 3: Docker build**

```bash
cd /home/patrick339/Jyzrox && docker compose build api worker
```

Expected: Build succeeds.

- [ ] **Step 4: Final commit with all remaining changes**

If any files were missed in previous commits:

```bash
cd /home/patrick339/Jyzrox && git add -A && git status
```

Review and commit if needed.
