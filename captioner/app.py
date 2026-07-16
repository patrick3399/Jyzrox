"""Pluggable Florence-2 / JoyCaption image caption microservice."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ENGINE = os.environ.get("CAPTION_ENGINE", "florence2").lower()
MODEL_NAME = os.environ.get(
    "CAPTION_MODEL_NAME",
    "microsoft/Florence-2-base" if ENGINE == "florence2" else "fancyfeast/llama-joycaption-alpha-two-hf-llava",
)
DEVICE = os.environ.get("CAPTION_DEVICE", "cpu")
_ALLOWED_IMAGE_ROOTS = (Path("/data").resolve(), Path("/mnt").resolve())

_model = None
_processor = None


def _load_model() -> None:
    global _model, _processor
    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor

    dtype = torch.float16 if DEVICE.startswith("cuda") else torch.float32
    _processor = AutoProcessor.from_pretrained(MODEL_NAME, trust_remote_code=True)
    _model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        trust_remote_code=True,
        torch_dtype=dtype,
    ).to(DEVICE)
    _model.eval()
    logger.info("Loaded caption model %s for engine %s on %s", MODEL_NAME, ENGINE, DEVICE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(_load_model)
    yield


app = FastAPI(title="Jyzrox Captioner", lifespan=lifespan)


class CaptionRequest(BaseModel):
    image_path: str
    engine: str = Field(pattern="^(florence2|joycaption)$")
    tags: list[str] = Field(default_factory=list, max_length=500)


class CaptionResponse(BaseModel):
    caption: str
    engine: str
    model: str


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model_loaded": _model is not None and _processor is not None,
        "engine": ENGINE,
        "model": MODEL_NAME,
        "device": DEVICE,
    }


@app.post("/caption", response_model=CaptionResponse)
async def caption(request: CaptionRequest):
    if request.engine != ENGINE:
        raise HTTPException(status_code=409, detail=f"Service is configured for {ENGINE}")
    path = Path(request.image_path).resolve()
    if not any(path.is_relative_to(root) for root in _ALLOWED_IMAGE_ROOTS):
        raise HTTPException(status_code=400, detail="Image path must be within /data/ or /mnt/")
    if not path.is_file():
        raise HTTPException(status_code=400, detail="Image not found")
    try:
        result = await asyncio.to_thread(_run_caption, path, request.tags)
    except Exception as exc:
        logger.exception("Caption inference failed for %s", path)
        raise HTTPException(status_code=500, detail=f"Caption inference failed: {type(exc).__name__}") from None
    return CaptionResponse(caption=result, engine=ENGINE, model=MODEL_NAME)


def _run_caption(path: Path, tags: list[str]) -> str:
    if _model is None or _processor is None:
        raise RuntimeError("Caption model is not loaded")
    import torch

    image = Image.open(path).convert("RGB")
    if ENGINE == "florence2":
        task = "<MORE_DETAILED_CAPTION>"
        inputs = _processor(text=task, images=image, return_tensors="pt")
        inputs = {key: value.to(DEVICE) for key, value in inputs.items()}
        with torch.inference_mode():
            generated = _model.generate(**inputs, max_new_tokens=256, num_beams=3)
        decoded = _processor.batch_decode(generated, skip_special_tokens=False)[0]
        parsed = _processor.post_process_generation(decoded, task=task, image_size=image.size)
        return str(parsed.get(task) or decoded).strip()

    tag_context = ", ".join(tags[:80])
    prompt = "Write one detailed natural-language training caption for this image."
    if tag_context:
        prompt += f" Relevant tags: {tag_context}."
    inputs = _processor(text=prompt, images=image, return_tensors="pt")
    inputs = {key: value.to(DEVICE) for key, value in inputs.items()}
    with torch.inference_mode():
        generated = _model.generate(**inputs, max_new_tokens=256)
    decoded = _processor.batch_decode(generated, skip_special_tokens=True)[0]
    return decoded.removeprefix(prompt).strip()
