"""ThumbHash encoding helpers."""

import base64
from typing import Any


def encode_pil_thumbhash(image: Any) -> str:
    """Return a base64 ThumbHash for a Pillow image."""
    from thumbhash import rgba_to_thumb_hash

    rgba = image.convert("RGBA")
    rgba.thumbnail((100, 100))
    hash_bytes = bytes(rgba_to_thumb_hash(rgba.width, rgba.height, list(rgba.tobytes())))
    return base64.b64encode(hash_bytes).decode()
