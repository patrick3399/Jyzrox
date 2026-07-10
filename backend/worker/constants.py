"""Shared constants for the worker package."""

import logging

logger = logging.getLogger("worker")

DISK_LOW_KEY = "system:disk_low"

# Max wall-clock duration of a single subscription-group check. Shared so the
# per-subscription check lock TTL can be kept >= this bound (edge case #32):
# a sub check must hold its lock for at least as long as the group run that may
# contain it, otherwise the lock can expire mid-check and allow a duplicate.
GROUP_MAX_DURATION = 1800  # 30 minutes

# Anti-bot pacing: subscription checks must not fire in machine-regular
# patterns (exact cron-minute starts, fixed inter-sub spacing).
GROUP_START_JITTER_MAX_S = 180  # scheduler-triggered group checks start 0..180s late
SUB_CHECK_SPACING_RANGE_S = (2.0, 8.0)  # randomized delay between sub checks

# SAQ kills jobs at Job.timeout, which DEFAULTS TO 10 SECONDS — every enqueue
# of a long job must pass an explicit timeout. Group checks may run
# jitter + GROUP_MAX_DURATION, plus margin.
GROUP_JOB_TIMEOUT = GROUP_MAX_DURATION + GROUP_START_JITTER_MAX_S + 120

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic"}
_VIDEO_EXTS = {".mp4", ".webm", ".mov"}
_MEDIA_EXTS = _IMAGE_EXTS | _VIDEO_EXTS

# Magic byte signatures for image file validation
_IMAGE_MAGIC = {
    b"\xff\xd8\xff": {".jpg", ".jpeg"},  # JPEG
    b"\x89PNG\r\n\x1a\n": {".png"},  # PNG
    b"GIF87a": {".gif"},  # GIF87a
    b"GIF89a": {".gif"},  # GIF89a
    # AVIF/HEIC: ftyp box at bytes 4-7, handled by the special-case check below
}
