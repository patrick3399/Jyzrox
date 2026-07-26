# Bundled custom gallery-dl extractors

Drop a `.py` file here to teach gallery-dl about a site it does not support.
Files are discovered automatically — nothing to register. An empty directory is
a no-op: the generated gallery-dl config omits `module-sources` entirely, so
behaviour is unchanged until the first extractor lands here.

See `.._extractors` for how the two consumers (download subprocess and
in-process category detection) are wired.

## Writing one

Standard gallery-dl extractor classes — a `pattern`, a `category`, and the
usual `items()`. Refer to gallery-dl's own `extractor/` package for examples.

```python
from gallery_dl.extractor.common import GalleryExtractor

class ExampleGalleryExtractor(GalleryExtractor):
    category = "example"
    pattern = r"(?:https?://)?(?:www\.)?example\.com/g/(\d+)"
    ...
```

## Rules

**Module names are global.** gallery-dl imports these as top-level modules
(`import <stem>`), so a file named `json.py` or `requests.py` collides with the
real package. Prefix filenames with the site name, e.g. `example_gallery.py`.

**Custom extractors are matched before built-ins.** Both the config
(`[<this dir>, null]`) and the in-process loader put this directory first.
Reusing a built-in `category` shadows it — do that only on purpose.

**Two gallery-dl installations must both import the file.** The download
subprocess runs the upgradable venv at `/opt/gallery-dl`; category detection
imports the copy baked into the image. Stick to API surface that is stable
across versions, or the extractor works for downloads while URL detection
silently falls through.

**A broken file does not break startup.** `load_inprocess()` logs and skips it —
which means an import error shows up as "site not detected" rather than a crash.
Check the API/worker logs for `failed to load custom extractor` before debugging
anything else.

## After adding an extractor

1. **Register the site in `.._sites.GDL_SITES`.** Without an entry,
   `get_site_config()` returns `_DEFAULT_CONFIG` and the importer files every
   gallery under `source_id="gallery_dl"` ("Unknown Site") instead of the real
   source. Set `extractor=` when the gallery-dl `category` differs from
   `source_id`.

2. **Set `url_path_id_index` deliberately.** It decides which URL path segment
   becomes the gallery's source identity. Leaving the default on a site whose
   ID is not the first segment lets distinct remote galleries upsert into one
   row (HR-018).

3. **Check `_METADATA_INCLUDE` in `..source`.** The metadata postprocessor
   drops any field not on that allowlist. Either emit the existing field names
   or extend the allowlist.
