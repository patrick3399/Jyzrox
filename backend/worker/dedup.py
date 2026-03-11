"""Dedup pipeline — re-exports for backward compatibility."""

from worker.dedup_tier1 import dedup_tier1_job
from worker.dedup_tier2 import dedup_tier2_job
from worker.dedup_tier3 import dedup_tier3_job
from worker.dedup_helpers import _classify_pair, _opencv_pixel_diff, _now_iso

__all__ = [
    "dedup_tier1_job",
    "dedup_tier2_job",
    "dedup_tier3_job",
    "_classify_pair",
    "_opencv_pixel_diff",
    "_now_iso",
]
