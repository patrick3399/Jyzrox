"""Shared helpers for the dedup pipeline workers."""

from db.models import Blob
import asyncio


_MASK64 = (1 << 64) - 1
_MASK16 = 0xFFFF


def _classify_pair(blob_a: Blob, blob_b: Blob, heuristic_enabled: bool) -> tuple[str, str | None, str | None]:
    """Classify a pair by resolution/file-size heuristics."""
    if not heuristic_enabled:
        return "quality_conflict", None, None

    pixels_a = (blob_a.width or 0) * (blob_a.height or 0)
    pixels_b = (blob_b.width or 0) * (blob_b.height or 0)

    if pixels_a > pixels_b * 1.10:
        return "quality_conflict", blob_a.sha256, "higher_resolution"
    if pixels_b > pixels_a * 1.10:
        return "quality_conflict", blob_b.sha256, "higher_resolution"
    if blob_a.file_size > blob_b.file_size * 1.20:
        return "quality_conflict", blob_a.sha256, "larger_file"
    if blob_b.file_size > blob_a.file_size * 1.20:
        return "quality_conflict", blob_b.sha256, "larger_file"

    return "variant", None, None


def _opencv_pixel_diff(path_a: str, path_b: str) -> tuple[float, str]:
    """Synchronous pixel-level diff using OpenCV. Call via asyncio.to_thread."""
    import cv2
    import numpy as np

    img_a = cv2.imread(path_a, cv2.IMREAD_GRAYSCALE)
    img_b = cv2.imread(path_b, cv2.IMREAD_GRAYSCALE)
    if img_a is None or img_b is None:
        raise ValueError("decode failed")

    img_a = cv2.resize(img_a, (256, 256), interpolation=cv2.INTER_AREA)
    img_b = cv2.resize(img_b, (256, 256), interpolation=cv2.INTER_AREA)

    diff = cv2.absdiff(img_a, img_b).astype(np.float32)
    mean_diff = float(np.mean(diff))
    std_diff = float(np.std(diff))
    similarity = 1.0 - (mean_diff / 255.0)
    diff_type = "compression_noise" if mean_diff < 10 or std_diff <= mean_diff * 1.5 else "localized_diff"
    return similarity, diff_type


def _now_iso() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


class DedupProgress:
    STATUS_KEY  = "dedup:progress:status"
    SIGNAL_KEY  = "dedup:progress:signal"
    CURRENT_KEY = "dedup:progress:current"
    TOTAL_KEY   = "dedup:progress:total"
    TIER_KEY    = "dedup:progress:tier"
    MODE_KEY    = "dedup:progress:mode"
    ALL_KEYS    = [STATUS_KEY, SIGNAL_KEY, CURRENT_KEY, TOTAL_KEY, TIER_KEY, MODE_KEY]

    def __init__(self, r):
        self.r = r
        self._current = 0

    async def start(self, mode: str, total: int, tier: int) -> None:
        pipe = self.r.pipeline()
        pipe.set(self.STATUS_KEY, "running")
        pipe.set(self.MODE_KEY, mode)
        pipe.set(self.TOTAL_KEY, str(total))
        pipe.set(self.TIER_KEY, str(tier))
        pipe.set(self.CURRENT_KEY, "0")
        pipe.delete(self.SIGNAL_KEY)
        await pipe.execute()
        self._current = 0

    async def advance_tier(self, tier: int, total: int) -> None:
        pipe = self.r.pipeline()
        pipe.set(self.TIER_KEY, str(tier))
        pipe.set(self.TOTAL_KEY, str(total))
        pipe.set(self.CURRENT_KEY, "0")
        await pipe.execute()
        self._current = 0

    async def report(self, increment: int = 1) -> None:
        self._current += increment
        await self.r.set(self.CURRENT_KEY, str(self._current))

    async def check_signal(self) -> str | None:
        val = await self.r.getdel(self.SIGNAL_KEY)
        if val is None:
            return None
        return val.decode() if isinstance(val, bytes) else val

    async def wait_for_resume(self) -> bool:
        """Set status=paused and poll until resume or stop signal. Returns True=resume, False=stop."""
        await self.r.set(self.STATUS_KEY, "paused")
        while True:
            await asyncio.sleep(1)
            val = await self.r.getdel(self.SIGNAL_KEY)
            if val is None:
                continue
            signal = val.decode() if isinstance(val, bytes) else val
            if signal == "resume":
                await self.r.set(self.STATUS_KEY, "running")
                return True
            if signal == "stop":
                return False

    async def finish(self) -> None:
        await self.r.delete(*self.ALL_KEYS)
