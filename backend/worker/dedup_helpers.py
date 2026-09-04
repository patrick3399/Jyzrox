"""Shared helpers for the dedup pipeline workers."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import case, select
from sqlalchemy.orm import aliased

from db.models import Blob, Image

_MASK64 = (1 << 64) - 1
_MASK16 = 0xFFFF
DEDUP_SCAN_VERSION = 1
AUTO_CANDIDATE_RELATIONSHIPS = (
    "needs_context",
    "needs_t2",
    "needs_review",
    "same_gallery_only",
    "quality_conflict",
    "variant",
    "needs_t3",
)


def _hamming_distance(a: int, b: int) -> int:
    return ((a & _MASK64) ^ (b & _MASK64)).bit_count()


@dataclass
class _BKNode:
    phash: int
    items: list = field(default_factory=list)
    children: dict[int, _BKNode] = field(default_factory=dict)


class PhashBKTree:
    """Metric index for exact Hamming-radius pHash candidate queries.

    Equal hashes share one node rather than forming a distance-zero chain. This
    keeps large exact-pHash groups bounded and makes the initial scan practical.
    """

    def __init__(self, items: Iterable = ()) -> None:
        self.root: _BKNode | None = None
        for item in items:
            self.add(item)

    def add(self, item) -> None:
        phash = int(item.phash_int) & _MASK64
        if self.root is None:
            self.root = _BKNode(phash=phash, items=[item])
            return

        node = self.root
        while True:
            distance = _hamming_distance(phash, node.phash)
            if distance == 0:
                node.items.append(item)
                return
            child = node.children.get(distance)
            if child is None:
                node.children[distance] = _BKNode(phash=phash, items=[item])
                return
            node = child

    def query(self, phash: int, threshold: int):
        if self.root is None:
            return
        target = int(phash) & _MASK64
        stack = [self.root]
        while stack:
            node = stack.pop()
            distance = _hamming_distance(target, node.phash)
            if distance <= threshold:
                for item in node.items:
                    yield item, distance
            lower = max(1, distance - threshold)
            upper = distance + threshold
            for edge in range(lower, upper + 1):
                child = node.children.get(edge)
                if child is not None:
                    stack.append(child)


def _scan_indexed_candidates(index: PhashBKTree, blob, threshold: int):
    """Yield canonical candidates for one blob from the metric index."""
    for candidate, distance in index.query(blob.phash_int, threshold):
        if candidate.sha256 == blob.sha256:
            continue
        yield candidate, distance


async def _pair_context_scope(session, sha_a: str, sha_b: str) -> str:
    """Classify where a similar blob pair occurs in the gallery graph."""
    image_a = aliased(Image)
    image_b = aliased(Image)
    ref_a = select(image_a.id).where(image_a.blob_sha256 == sha_a).limit(1).exists()
    ref_b = select(image_b.id).where(image_b.blob_sha256 == sha_b).limit(1).exists()
    same_gallery = (
        select(image_a.id)
        .join(image_b, image_b.gallery_id == image_a.gallery_id)
        .where(image_a.blob_sha256 == sha_a, image_b.blob_sha256 == sha_b)
        .limit(1)
        .exists()
    )
    cross_gallery = (
        select(image_a.id)
        .join(image_b, image_b.gallery_id != image_a.gallery_id)
        .where(image_a.blob_sha256 == sha_a, image_b.blob_sha256 == sha_b)
        .limit(1)
        .exists()
    )
    scope = (
        await session.execute(
            select(
                case(
                    ((~ref_a) | (~ref_b), "unreferenced"),
                    (same_gallery & cross_gallery, "mixed"),
                    (cross_gallery, "cross_gallery"),
                    (same_gallery, "same_gallery_only"),
                    else_="unreferenced",
                )
            )
        )
    ).scalar()

    # Preserve compatibility with lightweight mocked sessions used by focused
    # worker tests while production queries always return the string values.
    if scope is True:
        return "same_gallery_only"
    if scope is False:
        return "cross_gallery"
    return str(scope)


async def _pair_context_scopes(session, pairs) -> dict[int, str]:
    """Classify a batch of pairs with one occurrence query.

    Context is based only on the set of galleries referencing each blob, so
    loading ``(blob_sha256, gallery_id)`` once avoids four EXISTS probes and a
    transaction per relationship.
    """
    pair_list = list(pairs)
    shas = {sha for pair in pair_list for sha in (pair.sha_a, pair.sha_b)}
    if not shas:
        return {}
    rows = (
        await session.execute(select(Image.blob_sha256, Image.gallery_id).where(Image.blob_sha256.in_(shas)).distinct())
    ).all()
    galleries: dict[str, set[int]] = {sha: set() for sha in shas}
    for sha, gallery_id in rows:
        galleries.setdefault(sha, set()).add(int(gallery_id))

    scopes: dict[int, str] = {}
    for pair in pair_list:
        galleries_a = galleries.get(pair.sha_a, set())
        galleries_b = galleries.get(pair.sha_b, set())
        if not galleries_a or not galleries_b:
            scope = "unreferenced"
        else:
            has_same = bool(galleries_a & galleries_b)
            has_cross = any(a != b for a in galleries_a for b in galleries_b)
            if has_same and has_cross:
                scope = "mixed"
            elif has_cross:
                scope = "cross_gallery"
            else:
                scope = "same_gallery_only"
        scopes[int(pair.id)] = scope
    return scopes


def _scan_candidates(blobs, i, threshold):
    """Yield ``(b, dist)`` for every ``j > i`` whose pHash is within ``threshold``
    Hamming distance of ``blobs[i]``, using a q0/q1 pigeonhole prefilter.

    Iterates by index and never slices ``blobs``. The previous Tier-1 form
    (``for b in blobs[i + 1:]``) allocated a fresh copy of the entire blob list
    on every outer iteration — O(n^2) allocation churn that fragmented the worker
    heap and prevented glibc from returning memory to the OS. ``blobs`` must be
    ordered by ``sha256`` ascending so callers can treat ``blobs[i]`` as ``sha_a``.
    """
    a = blobs[i]
    a_q0 = (a.phash_q0 or 0) & _MASK16
    a_q1 = (a.phash_q1 or 0) & _MASK16
    a_phash = a.phash_int & _MASK64
    total = len(blobs)
    for j in range(i + 1, total):
        b = blobs[j]
        q01_dist = bin(a_q0 ^ ((b.phash_q0 or 0) & _MASK16)).count("1") + bin(
            a_q1 ^ ((b.phash_q1 or 0) & _MASK16)
        ).count("1")
        if q01_dist > threshold:
            continue

        dist = _hamming_distance(a_phash, b.phash_int)
        if dist > threshold:
            continue

        yield b, dist


def _classify_pair(blob_a: Blob, blob_b: Blob, heuristic_enabled: bool) -> tuple[str, str | None, str | None]:
    """Classify a pair by resolution/file-size heuristics."""
    if not heuristic_enabled:
        return "needs_review", None, None

    pixels_a = (blob_a.width or 0) * (blob_a.height or 0)
    pixels_b = (blob_b.width or 0) * (blob_b.height or 0)

    if pixels_a > pixels_b * 1.10:
        return "quality_conflict", blob_a.sha256, "higher_resolution"
    if pixels_b > pixels_a * 1.10:
        return "quality_conflict", blob_b.sha256, "higher_resolution"
    # Encoders and formats have very different size/quality trade-offs. File
    # size is only a weak suggestion when both blobs use the same format.
    extension_a = (getattr(blob_a, "extension", None) or "").lower()
    extension_b = (getattr(blob_b, "extension", None) or "").lower()
    size_a = getattr(blob_a, "file_size", None) or 0
    size_b = getattr(blob_b, "file_size", None) or 0
    if extension_a and extension_a == extension_b:
        if size_a > size_b * 1.20:
            return "quality_conflict", blob_a.sha256, "larger_file"
        if size_b > size_a * 1.20:
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
    STATUS_KEY = "dedup:progress:status"
    SIGNAL_KEY = "dedup:progress:signal"
    CURRENT_KEY = "dedup:progress:current"
    TOTAL_KEY = "dedup:progress:total"
    TIER_KEY = "dedup:progress:tier"
    MODE_KEY = "dedup:progress:mode"
    LAST_STATUS_KEY = "dedup:progress:last_status"
    LAST_STARTED_KEY = "dedup:progress:last_started"
    LAST_FINISHED_KEY = "dedup:progress:last_finished"
    LAST_ERROR_KEY = "dedup:progress:last_error"
    ALL_KEYS = [STATUS_KEY, SIGNAL_KEY, CURRENT_KEY, TOTAL_KEY, TIER_KEY, MODE_KEY]

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
        pipe.set(self.LAST_STARTED_KEY, _now_iso())
        pipe.set(self.LAST_STATUS_KEY, "running")
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

    async def finish(self, status: str = "completed", error: str | None = None) -> None:
        pipe = self.r.pipeline()
        pipe.set(self.LAST_STATUS_KEY, status)
        pipe.set(self.LAST_FINISHED_KEY, _now_iso())
        if error:
            pipe.set(self.LAST_ERROR_KEY, error[:1000])
        else:
            pipe.delete(self.LAST_ERROR_KEY)
        await pipe.execute()
        await self.r.delete(*self.ALL_KEYS)

    async def fail(self, error: str) -> None:
        await self.finish("failed", error)
