"""Remote SwarmUI processor for image refinement and upscaling."""

import base64
import mimetypes
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from core.config import settings
from plugins.models import PluginMeta, ProcessResult, ServiceHealth
from services.settings_store import get_string_setting, get_toggle


class SwarmUiPlugin:
    meta = PluginMeta(
        name="SwarmUI",
        source_id="swarmui",
        version="1.0.0",
        description="Remote AI image refinement and upscaling service",
    )

    async def _base_url(self) -> str:
        value = await get_string_setting("setting:swarmui_url", settings.swarmui_url)
        return value.rstrip("/")

    async def _session(self, client: httpx.AsyncClient, base_url: str) -> str:
        response = await client.post(f"{base_url}/API/GetNewSession", json={})
        response.raise_for_status()
        session_id = response.json().get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("SwarmUI did not return a session_id")
        return session_id

    async def health(self) -> ServiceHealth:
        if not await get_toggle("setting:swarmui_enabled", settings.swarmui_enabled):
            return ServiceHealth(online=False, service="SwarmUI", error="SwarmUI is disabled")

        try:
            base_url = await self._base_url()
            async with httpx.AsyncClient(timeout=10) as client:
                session_id = await self._session(client, base_url)
                resource_response = await client.post(
                    f"{base_url}/API/GetServerResourceInfo", json={"session_id": session_id}
                )
                params_response = await client.post(
                    f"{base_url}/API/ListT2IParams", json={"session_id": session_id}
                )
                resource_response.raise_for_status()
                params_response.raise_for_status()

            resource = resource_response.json()
            params = params_response.json()
            gpu = self._extract_gpu(resource)
            return ServiceHealth(
                online=True,
                service="SwarmUI",
                version=self._first_text(resource, "version", "server_version", "swarm_version"),
                gpu_name=self._first_text(gpu, "name", "gpu_name", "device_name", "device"),
                vram_total_mb=self._first_megabytes(gpu, "vram_total", "total_vram", "memory_total"),
                vram_free_mb=self._first_megabytes(gpu, "vram_free", "free_vram", "memory_free"),
                models=self._extract_models(params),
            )
        except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
            return ServiceHealth(online=False, service="SwarmUI", error=str(exc))

    async def process(self, input_path: Path, output_dir: Path, options: dict) -> ProcessResult:
        if not await get_toggle("setting:swarmui_enabled", settings.swarmui_enabled):
            return ProcessResult(status="failed", error="SwarmUI is disabled")

        scale = float(options.get("scale", 2))
        if scale not in {1.5, 2.0, 3.0, 4.0}:
            return ProcessResult(status="failed", error="scale must be one of 1.5, 2, 3, or 4")
        model = str(options.get("model") or "").strip()
        if len(model) > 300:
            return ProcessResult(status="failed", error="model name is too long")

        media_type = mimetypes.guess_type(input_path.name)[0] or "image/png"
        encoded = base64.b64encode(input_path.read_bytes()).decode("ascii")
        payload: dict = {
            "prompt": str(options.get("prompt") or ""),
            "images": 1,
            "initimage": f"data:{media_type};base64,{encoded}",
            "initimagecreativity": 0,
            "refinerupscale": scale,
            "refinertiling": bool(options.get("tiling", True)),
            "donotsave": False,
        }
        if model:
            payload["refinermodel"] = model

        try:
            base_url = await self._base_url()
            async with httpx.AsyncClient(timeout=settings.swarmui_timeout) as client:
                payload["session_id"] = await self._session(client, base_url)
                response = await client.post(f"{base_url}/API/GenerateText2Image", json=payload)
                response.raise_for_status()
                data = response.json()
                image_url = self._extract_image_url(data)
                if not image_url:
                    message = data.get("error") if isinstance(data, dict) else None
                    raise ValueError(str(message or "SwarmUI returned no output image"))
                absolute_url = urljoin(f"{base_url}/", image_url)
                if urlparse(absolute_url).netloc != urlparse(base_url).netloc:
                    raise ValueError("SwarmUI returned an output URL on an unexpected host")
                image_response = await client.get(absolute_url)
                image_response.raise_for_status()

            suffix = Path(urlparse(absolute_url).path).suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                suffix = ".png"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"processed{suffix}"
            output_path.write_bytes(image_response.content)
            return ProcessResult(
                status="done",
                output_path=str(output_path),
                metadata={"processor": "swarmui", "scale": scale, "model": model or None},
            )
        except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
            return ProcessResult(status="failed", error=str(exc))

    @staticmethod
    def _extract_image_url(data: object) -> str | None:
        if not isinstance(data, dict):
            return None
        images = data.get("images")
        if not isinstance(images, list) or not images:
            return None
        first = images[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            for key in ("src", "url", "image"):
                value = first.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    @classmethod
    def _extract_gpu(cls, data: object) -> dict:
        if not isinstance(data, dict):
            return {}
        for key in ("gpu", "gpus", "devices", "system"):
            value = data.get(key)
            if isinstance(value, dict):
                return value
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value[0]
        return data

    @staticmethod
    def _first_text(data: dict, *keys: str) -> str | None:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _first_megabytes(data: dict, *keys: str) -> int | None:
        for key in keys:
            value = data.get(key)
            if isinstance(value, int | float):
                return round(value / 1024 / 1024) if value > 1024 * 1024 else round(value)
        return None

    @classmethod
    def _extract_models(cls, data: object) -> list[str]:
        if not isinstance(data, dict):
            return []
        candidates = data.get("models") or data.get("model_list")
        if isinstance(candidates, list):
            return [str(item.get("name") if isinstance(item, dict) else item) for item in candidates]
        for param in data.get("params", []) if isinstance(data.get("params"), list) else []:
            if not isinstance(param, dict) or str(param.get("id", "")).lower() not in {"model", "refinermodel"}:
                continue
            values = param.get("values") or param.get("options") or []
            if isinstance(values, list):
                return [str(item.get("name") if isinstance(item, dict) else item) for item in values]
        return []
