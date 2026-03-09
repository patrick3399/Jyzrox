"""WD14 tagger service — ONNX Runtime inference for anime image tagging."""

import csv
import logging
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_model = None
_tags: list[dict] | None = None

MODEL_REPO = "SmilingWolf/wd-swinv2-tagger-v3"
MODEL_FILENAME = "model.onnx"
TAGS_FILENAME = "selected_tags.csv"
INPUT_SIZE = 448


def _ensure_model():
    """Lazy-load ONNX model and tags CSV from HuggingFace Hub cache."""
    global _model, _tags
    if _model is not None:
        return

    import onnxruntime as ort
    from huggingface_hub import hf_hub_download

    logger.info("[tagger] Loading WD14 model from %s ...", MODEL_REPO)

    model_path = hf_hub_download(MODEL_REPO, MODEL_FILENAME)
    tags_path = hf_hub_download(MODEL_REPO, TAGS_FILENAME)

    _model = ort.InferenceSession(
        model_path,
        providers=["CPUExecutionProvider"],
    )

    _tags = []
    with open(tags_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            _tags.append({
                "name": row["name"],
                "category": int(row["category"]),
                # category: 0=general, 4=character, 9=rating
            })

    logger.info("[tagger] Model loaded. %d tags available.", len(_tags))


def _preprocess(image_path: str) -> np.ndarray:
    """Resize and normalize image for WD14 input (448x448 RGB)."""
    img = Image.open(image_path).convert("RGBA")

    # Paste onto white background (handle transparency)
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    bg.paste(img, mask=img)
    img = bg.convert("RGB")

    # Pad to square then resize
    max_dim = max(img.size)
    padded = Image.new("RGB", (max_dim, max_dim), (255, 255, 255))
    padded.paste(img, ((max_dim - img.width) // 2, (max_dim - img.height) // 2))
    resized = padded.resize((INPUT_SIZE, INPUT_SIZE), Image.LANCZOS)

    # Convert to numpy: HWC float32, BGR, normalized to [0, 1]
    arr = np.array(resized, dtype=np.float32) / 255.0
    arr = arr[:, :, ::-1]  # RGB → BGR (WD14 expects BGR)
    return np.expand_dims(arr, axis=0)


def predict(image_path: str, general_threshold: float = 0.35, character_threshold: float = 0.85) -> list[tuple[str, str, float]]:
    """
    Run WD14 inference on a single image.

    Returns list of (namespace, tag_name, confidence) tuples.
    namespace is one of: "general", "character", "rating"
    """
    _ensure_model()
    assert _model is not None and _tags is not None

    input_data = _preprocess(image_path)
    input_name = _model.get_inputs()[0].name
    output_name = _model.get_outputs()[0].name
    probs = _model.run([output_name], {input_name: input_data})[0][0]

    results: list[tuple[str, str, float]] = []

    for i, prob in enumerate(probs):
        if i >= len(_tags):
            break

        tag_info = _tags[i]
        category = tag_info["category"]
        name = tag_info["name"].replace(" ", "_")

        if category == 0:  # general
            if prob >= general_threshold:
                results.append(("general", name, float(prob)))
        elif category == 4:  # character
            if prob >= character_threshold:
                results.append(("character", name, float(prob)))
        elif category == 9:  # rating
            if prob >= 0.5:
                results.append(("rating", name, float(prob)))

    # Sort by confidence descending
    results.sort(key=lambda x: x[2], reverse=True)
    return results
