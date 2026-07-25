"""ThumbHash encoding helpers."""

import base64
from typing import Any


def encode_pil_thumbhash(image: Any) -> str:
    """Return a base64 ThumbHash for a Pillow image.

    The image is flattened to RGB before encoding.  thumbhash 0.1.2 cannot encode
    an image with non-opaque alpha: it unpacks
    ``encode_channel(a, 5, 5) if has_alpha else 1.0, [], 1.0`` where the
    conditional binds to the first target only, so ``a_dc`` receives the whole
    ``(dc, ac, scale)`` tuple and ``round(15 * a_dc)`` raises
    ``TypeError: type tuple doesn't define __round__ method``.  Flattening keeps us
    out of that branch and matches the stored thumbnails, which the thumbnail job
    also writes from ``convert("RGB")``.
    """
    from thumbhash import rgba_to_thumb_hash

    # convert() always returns a new image, so the caller's image stays untouched.
    flattened = image.convert("RGB")
    flattened.thumbnail((100, 100))
    rgba = flattened.convert("RGBA")
    # "P"/"L" sources carry info["transparency"] through the RGB conversion, which
    # the RGBA conversion then turns back into real alpha; force the channel opaque.
    rgba.putalpha(255)
    hash_bytes = bytes(rgba_to_thumb_hash(rgba.width, rgba.height, list(rgba.tobytes())))
    return base64.b64encode(hash_bytes).decode()
