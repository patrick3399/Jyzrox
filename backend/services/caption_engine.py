"""Pluggable remote natural-language caption engines."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from core.config import settings
from services.settings_store import get_string_setting


@dataclass(frozen=True)
class CaptionResult:
    caption: str
    engine: str
    model: str | None = None


class CaptionEngine(Protocol):
    engine_id: str

    async def health(self) -> dict: ...

    async def caption(self, image_path: Path, tags: list[str]) -> CaptionResult: ...


class RemoteCaptionEngine:
    def __init__(self, engine_id: str) -> None:
        self.engine_id = engine_id

    async def _url(self) -> str:
        return (await get_string_setting("setting:captioner_url", settings.captioner_url)).rstrip("/")

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{await self._url()}/health")
                response.raise_for_status()
                return {"online": True, **response.json()}
        except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
            return {"online": False, "engine": self.engine_id, "error": str(exc)}

    async def caption(self, image_path: Path, tags: list[str]) -> CaptionResult:
        async with httpx.AsyncClient(timeout=settings.captioner_timeout) as client:
            response = await client.post(
                f"{await self._url()}/caption",
                json={"image_path": str(image_path), "engine": self.engine_id, "tags": tags},
            )
            response.raise_for_status()
            data = response.json()
        caption = str(data.get("caption") or "").strip()
        if not caption:
            raise ValueError("Caption service returned an empty caption")
        return CaptionResult(caption=caption, engine=self.engine_id, model=data.get("model"))


class CaptionEngineRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, CaptionEngine] = {}

    def register(self, engine: CaptionEngine) -> None:
        self._engines[engine.engine_id] = engine

    def get(self, engine_id: str) -> CaptionEngine | None:
        return self._engines.get(engine_id)

    def list(self) -> list[str]:
        return sorted(self._engines)


caption_engine_registry = CaptionEngineRegistry()
caption_engine_registry.register(RemoteCaptionEngine("florence2"))
caption_engine_registry.register(RemoteCaptionEngine("joycaption"))
