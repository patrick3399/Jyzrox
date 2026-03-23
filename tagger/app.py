"""WD14 Tagger microservice — ONNX Runtime inference for anime image tagging."""

import csv
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── Configuration via env ──────────────────────────────────────────────
MODEL_REPO = os.environ.get("TAG_MODEL_NAME", "SmilingWolf/wd-swinv2-tagger-v3")
MODEL_FILENAME = "model.onnx"
TAGS_FILENAME = "selected_tags.csv"
INPUT_SIZE = 448
ONNX_PROVIDERS = os.environ.get("ONNX_PROVIDERS", "CPUExecutionProvider").split(",")
_ALLOWED_IMAGE_ROOTS = (Path("/data").resolve(), Path("/mnt").resolve())

# ── Global model state ─────────────────────────────────────────────────
_model = None
_tags: list[dict] | None = None
_ort_version: str | None = None


def _load_model():
    """Eager-load ONNX model and tags CSV from HuggingFace Hub cache."""
    global _model, _tags, _ort_version

    import onnxruntime as ort
    from huggingface_hub import hf_hub_download

    _ort_version = ort.__version__

    logger.info("Loading WD14 model from %s ...", MODEL_REPO)

    model_path = hf_hub_download(MODEL_REPO, MODEL_FILENAME)
    tags_path = hf_hub_download(MODEL_REPO, TAGS_FILENAME)

    _model = ort.InferenceSession(model_path, providers=ONNX_PROVIDERS)

    _tags = []
    with open(tags_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            _tags.append({
                "name": row["name"],
                "category": int(row["category"]),
            })

    logger.info("Model loaded. %d tags available.", len(_tags))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_model()
    yield


app = FastAPI(title="WD14 Tagger", lifespan=lifespan)


# ── Schemas ────────────────────────────────────────────────────────────

class PredictRequest(BaseModel):
    image_path: str
    general_threshold: float = 0.35
    character_threshold: float = 0.85


class TagResult(BaseModel):
    namespace: str
    name: str
    confidence: float


class PredictResponse(BaseModel):
    tags: list[TagResult]


# ── Preprocessing ──────────────────────────────────────────────────────

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


# ── Endpoints ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model_loaded": _model is not None,
        "model_name": MODEL_REPO,
        "onnxruntime_version": _ort_version,
        "providers": ONNX_PROVIDERS,
    }


@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    if _model is None or _tags is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    path = Path(req.image_path).resolve()
    if not any(path.is_relative_to(r) for r in _ALLOWED_IMAGE_ROOTS):
        raise HTTPException(status_code=400, detail="Image path must be within /data/ or /mnt/")
    if not path.exists():
        raise HTTPException(status_code=400, detail="Image not found")

    import asyncio
    try:
        tags = await asyncio.to_thread(
            _run_inference, str(path), req.general_threshold, req.character_threshold
        )
    except Exception as exc:
        logger.error("Inference failed for %s: %s", req.image_path, exc)
        raise HTTPException(status_code=500, detail="Inference failed") from None

    return PredictResponse(tags=tags)


def _run_inference(
    image_path: str,
    general_threshold: float,
    character_threshold: float,
) -> list[TagResult]:
    """Run WD14 inference on a single image (synchronous, called in thread)."""
    assert _model is not None and _tags is not None

    input_data = _preprocess(image_path)
    input_name = _model.get_inputs()[0].name
    output_name = _model.get_outputs()[0].name
    probs = _model.run([output_name], {input_name: input_data})[0][0]

    results: list[TagResult] = []

    for i, prob in enumerate(probs):
        if i >= len(_tags):
            break

        tag_info = _tags[i]
        category = tag_info["category"]
        name = tag_info["name"].replace(" ", "_")

        if category == 0:  # general
            if prob >= general_threshold:
                results.append(TagResult(namespace="general", name=name, confidence=float(prob)))
        elif category == 4:  # character
            if prob >= character_threshold:
                results.append(TagResult(namespace="character", name=name, confidence=float(prob)))
        elif category == 9:  # rating
            if prob >= 0.5:
                results.append(TagResult(namespace="rating", name=name, confidence=float(prob)))

    results.sort(key=lambda x: x.confidence, reverse=True)
    return results
