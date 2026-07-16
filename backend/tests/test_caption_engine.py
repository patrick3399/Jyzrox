"""Tests for caption engine abstraction and remote response handling."""

from unittest.mock import AsyncMock, MagicMock, patch

from services.caption_engine import CaptionEngineRegistry, RemoteCaptionEngine
from worker.captioning import caption_job


def test_caption_engine_registry_supports_multiple_sources():
    registry = CaptionEngineRegistry()
    florence = RemoteCaptionEngine("florence2")
    joy = RemoteCaptionEngine("joycaption")
    registry.register(florence)
    registry.register(joy)

    assert registry.list() == ["florence2", "joycaption"]
    assert registry.get("florence2") is florence
    assert registry.get("joycaption") is joy


async def test_remote_caption_engine_returns_caption(tmp_path):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"caption": "A person beneath flowering trees.", "model": "florence"}
    client = AsyncMock()
    client.post.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client
    context.__aexit__.return_value = None
    image = tmp_path / "image.png"
    image.write_bytes(b"not-read-by-client")
    engine = RemoteCaptionEngine("florence2")

    with (
        patch("services.caption_engine.httpx.AsyncClient", return_value=context),
        patch.object(engine, "_url", new=AsyncMock(return_value="http://captioner:8200")),
    ):
        result = await engine.caption(image, ["character:alice"])

    assert result.caption == "A person beneath flowering trees."
    client.post.assert_awaited_once_with(
        "http://captioner:8200/caption",
        json={"image_path": str(image), "engine": "florence2", "tags": ["character:alice"]},
    )


async def test_caption_job_respects_runtime_toggle():
    with patch("worker.captioning.get_toggle", new=AsyncMock(return_value=False)) as get_toggle:
        result = await caption_job({}, 1, "florence2")

    assert result == {"status": "skipped", "reason": "captioner_enabled=false"}
    get_toggle.assert_awaited_once()
