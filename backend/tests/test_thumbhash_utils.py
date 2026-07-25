"""
Unit tests for worker/thumbhash_utils.py.

These exercise the real ``thumbhash`` package rather than a mock: the bug they
guard against lives in the interaction between Pillow's alpha channel and the
encoder, so a mocked ``rgba_to_thumb_hash`` would not reproduce it.
"""

import base64

import pytest
from PIL import Image

from worker.thumbhash_utils import encode_pil_thumbhash


def _decoded_length(hash_b64: str) -> int:
    return len(base64.b64decode(hash_b64))


def _partially_transparent_rgba() -> Image.Image:
    """An RGBA image whose alpha is mostly opaque with a soft transparent edge."""
    image = Image.new("RGBA", (40, 30), (200, 60, 40, 255))
    for x in range(6):
        for y in range(30):
            image.putpixel((x, y), (200, 60, 40, 40 * x))
    return image


def _palette_with_transparency() -> Image.Image:
    image = Image.new("P", (40, 30))
    image.putpalette([200, 60, 40] * 256)
    image.info["transparency"] = 0
    return image


def test_thumbhash_partially_transparent_image_does_not_raise_tuple_error():
    """Non-opaque alpha must not reach the encoder's broken has_alpha branch.

    thumbhash 0.1.2 unpacks ``encode_channel(a, 5, 5) if has_alpha else 1.0, [], 1.0``
    with the conditional binding to the first target only, so ``a_dc`` becomes the
    whole ``(dc, ac, scale)`` tuple and ``round(15 * a_dc)`` raises
    ``TypeError: type tuple doesn't define __round__ method``.  Flattening the
    image before encoding keeps us out of that branch entirely.
    """
    result = encode_pil_thumbhash(_partially_transparent_rgba())

    assert _decoded_length(result) > 0


def test_thumbhash_fully_transparent_region_does_not_raise_tuple_error():
    """A fully transparent region (alpha 0) is the same broken branch."""
    image = Image.new("RGBA", (40, 30), (200, 60, 40, 255))
    for x in range(20):
        for y in range(30):
            image.putpixel((x, y), (0, 0, 0, 0))

    assert _decoded_length(encode_pil_thumbhash(image)) > 0


@pytest.mark.parametrize(
    "image_factory",
    [
        pytest.param(_palette_with_transparency, id="P-with-transparency"),
        pytest.param(lambda: Image.new("LA", (40, 30), (128, 0)), id="LA-transparent"),
        pytest.param(lambda: Image.new("RGBA", (40, 30), (200, 60, 40, 255)), id="RGBA-opaque"),
        pytest.param(lambda: Image.new("RGB", (40, 30), (200, 60, 40)), id="RGB"),
        pytest.param(lambda: Image.new("L", (40, 30), 128), id="L"),
        pytest.param(lambda: Image.new("CMYK", (40, 30)), id="CMYK"),
        pytest.param(lambda: Image.new("1", (40, 30), 1), id="bilevel"),
    ],
)
def test_thumbhash_encodes_every_supported_mode(image_factory):
    """Every mode the thumbnail pipeline can hand us produces a usable hash."""
    assert _decoded_length(encode_pil_thumbhash(image_factory())) > 0


def test_thumbhash_does_not_mutate_the_source_image():
    """The caller reuses the image for phash and width/height after hashing."""
    image = _partially_transparent_rgba()

    encode_pil_thumbhash(image)

    assert image.size == (40, 30)
    assert image.mode == "RGBA"


def test_thumbhash_of_rgba_source_equals_thumbhash_of_its_rgb_flattening():
    """Encoding is driven purely by the flattened RGB pixels, not by the alpha channel.

    ``thumbhash_backfill`` re-derives the hash from ``thumb_160.webp``, which the
    thumbnail job writes from ``pil.convert("RGB")``.  Hashing the original and
    hashing its own RGB flattening must therefore give the same answer -- the
    backfill route only differs by the lossy WebP resize in between.
    """
    original = _partially_transparent_rgba()

    assert encode_pil_thumbhash(original) == encode_pil_thumbhash(original.convert("RGB"))
