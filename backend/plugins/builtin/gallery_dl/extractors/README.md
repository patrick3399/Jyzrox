# Bundled custom gallery-dl extractors

Drop a `.py` file here to teach gallery-dl about a site it does not support.
Files are discovered automatically — nothing to register. An empty directory is
a no-op: the generated gallery-dl config omits `module-sources` entirely, so
behaviour is unchanged until the first extractor lands here.

Three consumers load these files, and all three read this same directory:

| Consumer | Mechanism | Wired in |
| --- | --- | --- |
| Download subprocess | `extractor.module-sources` in the generated config | `..source._build_gallery_dl_config()` |
| In-process URL/category detection and `directory_fmt` lookup | `extractor.add_module()` at startup | `.._extractors.load_inprocess()` |
| Admin site probe (`--dump-json`) | `-X/--extractors` on the CLI | `core.probe._run_gallery_dl_probe()` |

The probe needs its own flag because it deliberately runs with
`--config /dev/null` to keep credentials out of probe runs, so it never sees
`module-sources`. See `.._extractors` for the rest of the wiring.

## Local development

gallery-dl is **not** in `backend/.venv` — it is installed in the image and in
the upgradable venv only. Importing it from a local shell fails until you put
the production venv on `PYTHONPATH`:

```bash
export $(grep -E '^JYZROX_DATA_ROOT=' .env)
export GDL_SITE_PACKAGES="$(ls -d "$JYZROX_DATA_ROOT"/venv/active/lib/python*/site-packages)"
PYTHONPATH="$GDL_SITE_PACKAGES" backend/.venv/bin/python -c "import gallery_dl; print(gallery_dl.version.__version__)"
```

That borrows the exact version downloads run against. Alternatively
`pip install gallery-dl==<that version>` into `backend/.venv`, but then you own
keeping it in step with the venv.

### The whole loop runs offline

An extractor whose first pattern group does **not** start with `/` leaves
`page_url` as `None`, so `GalleryExtractor.items()` skips its HTTP request and
calls `metadata(None)` / `images(None)` directly. Stub those two and you can
exercise the full pipeline with no network and no credentials:

```bash
export EXTRACTORS=backend/plugins/builtin/gallery_dl/extractors

# 1. Registration + pattern compile + the attributes --list-extractors reads
PYTHONPATH="$GDL_SITE_PACKAGES" backend/.venv/bin/python -m gallery_dl \
  --config-ignore -X "$EXTRACTORS" --list-extractors | grep -A2 YourExtractor

# 2. Resolved filenames, without downloading
PYTHONPATH="$GDL_SITE_PACKAGES" backend/.venv/bin/python -m gallery_dl \
  --config-ignore -X "$EXTRACTORS" --simulate "https://site.example/g/12345"

# 3. Exactly what the admin probe parses
PYTHONPATH="$GDL_SITE_PACKAGES" backend/.venv/bin/python -m gallery_dl \
  --config-ignore -X "$EXTRACTORS" --dump-json "https://site.example/g/12345"
```

`--config-ignore` keeps your own `~/.config/gallery-dl` out of the run. Use
`--dump-json` to confirm the metadata field names before touching
`_METADATA_INCLUDE` or `source_id_fields`.

Once real network calls are involved, point `-X` at the same directory and drop
`--simulate`; add `-o cookies=...` rather than editing the app's config.

> `backend/tests/test_gallery_dl_extractors.py` stubs `gallery_dl` so the suite
> runs without it installed. A green suite says nothing about whether your
> extractor matches the real gallery-dl API — the commands above are what
> verify that.

## Writing one

`GalleryExtractor` already implements `items()`. **Do not override it** — that
discards the directory message, page enumeration, `page-reverse` handling and
asset support. Implement `metadata()` and `images()` instead:

```python
from gallery_dl.extractor.common import GalleryExtractor


class ExampleGalleryExtractor(GalleryExtractor):
    category = "examplesite"                  # becomes the gallery `source`
    root = "https://example.com"              # items() builds page_url from this
    pattern = r"(?:https?://)?(?:www\.)?example\.com/g/(\d+)"
    example = "https://example.com/g/12345"   # --list-extractors reads this
    directory_fmt = ("{category}", "{gallery_id} {title}")
    filename_fmt = "{num:>03}.{extension}"
    archive_fmt = "{gallery_id}_{num}"

    def metadata(self, page):
        """Return a dict of gallery-level metadata."""
        return {"gallery_id": self.groups[0], "title": "...", "count": 2}

    def images(self, page):
        """Return an iterable of (image-url, metadata-dict-or-None) tuples."""
        return [(f"{self.root}/img/{n}.jpg", None) for n in (1, 2)]
```

Optional hooks: `login()` for cookie/session setup, `assets()` for extra files
(each asset needs at least `url` and `type`). Refer to gallery-dl's own
`extractor/` package for real examples.

Omitting `example` is not cosmetic — `--list-extractors` raises
`AttributeError` on it, which is how a missing attribute usually surfaces.

## Rules

**Module names are global.** gallery-dl imports these as top-level modules
(`import <stem>`), so a file named `json.py` or `requests.py` collides with the
real package. Prefix filenames with the site name, e.g. `example_gallery.py`.

**Custom extractors are matched before built-ins.** Both the config
(`[<this dir>, null]`) and the in-process loader put this directory first.
Reusing a built-in `category` shadows it — do that only on purpose.

**Two gallery-dl installations must both import the file.** Downloads and the
probe run the upgradable venv at `/opt/gallery-dl`; in-process detection imports
the copy baked into the image, which only changes on an image rebuild and can
therefore be an older release. Stick to API surface that is stable across
versions, or the extractor works for downloads while URL detection silently
falls through.

**A broken file does not break startup.** `load_inprocess()` logs and skips it —
so an import error surfaces as "site not detected", not a crash. Grep the
api/worker logs for `failed to load custom extractor` (import failed) or
`defines no extractor classes` (imported, but nothing with a `pattern` in it)
before debugging anything else. Success logs `loaded custom extractors: <name>`.

**Extractors must not live in `/opt/gallery-dl`.** That volume holds the
independently upgradable venv and is replaced on upgrade/rollback (HR-015).
This directory ships in the image at
`/app/plugins/builtin/gallery_dl/extractors/` instead.

## Wiring the site into Jyzrox

### Required for correctness

**1. Add the archive table to `db/init.sql`.** The generated config sets
`archive-table: "{category}"`, so every category needs its own table. If it is
missing, gallery-dl creates one itself as `(entry TEXT PRIMARY KEY)` — without
the `gallery_id` FK Jyzrox needs — and the failure is close to invisible:

- `ProgressiveImporter._link_archive_entries()` fails inside a savepoint and
  only emits `failed to link archive entries`; the download and import look fine
- archive entries stay unlinked, so trashing or deleting the gallery never
  cascades them away
- a later re-download is skipped as "already archived" and finishes with
  **0 images**

Follow the existing pattern in the `gallery-dl archive tables` section. Both
linking strategies need `job_id` and `created_at`:

```sql
CREATE TABLE IF NOT EXISTS examplesite (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    job_id      UUID,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_examplesite_unlinked ON examplesite (job_id) WHERE gallery_id IS NULL;
```

`db/init.sql` must stay equal to the HEAD schema (BE-T15), so add a migration
with the same idempotent DDL. Changing `db/init.sql` also requires
`docker compose build migrate` — editing the file alone does not reach the image.

**2. Register the site in `.._sites.GDL_SITES` if the table name differs from
the category.** `_link_archive_entries()` resolves the table as
`cfg.extractor or cfg.source_id`, and an unregistered category falls through to
`_DEFAULT_CONFIG` — i.e. it looks for a table literally named `gallery_dl`
(BE-T3). Registering with `extractor=` set is what keeps the two in step.

**3. Choose a stable gallery identity deliberately.** Metadata imports resolve
`source_id` from the registered site's `source_id_fields`, then the extractor's
`directory_fmt`, then `gallery_id` / `id`. Make sure one of those yields the
remote gallery's stable unique ID, or refreshes create duplicates and distinct
remote galleries collide (HR-018). Never use a username (BE-T1).
`url_path_id_index` applies only to the no-metadata URL fallback in
`ProgressiveImporter.ensure_gallery_from_url()`; set it too if the extractor can
finish without emitting a metadata sidecar.

**4. Check `_METADATA_INCLUDE` in `..source`.** The metadata postprocessor drops
any field not on that allowlist. Either emit the existing field names or extend
it — `--dump-json` above shows what your extractor actually produces.

### Optional

Unknown categories are preserved as the gallery `source` (they are not collapsed
into `gallery_dl`), so registration is not needed just to avoid "Unknown Site".
Beyond the table-name case above, register when the site needs a canonical
source ID, display metadata, credentials, download tuning, subscriptions, or
non-default metadata rules.

## Deploying

Adding or changing an extractor needs an image rebuild — the directory is baked
in, not bind-mounted. Use the `/deploy` skill, which builds, restarts, reloads
nginx and verifies the endpoints. Both `api` and `worker` need the file: `worker`
runs downloads, `api` handles URL detection and site probing.

Confirm it landed:

```bash
docker compose logs api worker | grep 'loaded custom extractors'
docker compose exec worker /opt/gallery-dl/active/bin/gallery-dl --list-extractors | grep -i <category>
```
