# Download System v3.0 Design

Offload-first redesign of the v2.3 download pipeline. Delegates rate limiting,
archive management, content integrity, and media conversion to gallery-dl's
native config system. Jyzrox retains only application-layer concerns:
progressive import, scheduling, credential management, and UI.

**Breaking change**: No migration from v2.3 data. PostgreSQL archive table
replaces SQLite. Adaptive engine state reset. Clean start.

---

## Overall Approach

**gallery-dl config-driven offloading.**

v2.3 built custom Python systems for problems gallery-dl already solves:
rate-limit backoff (Lua scripts), archive integrity (SQLite verification),
content validation (empty file detection), timeout adjustment (adaptive
http_timeout_add). v3.0 replaces these with gallery-dl config parameters
injected by `_build_gallery_dl_config()`.

```
v2.3:  Jyzrox Python code  >  gallery-dl subprocess  >  Jyzrox Python code
v3.0:  gallery-dl config    >  gallery-dl subprocess  >  sidecar files → import
```

### Two-Layer Architecture

```
gallery-dl layer (config-driven, zero custom Python)
├── Archive dedup          → PostgreSQL via "archive" connection string
├── Rate-limit backoff     → sleep-429, sleep-retries (per-request)
├── Content integrity      → adjust-extensions, filesize-min
├── Hash computation       → hash PP, result streamed via --Print
├── Timestamp preservation → mtime postprocessor
├── Media conversion       → ugoira postprocessor (Pixiv → MP4)
├── Subscription speedup   → skip:"abort:N", date-after, archive-mode:memory
├── Anti-bot defense       → browser TLS fingerprint
├── Cookie refresh         → cookies-update postprocessor
├── Structured stdout      → --Print (file paths + SHA256 + skip events)
├── Failure logging        → --write-unsupported + --error-file
└── URL dedup              → file-unique

Jyzrox application layer (retained)
├── Progressive import     → parses --Print output (no regex, no sidecar I/O)
├── Gallery metadata       → reads filtered JSON sidecar (metadata PP, first file only)
├── Semaphore concurrency  → cross-job scheduling (unchanged)
├── Credential management  → encrypted storage + gallery-dl cookie writeback
├── Dashboard / WebSocket  → simplified (no adaptive sleep display)
├── Subscription groups    → scheduling + date-after injection
├── HTML content detection → defense-in-depth (gallery-dl validate-html is first layer)
└── Credential warning     → 403 detection retained
```

---

## Module Changes from v2.3

### Unchanged Modules (no code changes)

| Module | Reason |
|--------|--------|
| M0A Config File Isolation | Per-job config files still needed |
| M0B Semaphore Redesign | Sorted set + heartbeat + Lua unchanged |
| M0C Disk Space Pre-flight | Disk check logic unchanged |
| M0D Download Loop Architecture | Task structure unchanged; individual tasks simplified |
| M1 SiteConfigService | Architecture unchanged; DownloadParams expanded |
| M2 Config Builder UI | Architecture unchanged; new fields added |
| M3 Subscription Groups | Scheduling logic unchanged; config injection added |
| M4 Live Dashboard | Architecture unchanged; adaptive display simplified |
| M5A Gallery-dl Venv | Architecture unchanged; psycopg added to venv |
| M5B Inactivity Timeout | Unchanged |
| M7 Docker Restart Recovery | Unchanged; archive corruption references removed |

---

## N1. PostgreSQL Archive with CASCADE Lifecycle

**Replaces**: SQLite file at `/data/archive/gallery-dl.db`, manual archive
cleanup in `_cleanup_archive_entries()`, broken archive key reconstruction.

### v2.3 Problems

1. **Two separate databases** — SQLite for archive, PostgreSQL for everything
   else. No transactional consistency, no foreign keys between them.
2. **Archive key format mismatch** — `library.py:1533` reconstructs archive
   keys as `"{source}{filename}"` (e.g., `"ehentai001.jpg"`), but gallery-dl
   stores entries in its own `archive_fmt` format (e.g., `"{gid}_{num}"` →
   `"2845123_4"`). The `DELETE FROM archive WHERE entry = ?` always misses →
   deleted galleries can never be re-downloaded.
3. **No lifecycle coupling** — deleting a gallery requires manually cleaning
   the archive. If cleanup fails (which it does, see #2), archive entries
   accumulate forever.

### v2.3 Code (to delete)

```
backend/plugins/builtin/gallery_dl/source.py:548-554
  → --download-archive /data/archive/gallery-dl.db

backend/routers/library.py:50-61
  → _cleanup_archive_entries() — sqlite3.connect() + DELETE

backend/routers/library.py:1531-1536
  → archive key reconstruction (broken format)

backend/routers/library.py:1581-1585
  → archive cleanup call in _hard_delete_galleries()

backend/core/config.py:55
  → data_archive_path: str = "/data/archive"

backend/worker/subscription.py:96-115
  → skip_archive logic (queries galleries table to decide)
```

### v3.0 Design — CASCADE-linked Archive Tables

gallery-dl's PostgreSQL archive uses a single-column table:

```sql
CREATE TABLE IF NOT EXISTS {table_name} (entry TEXT PRIMARY KEY)
```

gallery-dl only ever runs two queries:
- `SELECT 1 FROM {table} WHERE entry=? LIMIT 1` (check)
- `INSERT INTO {table} (entry) VALUES (?) ON CONFLICT DO NOTHING` (add)

**Key insight**: gallery-dl only touches the `entry` column. We can add extra
columns with DEFAULT values — gallery-dl will never know they exist.

#### Schema: Pre-create tables with extra columns

In `db/init.sql`, pre-create the archive tables **before** gallery-dl uses
them. gallery-dl's `CREATE TABLE IF NOT EXISTS` will no-op since the tables
already exist:

```sql
-- gallery-dl archive tables with Jyzrox extensions.
-- gallery-dl only reads/writes the 'entry' column.
-- Extra columns are managed by Jyzrox for lifecycle coupling.

CREATE TABLE IF NOT EXISTS exhentai (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    job_id      UUID,           -- download job that created this entry (for linking)
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pixiv (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    job_id      UUID,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS twitter (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    job_id      UUID,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Repeat for all sources in GDL_SITES...
-- Use a template or generate from _sites.py at migration time.
```

**Index for linking** (used during finalize):
```sql
CREATE INDEX IF NOT EXISTS idx_exhentai_unlinked
    ON exhentai (job_id) WHERE gallery_id IS NULL;
-- Repeat per table...
```

#### Scalability: Auto-upgrade tables created by gallery-dl

When gallery-dl encounters a new extractor not in `init.sql`, it auto-creates
a minimal table: `CREATE TABLE IF NOT EXISTS {name} (entry TEXT PRIMARY KEY)`.
This table lacks the `gallery_id` FK column. Two mitigation strategies:

**Strategy A — Worker startup check** (recommended):

```python
async def _ensure_archive_table_schema():
    """Ensure all gallery-dl archive tables have the gallery_id FK column.

    Called at worker startup. Finds tables that gallery-dl created without
    the Jyzrox extensions and ALTERs them to add gallery_id + created_at.
    """
    async with AsyncSessionLocal() as session:
        # Find tables that have 'entry' column but no 'gallery_id' column
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
            # Safety: only ALTER tables that look like archive tables (single 'entry' column)
            col_count = (await session.execute(text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_name = :t AND table_schema = 'public'"
            ), {"t": table})).scalar()
            if col_count != 1:
                continue  # not a gallery-dl archive table

            await session.execute(text(f'''
                ALTER TABLE "{table}"
                ADD COLUMN IF NOT EXISTS gallery_id BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()
            '''))
            logger.info("[archive] upgraded table '%s' with gallery_id FK", table)

        await session.commit()
```

Call in `worker/__init__.py startup()` before `recover_stale_jobs()`.

**Strategy B — `_link_archive_entries()` graceful degradation**:

If the table exists but has no `gallery_id` column, the UPDATE will fail.
The `except Exception` block already catches this. The gallery will work
normally but won't benefit from CASCADE cleanup (manual cleanup still needed
for unknown sources). This is acceptable for rare edge cases.

#### archive-format: Use gallery-dl's native defaults

**Do NOT override `archive-format`**. Use gallery-dl's per-extractor defaults:

| Source | gallery-dl default `archive_fmt` | Example entry |
|--------|----------------------------------|---------------|
| exhentai | `{gid}_{num}` | `2845123_4` |
| pixiv | `{id}{suffix}.{extension}` | `123456789.jpg` |
| twitter | `{tweet_id}_{retweet_id}_{num}` | `1834567890_0_1` |

Why: Custom `archive-format` risks breaking gallery-dl's internal dedup logic
(some extractors depend on specific key structure for incremental updates).
Using defaults means gallery-dl works exactly as designed.

The `archive-table: "{category}"` config routes each extractor to its own
table. gallery-dl's `{category}` resolves to the extractor name, which
matches our table names.

#### Lifecycle: gallery-dl INSERT → Jyzrox UPDATE → CASCADE DELETE

```
Step 1: gallery-dl downloads a file
  → INSERT INTO exhentai (entry) VALUES ('2845123_4') ON CONFLICT DO NOTHING
  → gallery_id = NULL (gallery-dl doesn't know about Jyzrox galleries)

Step 2: ProgressiveImporter.finalize() links entries to gallery
  → UPDATE exhentai SET gallery_id = 42
    WHERE gallery_id IS NULL
    AND entry LIKE '2845123_%'

Step 3: User deletes gallery 42
  → DELETE FROM galleries WHERE id = 42
  → CASCADE → all exhentai rows with gallery_id = 42 are deleted
  → Next download of same URL → gallery-dl finds no archive entry → re-downloads
```

#### Code: `_build_gallery_dl_config()` change

```python
config = {
    "extractor": {
        "base-directory": settings.data_gallery_path,
        "directory": [],
        # N1: PostgreSQL archive — tables pre-created in init.sql
        "archive": settings.gdl_archive_dsn,
        "archive-table": "{category}",
        # Do NOT set archive-format — use gallery-dl's per-extractor defaults
    },
}
```

#### Code: `ProgressiveImporter.finalize()` — link archive entries

After all files are imported, batch-UPDATE unlinked archive entries:

```python
async def _link_archive_entries(self, session) -> None:
    """Link gallery-dl archive entries to this gallery via gallery_id FK.

    gallery-dl INSERTs entries with gallery_id=NULL and job_id=NULL.
    Before download starts, we UPDATE all NULL job_id entries created during
    this job (matched by job_id which was set via a PostgreSQL trigger or
    by post-INSERT UPDATE).

    Two strategies:
    1. LIKE match by source_id prefix — works for gallery-level sources
       (E-Hentai, Pixiv, nhentai) where archive key starts with source_id.
    2. job_id match — works for ALL sources. gallery-dl doesn't write
       job_id, so we stamp it immediately after gallery-dl's INSERT via
       a post-download UPDATE keyed on job_id stored in the config.

    Strategy 2 avoids the time-window race condition where two concurrent
    downloads for the same source could claim each other's entries.
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

        # Strategy 1: LIKE match by source_id prefix (fast, covers most sources)
        if self.source_id:
            prefix = f"{self.source_id}%"
            result = await session.execute(
                text(f'UPDATE "{table}" SET gallery_id = :gid '
                     f'WHERE gallery_id IS NULL AND entry LIKE :prefix'),
                {"gid": self.gallery_id, "prefix": prefix},
            )
            if result.rowcount:
                logger.info("[progressive] linked %d archive entries to gallery %d (prefix match)",
                            result.rowcount, self.gallery_id)
                return

        # Strategy 2: job_id match (race-condition-safe, works for ALL sources)
        if self.db_job_id:
            result = await session.execute(
                text(f'UPDATE "{table}" SET gallery_id = :gid '
                     f'WHERE gallery_id IS NULL AND job_id = :jid'),
                {"gid": self.gallery_id, "jid": self.db_job_id},
            )
            if result.rowcount:
                logger.info("[progressive] linked %d archive entries to gallery %d (job_id match)",
                            result.rowcount, self.gallery_id)

    except Exception as exc:
        logger.warning("[progressive] failed to link archive entries: %s", exc)
```

**How `job_id` gets stamped**: gallery-dl's INSERT only writes the `entry`
column. We need a mechanism to stamp `job_id` on entries created during a
specific download job. Two approaches:

**Approach A — PostgreSQL session variable (recommended)**:

Before starting gallery-dl, set a session variable. A `BEFORE INSERT` trigger
on each archive table reads it:

```sql
-- Set before each download job starts (in download_job() before subprocess)
SET LOCAL jyzrox.current_job_id = '{job_id}';

-- Trigger on each archive table
CREATE OR REPLACE FUNCTION stamp_archive_job_id()
RETURNS TRIGGER AS $$
BEGIN
    NEW.job_id := nullif(current_setting('jyzrox.current_job_id', true), '');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_stamp_job_id
BEFORE INSERT ON exhentai
FOR EACH ROW EXECUTE FUNCTION stamp_archive_job_id();
-- Repeat per table...
```

**Problem**: gallery-dl uses its own `psycopg` connection (from the archive
DSN), not Jyzrox's SQLAlchemy session. `SET LOCAL` only affects the current
transaction/session, so a variable set in Jyzrox's session won't be visible
to gallery-dl's connection.

**Approach B — Post-download batch UPDATE by time window + job exclusion (practical)**:

Instead of a trigger, stamp `job_id` after gallery-dl finishes, using a
bounded time window AND excluding entries already claimed by other jobs:

```python
# In finalize(), Strategy 2:
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
```

The `job_id IS NULL` condition prevents races: once one job claims entries
(sets `job_id`), no other job can re-claim them. The time window
(`BETWEEN start AND end`) scopes to this job's lifetime. Combined with
Strategy 1 (prefix match) running first, Strategy 2 only fires for sources
where prefix match fails (Twitter, etc.), minimizing the race window.

Call in `finalize()` inside the existing session:

```python
def __init__(self, db_job_id, user_id, *, page_num_from_filename=False):
    # ... existing init ...
    self._job_started_at = datetime.now(UTC)

async def finalize(self, dest_dir, *, partial=False):
    # ... existing task drain and page count ...
    async with AsyncSessionLocal() as session:
        # ... existing gallery update ...
        await self._link_archive_entries(session)
        await session.commit()
```

#### Code: Delete `_cleanup_archive_entries()` entirely

The entire function in `library.py:50-61` is deleted. The archive key
reconstruction at `library.py:1531-1536` is deleted. The cleanup call at
`library.py:1581-1585` is deleted.

When `_hard_delete_galleries()` calls `DELETE FROM galleries WHERE id = ?`,
PostgreSQL CASCADE automatically deletes all linked archive entries. No
manual cleanup needed.

#### Code: Simplify subscription `skip_archive` logic

`subscription.py:96-115` currently queries the `galleries` table to decide
whether to use the archive. This can be simplified:

```python
# v3.0: archive is always enabled. gallery-dl's archive table (in PG) is
# automatically cleaned via CASCADE when galleries are deleted. No need
# for skip_archive logic — if archive entries exist, gallery-dl skips them;
# if they were CASCADE-deleted, gallery-dl re-downloads.
options = None  # archive always active
```

The `skip_archive` option is removed entirely. Archive lifecycle is managed
by CASCADE, not by application logic.

#### Config changes

**`core/config.py`**: Delete `data_archive_path`. Add DSN helper:

```python
@property
def gdl_archive_dsn(self) -> str:
    """Build a psycopg-compatible DSN from the asyncpg database_url."""
    return self.database_url.replace("+asyncpg", "")
```

**`gallery_dl_venv.py`**: Install `psycopg[binary]` alongside gallery-dl:

```python
pip_cmd = [str(new_dir / "bin/pip"), "install", "gallery-dl", "psycopg[binary]"]
```

#### What this eliminates

| Deleted component | Reason |
|-------------------|--------|
| `_cleanup_archive_entries()` function | CASCADE handles cleanup |
| Archive key reconstruction (`library.py:1531-1536`) | No manual cleanup needed |
| Archive cleanup call (`library.py:1581-1585`) | No manual cleanup needed |
| `skip_archive` logic (`subscription.py:96-115`) | Archive always active, lifecycle via CASCADE |
| `data_archive_path` config | No SQLite file |
| `/data/archive/` directory | No SQLite file |
| `sqlite3` import in `library.py` | No SQLite |

#### What this fixes

| v2.3 Bug | v3.0 Fix |
|----------|----------|
| Archive key format mismatch → deleted galleries can never be re-downloaded | CASCADE DELETE removes exact entries gallery-dl wrote |
| SQLite concurrent writer contention | PostgreSQL MVCC |
| Two separate databases with no transactional consistency | Single PostgreSQL instance, FK constraints |
| Manual cleanup can silently fail | CASCADE is atomic and guaranteed |

---

## N2. Subscription Optimization (abort:N + date-after)

**Replaces**: Full gallery traversal on every subscription check.

### v2.3 Behavior

Every subscription check runs gallery-dl with `skip: true` (default). gallery-dl
iterates ALL items in an artist's gallery, checking each against the archive.
For a 500-item artist with 3 new items: 500 API requests, 497 skips.

### v3.0 Design

Two config parameters injected per-job based on job type:

**In `_build_gallery_dl_config()`**, add a `job_context` parameter:

```python
async def _build_gallery_dl_config(
    credentials: dict,
    config_id: str | None = None,
    job_context: str = "manual",        # "manual" | "subscription"
    last_completed_at: datetime | None = None,
) -> Path:
```

**Config injection logic**:

```python
# N2: Subscription optimization
if job_context == "subscription":
    # abort:10 — stop after 10 consecutive already-downloaded items
    config["extractor"]["skip"] = "abort:10"

    # date-after — only fetch items newer than last successful check
    if last_completed_at:
        # Subtract 1 day buffer for timezone edge cases
        cutoff = last_completed_at - timedelta(days=1)
        config["extractor"]["date-after"] = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
```

**Caller change** — `_enqueue_for_subscription()` in `worker/subscription.py`:

Pass `job_context="subscription"` and `last_completed_at=group.last_completed_at`
through the options dict to `download_job()`, which forwards to
`_build_gallery_dl_config()`.

```python
opts = {
    "job_context": "subscription",
    "last_completed_at": group.last_completed_at.isoformat() if group.last_completed_at else None,
}
```

**`download_job()` change** — extract and forward:

```python
job_context = (options or {}).get("job_context", "manual")
last_completed_at_str = (options or {}).get("last_completed_at")
last_completed_at = datetime.fromisoformat(last_completed_at_str) if last_completed_at_str else None
```

---

## N3. gallery-dl Native Rate Limiting (Adaptive Engine Offload)

**Replaces**: Lua script 429/503/timeout branches, sleep_multiplier,
http_timeout_add, adaptive sleep overlay in config builder.

### v2.3 Code (to delete/simplify)

```
core/adaptive.py:
  → Lua ADAPTIVE_UPDATE_SCRIPT: 429, 503, timeout, success branches  [DELETE]
  → AdaptiveState.sleep_multiplier field                               [DELETE]
  → AdaptiveState.http_timeout_add field                               [DELETE]
  → consecutive_success tracking + recovery thresholds                 [DELETE]
  → persist_dirty() — simplify to only handle credential_warning       [SIMPLIFY]
  → load_all_from_db() — simplify                                      [SIMPLIFY]
  → get_states_batch() — simplify (dashboard only needs credential_warning) [SIMPLIFY]

source.py:122-151
  → Adaptive sleep multiplier overlay in _build_gallery_dl_config()    [DELETE]

source.py:569-575
  → Adaptive http_timeout calculation                                  [DELETE]

source.py:272-289 (_read_stderr)
  → parse_adaptive_signal() call for 429/503/timeout                   [DELETE]
  → Keep: debug logging of stderr lines                                [KEEP]
  → Keep: 403 detection for credential warning                         [KEEP]
```

### v3.0 Design

**`_build_gallery_dl_config()` — inject native rate limiting**:

```python
# N3: gallery-dl native rate limiting (replaces adaptive engine)
config["extractor"].update({
    "sleep-retries": "exp=5",       # exponential backoff on retry, max 5 min
    "sleep-429": "exp:2=120",       # 429-specific: base 2s, exponential, max 120s
})

# Per-extractor overrides for sites with known aggressive rate limiting
config["extractor"]["ehentai"] = {
    **config["extractor"].get("ehentai", {}),
    "sleep-retries": "exp=10",      # EH is slow, longer backoff
    "sleep-429": "exp:5=300",       # EH 429s are serious, 5s base, 5min max
}
```

**Simplified `AdaptiveState`** (`core/adaptive.py`):

```python
@dataclass
class AdaptiveState:
    credential_warning: bool = False
    last_signal: str | None = None
    last_signal_at: str | None = None
```

3 fields instead of 6. No sleep_multiplier, no http_timeout_add, no
consecutive_success.

**Simplified `record_signal()`** — remove `count` parameter:

```python
async def record_signal(self, source_id: str, signal: AdaptiveSignal) -> AdaptiveState:
    from core.redis_client import get_redis
    r = get_redis()
    key = f"adaptive:{source_id}"
    now_str = datetime.now(UTC).isoformat()
    raw = await r.eval(self._SIGNAL_LUA, 1, key, source_id, signal.value, str(_ADAPTIVE_TTL), now_str)
    return self._parse_raw(raw)
```

**Simplified `persist_dirty()`**:

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
                logger.exception("[adaptive] persist failed for %s, re-queued", source_id)
        await session.commit()
    return persisted
```

**Simplified Lua script** — only handles credential signals:

```lua
local state = cjson.decode(redis.call('GET', KEYS[1]) or '{}')
local signal = ARGV[1]
if signal == '403' or signal == 'html_response' then
    state.credential_warning = true
end
state.last_signal = signal
state.last_signal_at = ARGV[2]
redis.call('SET', KEYS[1], cjson.encode(state))
redis.call('EXPIRE', KEYS[1], 86400)
```

**Simplified `_read_stderr()`** (`source.py`):

```python
async def _read_stderr(
    proc: asyncio.subprocess.Process,
    state: _DownloadState,
) -> None:
    """Accumulate stderr lines. Detect 403 for credential warnings only."""
    assert proc.stderr is not None

    async for raw_line in proc.stderr:
        line = raw_line.decode("utf-8", errors="replace").rstrip()
        if line and len(state.stderr_lines) < _MAX_STDERR_LINES:
            state.stderr_lines.append(line)
        # N3: only detect 403 for credential warning (rate limiting offloaded)
        if state.source_id and _RE_403.search(line):
            from core.adaptive import AdaptiveSignal, adaptive_engine
            try:
                await adaptive_engine.record_signal(state.source_id, AdaptiveSignal.HTTP_403)
            except Exception:
                pass
```

**Delete `parse_adaptive_signal()`** entirely. Replace with inline 403 check.

**`_build_gallery_dl_config()` adaptive overlay — DELETE**:

Remove the entire block at source.py:122-151 that reads adaptive state from
Redis and multiplies sleep-request values. gallery-dl handles its own backoff
now.

**`source.py` download() — DELETE adaptive timeout**:

Remove source.py:569-575. gallery-dl uses its own retry/timeout behavior.
The `--http-timeout` flag is still set from `DownloadParams.http_timeout`
(static per-site config), but no longer dynamically adjusted.

---

## N4. Content Integrity Offload

**Replaces**: Empty file detection in `_validate_download_content()`.

### v2.3 Code (to simplify)

```
source.py:390-406 (_validate_download_content)
  → size == 0 check (empty file)                                      [DELETE]
  → size < 100KB HTML check                                           [KEEP]
```

### v3.0 Design

**`_build_gallery_dl_config()`**:

```python
# N4: content integrity offload
config["extractor"].update({
    "filesize-min": "1k",               # reject empty/tiny files
})
config["downloader"] = {
    "adjust-extensions": True,          # fix mismatched extensions
}
```

**Simplified `_validate_download_content()`**:

```python
def _validate_download_content(file_path: Path) -> str | None:
    """Check for HTML masquerading as media, plus post-download empty file safety net.

    gallery-dl's filesize-min checks Content-Length header at download time, but:
    - Chunked transfer has no Content-Length → bypasses check
    - Server may report incorrect Content-Length
    - Write failure may produce 0-byte file

    Keep a lightweight size check as defense-in-depth.
    """
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

Empty file check **retained** as a safety net (gallery-dl's `filesize-min`
only checks HTTP `Content-Length` header, not actual file size). The
`EMPTY_FILE` adaptive signal is removed — empty files are simply skipped
without recording a signal (no rate-limit adjustment needed for disk I/O
failures).

---

## N5. Import Pipeline Acceleration (hash + mtime Postprocessors)

**Replaces**: SHA256 computation during import, hardcoded `datetime.now(UTC)`
for image timestamps.

### v2.3 Code (to modify)

```
progressive.py:280
  → sha256 = await asyncio.to_thread(_sha256, file_path)              [MODIFY]

progressive.py:298
  → added_at=datetime.now(UTC)                                        [MODIFY]
```

### v3.0 Design

**`_build_gallery_dl_config()` — postprocessors**:

```python
# N5: hash PP computes SHA256 → available via --Print {sha256} (N11)
#     mtime PP sets file mtime to original upload date
config["postprocessors"] = [
    {
        "name": "hash",
        "hash": "sha256",
    },
    {
        "name": "mtime",
    },
]
```

- **hash PP**: Computes SHA256 and stores it in gallery-dl's metadata dict.
  N11's `--Print "after:...\t{sha256}"` streams the hash to stdout. No sidecar
  file reading needed in `progressive.py`. The hash PP also creates `.sha256`
  sidecar files on disk, but these are ignored (cleaned up by `shutil.rmtree`
  in `finalize()`).
- **mtime PP**: Sets file `os.utime()` to the metadata `date` field (original
  upload date). `progressive.py` reads `file_path.stat().st_mtime` for
  `added_at`.

**`progressive.py` `_import_single()` change**:

```python
async def _import_single(self, file_path: Path, page_num: int, sha256: str | None = None) -> None:
    if not file_path.exists():
        return

    if file_path.suffix.lower() not in _VIDEO_EXTS:
        if not _validate_image_magic(file_path):
            logger.warning("[progressive] invalid magic bytes, skipping: %s", file_path.name)
            return

    try:
        # N5+N11: SHA256 from --Print stdout (hash PP computed, --Print streamed)
        # Fallback: self-compute (e.g., manual import without gallery-dl)
        final_sha256 = sha256 or await asyncio.to_thread(_sha256, file_path)

        # N5: use file mtime as added_at (mtime PP sets original upload date)
        try:
            mtime = file_path.stat().st_mtime
            added_at = datetime.fromtimestamp(mtime, tz=UTC)
            if added_at.year < 2000 or added_at > datetime.now(UTC):
                added_at = datetime.now(UTC)
        except (OSError, ValueError, OverflowError):
            added_at = datetime.now(UTC)

        # ... rest of import (unchanged) ...
        img_stmt = (
            pg_insert(Image)
            .values(
                gallery_id=self.gallery_id,
                page_num=page_num,
                filename=file_path.name,
                blob_sha256=final_sha256,
                added_at=added_at,
            )
            .on_conflict_do_nothing()
            .returning(Image.id)
        )
```

**No sidecar reading**: SHA256 arrives via `on_file(file_path, sha256)` callback
(from N11's `--Print` stdout parsing). Sidecar `.sha256` files still created by
hash PP but ignored and cleaned up with `shutil.rmtree` in `finalize()`.

---

## N6. Pixiv Ugoira Conversion

**Replaces**: Nothing (new capability). Pixiv animated images currently stored
as raw ZIP frames.

### v3.0 Design

**`_build_gallery_dl_config()`** — Pixiv-specific postprocessor:

```python
# N6: Pixiv ugoira → MP4 conversion
# Only add for Pixiv extractor to avoid affecting other sources
if any(src == "pixiv" for src in credentials):
    config["extractor"].setdefault("pixiv", {})["ugoira"] = True
    # Append ugoira PP to postprocessors list
    config.setdefault("postprocessors", []).append({
        "name": "ugoira",
        "extension": "mp4",
        "ffmpeg-args": ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-an"],
        "ffmpeg-twopass": False,
        "keep-files": False,        # delete ZIP frames after conversion
    })
```

**No other changes needed**: `_MEDIA_EXTS` in `worker/constants.py` already
includes `.mp4`. `VideoPlayer.tsx` in the Reader already handles MP4 playback.
`thumbnail.py` already generates thumbnails from video via ffmpeg.

**Dockerfile**: Verify `ffmpeg` is installed in worker image (required for
existing thumbnail generation — should already be present).

---

## N7. Anti-Bot Defense (browser + proxy)

**Replaces**: Nothing (new capability). Reduces 403/429 frequency, complementing
N3's native rate limiting.

### v3.0 Design

**Expand `DownloadParams`** (`core/site_config.py`):

```python
@dataclass
class DownloadParams:
    retries: int = 4
    http_timeout: int = 30
    sleep_request: float | tuple[float, float] | None = None
    concurrency: int = 2
    inactivity_timeout: int = 300
    # N7: new fields
    browser_profile: str | None = None     # "chrome" | "firefox" | None
    proxy_url: str | None = None           # "socks5://..." | "http://..." | None
    rate_limit: str | None = None          # "2M" | "500k" | None
```

**`_build_gallery_dl_config()` injection**:

```python
for site_cfg in GDL_SITES:
    params = all_params.get(site_cfg.source_id)
    if not params:
        continue
    ext = site_cfg.extractor or site_cfg.source_id
    entry = config["extractor"].setdefault(ext, {})

    # Existing: sleep-request injection (unchanged)
    if params.sleep_request is not None:
        entry["sleep-request"] = (
            list(params.sleep_request) if isinstance(params.sleep_request, tuple)
            else params.sleep_request
        )

    # N7: browser TLS fingerprint
    if params.browser_profile:
        entry["browser"] = params.browser_profile

    # N7: per-site proxy
    if params.proxy_url:
        entry["proxy"] = params.proxy_url

# N7: global rate limit
for site_cfg in GDL_SITES:
    params = all_params.get(site_cfg.source_id)
    if params and params.rate_limit:
        config.setdefault("downloader", {})["rate"] = params.rate_limit
```

**SiteConfigService validation** — add to `update()`:

```python
if "browser_profile" in dl:
    bp = dl["browser_profile"]
    if bp is not None and bp not in ("chrome", "firefox"):
        raise ValueError(f"browser_profile must be 'chrome', 'firefox', or null")
```

**Config Builder UI (M2)**: Add three new fields to the per-site editor:
- Browser Profile: dropdown (None / Chrome / Firefox)
- Proxy URL: text input with URL validation
- Rate Limit: text input (e.g., "2M", "500k")

---

## N8. Cookie Session Refresh

**Replaces**: Manual credential re-entry when cookies expire.

### Important: Format Difference

gallery-dl's `cookies-update` writes **Netscape cookies.txt format** (via
`util.cookiestxt_store()`), not JSON. Jyzrox stores cookies as JSON dicts in
the `credentials` table. The writeback path must convert between formats.

### v3.0 Design

**`_build_gallery_dl_config()`** — per-source cookies-update:

```python
# N8: cookie session refresh
# Only for cookie-based auth sources
for src, cred_val in credentials.items():
    cfg = get_site_config(src)
    if cfg.credential_type != "cookies":
        continue
    ext = cfg.extractor or cfg.source_id
    # gallery-dl writes Netscape cookies.txt format to this path
    cookie_update_path = f"/tmp/gdl-cookies-{config_id}-{src}.txt"
    config["extractor"].setdefault(ext, {})["cookies-update"] = cookie_update_path
```

**`download_job()` finally block** — read back and convert cookies:

```python
import http.cookiejar

def _cookiestxt_to_dict(path: Path) -> dict[str, str]:
    """Parse Netscape cookies.txt into a simple {name: value} dict."""
    jar = http.cookiejar.MozillaCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=True)
    return {c.name: c.value for c in jar}

# N8: cookie writeback (Netscape cookies.txt → JSON dict → encrypted DB)
if db_job_id and result.status in ("done", "partial"):
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

---

## N9. Failure Logging (write-unsupported)

**Replaces**: Limited stderr capture (first 500 chars of error).

### v3.0 Design

**`source.py` download() — add CLI flag**:

```python
# N9: log unsupported/failed URLs
unsupported_path = f"/tmp/gdl-unsupported-{config_id}.txt"
cmd += ["--write-unsupported", unsupported_path]
```

**After process completes** (in `_run_download` result section):

```python
# N9: capture unsupported URLs
unsupported_file = Path(f"/tmp/gdl-unsupported-{config_id}.txt")
unsupported_urls: list[str] = []
if unsupported_file.exists():
    try:
        unsupported_urls = [
            line.strip() for line in unsupported_file.read_text().splitlines()
            if line.strip()
        ]
    except OSError:
        pass
    finally:
        unsupported_file.unlink(missing_ok=True)

# Include in DownloadResult
return DownloadResult(
    status=...,
    downloaded=state.downloaded,
    total=state.downloaded,
    unsupported_urls=unsupported_urls,  # new field
    ...
)
```

**`download_job()` — include in progress**:

```python
if result.unsupported_urls:
    final_progress["unsupported_urls"] = result.unsupported_urls
```

---

## N10. Additional gallery-dl Native Features

Four low-cost features identified during comprehensive gallery-dl config audit.

### N10a. `archive-mode: "memory"` for Subscription Jobs

Subscription checks trigger many archive lookups (most entries already exist)
with few actual downloads. `archive-mode: "memory"` batches all archive writes
to the end of the gallery-dl process, reducing per-file PostgreSQL round trips.

**Config injection** (in `_build_gallery_dl_config()`):

```python
# N10a: batch archive writes for subscription jobs
if job_context == "subscription":
    config["extractor"]["archive-mode"] = "memory"
```

Manual downloads keep the default `"file"` mode (safer for large galleries
where mid-download interruption would lose progress).

**Trade-off**: If gallery-dl is killed mid-subscription-check, in-memory
archive IDs are lost → next check re-downloads those files. Acceptable because
`store_blob()` SHA256 dedup prevents actual duplicate storage, and subscription
jobs are typically short.

### N10b. `file-unique: true`

Prevents gallery-dl from downloading the same URL twice within a single run.
Common on Twitter (retweets of the same media) and Reddit (cross-posts).

**Config injection** (global, all job types):

```python
# N10b: deduplicate URLs within a single download run
config["extractor"]["file-unique"] = True
```

Zero downside. One-liner.

### N10c. gallery-dl's Built-in `validate-html` (Documentation Note)

**Discovery**: gallery-dl's HTTP downloader has `validate-html: true` by
default. It rejects responses whose body starts with `<!DOCTYPE` or `<html`.

This means Jyzrox's `_validate_download_content()` HTML check is a **second
layer of defense**. gallery-dl catches most HTML responses during download;
Jyzrox catches edge cases (e.g., HTML without standard doctype, Cloudflare
challenge pages with `cf-browser-verification`).

**No code change needed.** Document this in the Retained Code Summary as
defense-in-depth rationale.

### N10d. `metadata` Postprocessor (Replace `--write-metadata --write-tags`)

v2.3 uses CLI flags `--write-metadata --write-tags` which write **all**
gallery-dl metadata fields to JSON sidecars. This produces large files
(10-50KB per image for sites with rich metadata) that Jyzrox must parse and
mostly ignore.

The `metadata` postprocessor supports `include`/`exclude` field filtering:

```python
# N10d: write only fields Jyzrox needs (replaces --write-metadata --write-tags)
config["postprocessors"].append({
    "name": "metadata",
    "mode": "json",
    "extension": "json",
    "include": [
        # Gallery-level fields used by _metadata.py parse_gallery_dl_import()
        "category", "subcategory",
        "gallery_id", "id", "gid",
        "title", "title_en", "title_jpn", "title_original",
        "tags", "tag_string",
        "date", "posted",
        "uploader", "username", "user",
        "author",
        "lang", "language",
        "gallery_category",
        "rating",
        "description", "content",
        # Per-image fields used by progressive import
        "filename", "extension", "num",
    ],
})
```

**What this replaces**: Remove `--write-metadata` and `--write-tags` from the
`cmd` list in `download()`. The postprocessor produces the same JSON sidecars
but with only the fields Jyzrox actually reads.

**Benefits**:
- Sidecar files shrink from ~10-50KB to ~1-3KB
- Less disk I/O during import (smaller files to parse)
- No code change needed in `_metadata.py` — it reads the same field names

---

## N11. Structured Stdout via `--Print` (Replace Regex Parsing)

**Replaces**: `_FILE_PATH_EXTRACT_RE` regex parsing in `_read_stdout()`,
`.sha256` sidecar file reading in `progressive.py`, manual skip counting.

### v2.3 Problems

1. `_read_stdout()` uses `re.compile(r"(/data/.+\.\w+)")` to detect downloaded
   file paths from gallery-dl's stdout. This is fragile — any gallery-dl version
   change to output format breaks it silently.
2. Skip counting relies on detecting `# ` prefix lines, another format assumption.
3. SHA256 is computed by hash PP → written to `.sha256` sidecar → read back by
   `progressive.py`. This is 2 extra disk I/O ops per file.

### v2.3 Code (to delete)

```
source.py:34-36
  → _FILE_PATH_RE, _FILE_PATH_EXTRACT_RE, _IMAGE_EXT_RE regex patterns    [DELETE]

source.py:205-270 (_read_stdout)
  → Regex-based line parsing, pending_file state machine                   [REWRITE]

source.py:536-546 (download cmd)
  → --write-metadata, --write-tags CLI flags                               [DELETE]

progressive.py:267-273
  → .sha256 sidecar reading logic                                          [DELETE]
```

### v3.0 Design

gallery-dl's `--Print` (capital P) downloads files AND outputs a formatted
string per event. The `"after"` event fires after all postprocessors (including
hash PP), so `{sha256}` is available in the format string.

**Critical: hash PP must appear before any other PP in the postprocessors list.**
gallery-dl executes PPs in config order. `--Print "after:..."` fires after ALL
PPs complete, so ordering doesn't affect `--Print`. But if a future PP depends
on the hash (e.g., metadata PP writing SHA256 to JSON), it needs hash PP to run
first. `_build_gallery_dl_config()` enforces hash PP as the first entry:

```python
config["postprocessors"] = [
    {"name": "hash", "hash": "sha256"},   # MUST be first — others may depend on {sha256}
    {"name": "mtime"},
    {"name": "metadata", ...},
]
# Ugoira PP appended later (only for Pixiv) — order doesn't matter for video conversion
```

**CLI flags added to `cmd` in `download()`**:

```python
# N11: structured stdout — replaces regex parsing
cmd += [
    "--Print", "after:JYZROX_FILE\t{_path}\t{sha256}",
    "--Print", "skip:JYZROX_SKIP",
]
```

stdout output becomes deterministic:
```
JYZROX_FILE\t/data/gallery/12345/001.jpg\tabc123def456...
JYZROX_FILE\t/data/gallery/12345/002.jpg\t789012ghi345...
JYZROX_SKIP
JYZROX_SKIP
```

**CLI flags removed from `cmd`** (replaced by N10d metadata PP + N11):
```python
# DELETE these lines:
"--write-metadata",
"--write-tags",
```

**Rewritten `_read_stdout()`**:

```python
_PRINT_FILE_PREFIX = "JYZROX_FILE\t"
_PRINT_SKIP_PREFIX = "JYZROX_SKIP"

async def _read_stdout(
    proc: asyncio.subprocess.Process,
    state: _DownloadState,
    on_file: Callable[[Path, str], Awaitable[None]] | None,
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
            # "JYZROX_FILE\t/path/to/file.jpg\tsha256hex"
            parts = line[len(_PRINT_FILE_PREFIX):].split("\t", 1)
            file_path = Path(parts[0])
            sha256 = parts[1] if len(parts) > 1 else None

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

        # Progress reporting (every N files or T seconds)
        total_seen = state.downloaded + state.skipped_count
        if total_seen > 0 and (total_seen % _PROGRESS_EVERY_N == 0 or (now - state.last_progress_update) >= _PROGRESS_EVERY_S):
            state.last_progress_update = now
            if on_progress:
                try:
                    await on_progress(total_seen, 0)
                except Exception:
                    pass
```

**Key changes**:
- No regex. Just `str.startswith()` + `str.split()`.
- `sha256` is passed directly to `_on_file_with_validation()` → forwarded to
  `on_file()` callback → no sidecar reading in `progressive.py`.
- No `pending_file` state machine. `--Print "after:..."` fires once per completed
  file, so there's no "current file is the NEXT line's context" ambiguity.
- Skip counting is explicit (`JYZROX_SKIP` prefix), not guessed from `# ` prefix.

**Updated `_on_file_with_validation()` signature**:

```python
async def _on_file_with_validation(
    file_path: Path,
    sha256: str | None,
    state: _DownloadState,
    proc: asyncio.subprocess.Process,
    inner_on_file: Callable[[Path, str | None], Awaitable[None]] | None,
) -> None:
```

The `sha256` parameter passes through to `inner_on_file` (the progressive
importer's `on_file` callback).

**Updated `on_file` callback in `download_job()`**:

```python
async def on_file(file_path: Path, sha256: str | None = None):
    # ... existing gallery creation logic (unchanged) ...
    await importer.import_file(file_path, sha256=sha256)
```

**Updated `progressive.py` `_import_single()`**:

```python
async def _import_single(self, file_path: Path, page_num: int, sha256: str | None = None) -> None:
    # ...
    # N11: SHA256 from --Print stdout (hash PP computed it, --Print streamed it)
    if sha256:
        final_sha256 = sha256
    else:
        # Fallback: compute ourselves (e.g., manual import without gallery-dl)
        final_sha256 = await asyncio.to_thread(_sha256, file_path)
```

No `.sha256` sidecar reading. No sidecar file created (hash PP still runs
to compute the hash, but its sidecar output is ignored — cleaned up with
`shutil.rmtree` in `finalize()`).

**What this eliminates**:
- `_FILE_PATH_RE`, `_FILE_PATH_EXTRACT_RE`, `_IMAGE_EXT_RE` regex constants
- `pending_file` state machine in `_read_stdout()`
- `.sha256` sidecar reading in `progressive.py`
- `# ` prefix-based skip detection
- `_flush_success_signals()` (already deleted by N3)

---

## N12. Error File (Complement to N9)

**Replaces**: Nothing (new capability). `--write-unsupported` captures URLs
gallery-dl doesn't recognize. `--error-file` captures URLs gallery-dl
recognized but failed to download.

### v3.0 Design

**CLI flag** (in `download()` cmd):

```python
# N12: capture download errors (complements N9 write-unsupported)
error_path = f"/tmp/gdl-errors-{config_id}.txt"
cmd += ["--error-file", error_path]
```

**After process completes** (in the same block as N9):

```python
# N12: capture error URLs
error_file = Path(f"/tmp/gdl-errors-{config_id}.txt")
error_urls: list[str] = []
if error_file.exists():
    try:
        error_urls = [l.strip() for l in error_file.read_text().splitlines() if l.strip()]
    except OSError:
        pass
    finally:
        error_file.unlink(missing_ok=True)
```

**Include in `DownloadResult`**:

```python
class DownloadResult(BaseModel):
    status: Literal["done", "cancelled", "failed", "partial"]
    downloaded: int
    total: int
    failed_pages: list[int] = []
    error: str | None = None
    unsupported_urls: list[str] = []  # N9
    error_urls: list[str] = []        # N12
```

---

## Future Work (Not in v3.0)

| Feature | Reason for Deferral |
|---------|--------------------|
| `tags-blacklist` / `tags-whitelist` | User-facing feature requiring Subscription Group UI + model changes. Independent feature, not a config offload. |
| Per-site `metadata: true` (exhentai, pixiv, twitter) | Enriches gallery data but requires `_metadata.py` parsing changes per-source. Incremental improvement, do per-source as needed. |
| `cookies-select: "rotate"` | Requires multi-account credential storage. No current demand. |
| `file-filter` / `post-filter` | Python expressions too complex for general users. `tags-blacklist` covers 90% of use cases. |
| `child-filter` | Multi-chapter manga filtering. Too niche for v3.0 scope. |

---

## DownloadParams v3.0 Full Schema

Complete expanded `DownloadParams` with all v3.0 fields:

```python
@dataclass
class DownloadParams:
    # v2.3 existing
    retries: int = 4
    http_timeout: int = 30
    sleep_request: float | tuple[float, float] | None = None
    concurrency: int = 2
    inactivity_timeout: int = 300

    # v3.0 new
    browser_profile: str | None = None     # N7: "chrome" | "firefox" | None
    proxy_url: str | None = None           # N7: per-site proxy
    rate_limit: str | None = None          # N7: bandwidth cap ("2M", "500k")
```

---

## GdlSiteConfig v3.0 Additions

No new fields needed on `GdlSiteConfig`. Archive format uses gallery-dl's
per-extractor defaults (not overridden by Jyzrox). The `archive_format` field
from the earlier draft is **removed** — overriding archive format risks
breaking gallery-dl's internal dedup logic.

---

## Deleted Code Summary

| File | Lines/Block | What | Why |
|------|-------------|------|-----|
| `core/adaptive.py` | Lua script 429/503/timeout/success branches | Rate-limit state machine | N3: gallery-dl handles natively |
| `core/adaptive.py` | `AdaptiveState.sleep_multiplier` | Sleep adjustment tracking | N3: offloaded |
| `core/adaptive.py` | `AdaptiveState.http_timeout_add` | Timeout adjustment tracking | N3: offloaded |
| `core/adaptive.py` | `AdaptiveState.consecutive_success` | Recovery threshold tracking | N3: offloaded |
| `core/adaptive.py` | Success recovery logic (every 20th/100th) | Gradual speed-up | N3: offloaded |
| `core/adaptive.py` | `AdaptiveSignal.HTTP_429` | 429 signal enum | N3: offloaded |
| `core/adaptive.py` | `AdaptiveSignal.HTTP_503` | 503 signal enum | N3: offloaded |
| `core/adaptive.py` | `AdaptiveSignal.TIMEOUT` | Timeout signal enum | N3: offloaded |
| `core/adaptive.py` | `AdaptiveSignal.CONNECTION_ERROR` | Connection error signal | N3: offloaded |
| `core/adaptive.py` | `AdaptiveSignal.SUCCESS` | Success signal enum | N3: offloaded |
| `core/adaptive.py` | `AdaptiveSignal.EMPTY_FILE` | Empty file signal | N4: gallery-dl filesize-min |
| `core/adaptive.py` | `parse_adaptive_signal()` | Stderr regex parsing | N3: offloaded |
| `core/adaptive.py` | `_RE_429`, `_RE_503`, `_RE_TIMEOUT`, `_RE_CONN` | Regex patterns | N3: offloaded |
| `source.py:122-151` | Adaptive sleep multiplier overlay | Config mutation per-job | N3: offloaded |
| `source.py:569-575` | Adaptive http_timeout calculation | CLI flag mutation | N3: offloaded |
| `source.py:284-288` | `parse_adaptive_signal()` call in `_read_stderr` | Signal collection | N3: simplified to 403-only |
| `source.py:479-481` | `AdaptiveSignal.EMPTY_FILE` recording | Empty file signal | N4: empty check retained as safety net, signal removed |
| `source.py:34-36` | `_FILE_PATH_RE`, `_FILE_PATH_EXTRACT_RE`, `_IMAGE_EXT_RE` | Regex patterns for stdout parsing | N11: `--Print` structured output |
| `source.py:205-270` | `_read_stdout()` regex + pending_file state machine | Fragile stdout parsing | N11: rewritten as prefix matching |
| `source.py:536-546` | `--write-metadata`, `--write-tags` CLI flags | Replaced by N10d metadata PP | N10d + N11 |
| `source.py:548-554` | `--download-archive` CLI flag | SQLite archive path | N1: PostgreSQL config |
| `library.py:50-61` | `_cleanup_archive_entries()` function | SQLite archive cleanup | N1: CASCADE handles cleanup |
| `library.py:1531-1536` | Archive key reconstruction | Broken format mismatch | N1: CASCADE handles cleanup |
| `library.py:1581-1585` | Archive cleanup call in `_hard_delete_galleries()` | Manual cleanup | N1: CASCADE handles cleanup |
| `subscription.py:96-115` | `skip_archive` logic | Redundant with CASCADE lifecycle | N1: archive always active |
| `core/config.py:55` | `data_archive_path` setting | Archive directory config | N1: no longer needed |
| `worker/__init__.py` | `load_all_from_db()` adaptive state loading | Startup state restoration | N3: simplified |
| `worker/__init__.py` | `adaptive_persist_job` cron complexity | 5-min DB flush | N3: simplified |

**Estimated net code reduction**: ~300 lines deleted, ~100 lines added = **~200 lines net reduction**.

---

## Retained Code Summary

| Component | Why Retained |
|-----------|-------------|
| `_on_file_with_validation()` HTML detection | Defense-in-depth: gallery-dl's `validate-html` (N10c) catches standard HTML responses during download, but misses edge cases like Cloudflare `cf-browser-verification` pages and non-standard HTML without doctype. Jyzrox's post-download check is the second layer. |
| `_on_file_with_validation()` HTML count → kill at 5 | Application-level circuit breaker |
| `ADAPTIVE_BLOCKED` event emission | Frontend credential warning notification |
| `AdaptiveState.credential_warning` | Dashboard display |
| `_read_stderr()` 403 detection | Credential expiration signal |
| `_read_stdout()` file path parsing | Progressive import callback |
| Semaphore (M0B) | Cross-job concurrency control |
| Inactivity watchdog (M5B) | Process hang detection |
| Heartbeat loop | Semaphore liveness |
| Pause/cancel watcher | User interaction |

---

## New Dependencies

| Package | Where | Purpose |
|---------|-------|---------|
| `psycopg[binary]` | gallery-dl venv (M5A) | PostgreSQL archive backend |

No new Python packages in the Jyzrox backend itself.

---

## _build_gallery_dl_config() v3.0 — Complete Pseudocode

```python
async def _build_gallery_dl_config(
    credentials: dict,
    config_id: str | None = None,
    job_context: str = "manual",
    last_completed_at: datetime | None = None,
) -> Path:
    config = {
        "extractor": {
            "base-directory": settings.data_gallery_path,
            "directory": [],
            # N1: PostgreSQL archive (tables pre-created in init.sql with CASCADE FK)
            "archive": settings.gdl_archive_dsn,
            "archive-table": "{category}",
            # Do NOT set archive-format — use gallery-dl's per-extractor defaults
            # N3: native rate limiting
            "sleep-retries": "exp=5",
            "sleep-429": "exp:2=120",
            # N4: content integrity
            "filesize-min": "1k",
            # N10b: deduplicate URLs within a single download run
            "file-unique": True,
        },
        "downloader": {
            # N4: fix mismatched extensions
            "adjust-extensions": True,
        },
        # N5: hash (result streamed via --Print N11) + mtime; N10d: filtered metadata
        "postprocessors": [
            {"name": "hash", "hash": "sha256"},
            {"name": "mtime"},
            {
                "name": "metadata",
                "mode": "json",
                "extension": "json",
                "include": [
                    "category", "subcategory",
                    "gallery_id", "id", "gid",
                    "title", "title_en", "title_jpn", "title_original",
                    "tags", "tag_string",
                    "date", "posted",
                    "uploader", "username", "user", "author",
                    "lang", "language",
                    "gallery_category", "rating",
                    "description", "content",
                    "filename", "extension", "num",
                ],
            },
        ],
    }

    # N2: subscription optimization
    if job_context == "subscription":
        config["extractor"]["skip"] = "abort:10"
        # N10a: batch archive writes (fewer PG round trips)
        config["extractor"]["archive-mode"] = "memory"
        if last_completed_at:
            cutoff = last_completed_at - timedelta(days=1)
            config["extractor"]["date-after"] = cutoff.strftime("%Y-%m-%dT%H:%M:%S")

    # Per-site download tuning via SiteConfigService
    all_params = await site_config_service.get_all_download_params()
    for site_cfg in GDL_SITES:
        params = all_params.get(site_cfg.source_id)
        ext = site_cfg.extractor or site_cfg.source_id
        entry = config["extractor"].setdefault(ext, {})

        # N1: archive-format uses gallery-dl defaults (not overridden)

        # Sleep request (existing v2.3)
        if params and params.sleep_request is not None:
            entry["sleep-request"] = (
                list(params.sleep_request) if isinstance(params.sleep_request, tuple)
                else params.sleep_request
            )

        # N7: browser profile
        if params and params.browser_profile:
            entry["browser"] = params.browser_profile

        # N7: per-site proxy
        if params and params.proxy_url:
            entry["proxy"] = params.proxy_url

    # N7: per-site rate limit
    for site_cfg in GDL_SITES:
        params = all_params.get(site_cfg.source_id)
        if params and params.rate_limit:
            config["downloader"]["rate"] = params.rate_limit

    # Merge credentials (unchanged from v2.3)
    for src, cred_val in credentials.items():
        # ... existing credential merge logic (unchanged) ...

    # N6: Pixiv ugoira conversion
    if any(src == "pixiv" for src in credentials):
        config["extractor"].setdefault("pixiv", {})["ugoira"] = True
        config["postprocessors"].append({
            "name": "ugoira",
            "extension": "mp4",
            "ffmpeg-args": ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-an"],
            "ffmpeg-twopass": False,
            "keep-files": False,
        })

    # N8: cookie session refresh
    for src, cred_val in credentials.items():
        cfg = get_site_config(src)
        if cfg.credential_type != "cookies" or not cred_val:
            continue
        ext = cfg.extractor or cfg.source_id
        cookie_update_path = f"/tmp/gdl-cookies-{config_id}-{src}.json"
        config["extractor"].setdefault(ext, {})["cookies-update"] = cookie_update_path

    # Write config file (unchanged from v2.3)
    config_path = Path(f"/app/config/gallery-dl-{config_id}.json") if config_id else Path(settings.gallery_dl_config)
    tmp_path = config_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(config, indent=2))
    os.rename(tmp_path, config_path)
    return config_path
```

---

## Implementation Phases

| Phase | Modules | Depends On | Estimated |
|-------|---------|------------|-----------|
| **1** | N1 (PG Archive) + N5A (psycopg in venv) | — | 2 days |
| **2** | N2 (Subscription optimization) | N1 (archive must be PG for abort:N to work with PG) | 1 day |
| **3** | N3 (Adaptive offload) + N4 (Content integrity) | — | 3 days |
| **4** | N5 (hash + mtime PP) | — | 1 day |
| **5** | N6 (ugoira) + N7 (browser/proxy) + N8 (cookies) + N9 (write-unsupported) | — | 2 days |
| **6** | M2 UI updates (new fields in Config Builder) + M4 Dashboard simplification | N3, N7 | 2 days |

Phases 1-5 are backend-only. Phase 6 is frontend. Total: ~11 days.

Phases 3, 4, 5 have no dependencies on each other and can be parallelized.

---

## Testing Strategy

Each module needs:

1. **Config generation test**: Verify `_build_gallery_dl_config()` outputs
   correct JSON for each feature.
2. **Integration test**: Run gallery-dl with generated config against a test
   URL (mock or real).
3. **Regression test**: Ensure existing download flow still works with new
   config parameters.

Specific tests:

| Module | Test |
|--------|------|
| N1 | Config contains `archive: postgresql://...`; `_cleanup_archive_entries()` uses SQLAlchemy |
| N2 | Subscription job config has `skip: abort:10` + `date-after`; manual job does not |
| N3 | Config has `sleep-429`; `AdaptiveState` has no `sleep_multiplier`; `_read_stderr` ignores 429 |
| N4 | Config has `filesize-min`; `_validate_download_content` has no empty branch |
| N5 | `.sha256` sidecar read; mtime used as `added_at`; fallback when sidecar missing |
| N6 | Pixiv config has ugoira PP; non-Pixiv does not |
| N7 | `browser_profile` + `proxy_url` injected per-site |
| N8 | Cookie update file read + credential save on change |
| N9 | Unsupported URLs captured in result |
| N10a | Subscription config has `archive-mode: "memory"`; manual does not |
| N10b | Config has `file-unique: true` |
| N10d | Config has `metadata` PP with `include` list; `--write-metadata`/`--write-tags` removed from cmd |
| N11 | `--Print` stdout has `JYZROX_FILE\t{path}\t{sha256}` and `JYZROX_SKIP`; no regex patterns; SHA256 from stdout not sidecar |
| N12 | Error URLs captured in result alongside unsupported URLs |
