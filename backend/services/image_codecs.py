"""Optional Pillow decoders for formats Pillow cannot read on its own."""

_registered = False


def register_image_codecs() -> None:
    """Register the HEIF and JPEG XL openers once; a missing package is skipped."""
    global _registered
    if _registered:
        return
    try:
        # .heic is an accepted import extension but Pillow has no HEIF decoder of its own.
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:
        pass
    try:
        import pillow_jxl  # noqa: F401  - importing registers the JXL plugin
    except ImportError:
        pass
    _registered = True
