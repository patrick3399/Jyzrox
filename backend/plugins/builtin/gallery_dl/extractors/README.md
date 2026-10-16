# Bundled custom gallery-dl extractors

Drop a `.py` file here to teach gallery-dl about a site it does not support.
Files are discovered automatically, and the file itself carries everything
Jyzrox needs to know about the site (`JYZROX_SITE`, below) — no `_sites.py`
entry, no `db/init.sql` table, no migration and no image rebuild. An empty
directory is a no-op: the generated gallery-dl config omits `module-sources`
entirely, so behaviour is unchanged until the first extractor lands here.

The whole workflow:

1. Write `<site>_gallery.py` with an extractor class and a `JYZROX_SITE` dict.
2. Verify it with the gallery-dl CLI ([Local development](#local-development)).
3. Put it in this directory — it is bind-mounted into `api` and `worker`.
4. `docker compose restart api worker` ([Deploying](#deploying)).

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

# Read by Jyzrox only; see "JYZROX_SITE" below.
JYZROX_SITE = {"domain": "example.com", "name": "Example", "category": "gallery", "has_tags": True}


class ExampleGalleryExtractor(GalleryExtractor):
    category = "examplesite"                  # becomes the gallery `source`
    root = "https://example.com"              # items() builds page_url from this
    pattern = r"(?:https?://)?(?:www\.)?example\.com/g/(\d+)"
    example = "https://example.com/g/12345"   # --list-extractors reads this
    directory_fmt = ("{category}", "{gallery_id} {title}")
    filename_fmt = "{num:>03}.{extension}"
    archive_fmt = "gallery={gallery_id}_{num}"

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
falls through. The in-process import is also what reads `JYZROX_SITE` and
names the archive table a download prepares, so a file that only the venv can
import downloads with no title, no tags and unlinked archive entries.

**A broken file does not break startup.** `load_inprocess()` logs and skips it —
so an import error surfaces as "site not detected", not a crash. Grep the
api/worker logs for `failed to load custom extractor` (import failed) or
`defines no extractor classes` (imported, but nothing with a `pattern` in it)
before debugging anything else. Success logs `loaded custom extractors: <name>`.

**Extractors must not live in `/opt/gallery-dl`.** That volume holds the
independently upgradable venv and is replaced on upgrade/rollback (HR-015).
This directory is bind-mounted from the host checkout into both containers at
`/app/plugins/builtin/gallery_dl/extractors/` (read-only; see
`docker-compose.yml`). The image still carries a copy, so an image run without
the mount keeps the bundled extractors.

## Wiring the site into Jyzrox

### `JYZROX_SITE`

Declare the site in the extractor file. gallery-dl ignores the dict;
`.._extractors.load_inprocess()` validates it at api/worker startup and
registers it next to `.._sites.GDL_SITES`, so URL detection, the supported-site
list, site settings, credentials and metadata parsing all see it:

```python
JYZROX_SITE = {
    "domain": "example.com",       # bare host; a leading "www." is dropped
    "name": "Example",             # display name
    "category": "gallery",         # gallery | manga | art | social | booru | filehost | other
    "has_tags": True,
    "title_fields": ("title",),    # dotted metadata paths, first non-empty wins
    "artist_fields": ("artist",),
    "source_id_fields": ("gallery_id",),
    "metadata_include": ("studio",),  # extra fields to keep, see below
}
```

- `source_id` defaults to the extractor's `category` and, when given, must be
  one of the module's extractor categories. A module with several categories
  can declare a list of dicts, one per category.
- Any other `GdlSiteConfig` field may be set (`credential_type`, `retries`,
  `sleep_request`, `subscribe_url_tpl`, …) except `extractor`,
  `feature_toggle_key`/`feature_toggle_attr` and `credential_warning_code`,
  which need code changes elsewhere.
- **`category` decides title and tags.** They are taken from the metadata
  sidecar only for `gallery` and `manga`; on any other category — and for a
  file without `JYZROX_SITE` — the gallery title is the identity string
  (`gallery=12345`) and no tags are written.
- **A built-in site always wins.** A `source_id` or `domain` already in
  `GDL_SITES` (or declared by an earlier file) keeps its owner; the declaration
  is ignored with a warning.
- **A bad declaration does not stop the extractor.** It loads and downloads,
  the site just behaves as unregistered. Look for
  `ignoring JYZROX_SITE in custom extractor` in the logs; success logs
  `registered site <source_id> (<domain>)`.

The metadata postprocessor drops every field `_METADATA_INCLUDE` in `..source`
does not list. The top-level key of each `title_fields`, `artist_fields` and
`source_id_fields` path is kept automatically; list anything else you need in
`metadata_include`. `--dump-json` shows what the extractor actually produces.

### Archive table — automatic

The generated config sets `archive-table: "{category}"`. Before gallery-dl
starts, the download creates that table with Jyzrox's columns (`entry`,
`gallery_id` FK with `ON DELETE CASCADE`, the `job_id` that records the writing
job, `created_at`) or upgrades the bare `(entry)` table gallery-dl made earlier.
That is what lets `ProgressiveImporter._link_archive_entries()` link entries to
their gallery, so deleting the gallery frees its files for a re-download.

A category whose name is already taken by a table that is not an archive
(e.g. `galleries`) fails the download before gallery-dl runs. Pick another
category.

### Gallery identity

For jobs handled by the gallery-dl plugin the download URL alone decides
`(source, source_id)` (ADR 0016): `{subcategory}={pattern groups joined by "/"}`,
e.g. `gallery=12345`. Capture the remote gallery's stable unique ID in the
pattern — never a username or a title (BE-T1, HR-018). `source_id_fields`,
`directory_fmt` and `url_path_id_index` only matter on the fallback paths taken
when in-process URL matching fails, so a failed in-process load shows up as a
second gallery with a different `source_id`.

**Start `archive_fmt` with that identity**, e.g.
`archive_fmt = "gallery={gallery_id}_{num}"`. `_link_archive_entries()` links
the entries the finishing job wrote (by `job_id`) and, in addition, any unlinked
entry whose key is the gallery's `source_id` followed by the end of the key or a
non-alphanumeric character. The second rule is what recovers entries left
behind by a download that died before linking, and it can only work when the
key names the gallery.

### When to edit `_sites.py` instead

Only to change a built-in site, or for the fields a drop-in file cannot set
(see above). Unknown categories are already preserved as the gallery `source`
rather than collapsed into `gallery_dl`.

## Deploying

Both `api` and `worker` read this directory: `worker` runs downloads, `api`
handles URL detection and site probing. Extractors and `JYZROX_SITE` are loaded
once at process start, so after adding or changing a file:

```bash
docker compose restart api worker
# nginx re-resolves the api container's IP every 10s, so no reload is needed;
# /api/* may answer 502 for a few seconds while api boots.
```

Confirm it landed:

```bash
docker compose logs api worker | grep -E 'loaded custom extractors|registered site|JYZROX_SITE'
docker compose exec worker /opt/gallery-dl/active/bin/gallery-dl --list-extractors | grep -i <category>
# Through nginx: 401 without a session cookie is healthy, 502 means step 2 was skipped.
curl -s -o /dev/null -w '%{http_code}\n' "http://localhost:${HTTP_PORT:-35689}/api/settings/features"
```

No image rebuild is needed: the directory is bind-mounted. A rebuild only
refreshes the fallback copy inside the image.
