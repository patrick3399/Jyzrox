"""Gallery category registry: the closed set of names local import and manual edits may assign.

``galleries.category`` stays free text. Remote download sources may still write
values outside the registry; only local discovery/import and manual edits are
resolved through it (a miss becomes NULL, i.e. uncategorized).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.local_category_plan import normalize_category
from db.models import GalleryCategory

# Keys of the frontend colour palette (pwa/src/lib/categoryPalette.ts). Order is UI order.
PALETTE: tuple[str, ...] = (
    "pink",
    "orange",
    "yellow",
    "green",
    "sky",
    "blue",
    "purple",
    "red",
    "rose",
    "gray",
    "teal",
    "indigo",
    "emerald",
    "cyan",
)

# (name, palette key, sort_order). Mirrors migrations/versions/0029_gallery_categories.py.
BUILTIN_CATEGORIES: tuple[tuple[str, str, int], ...] = (
    ("Doujinshi", "pink", 1),
    ("Manga", "orange", 2),
    ("Artist CG", "yellow", 3),
    ("Game CG", "green", 4),
    ("Western", "sky", 5),
    ("Non-H", "blue", 6),
    ("Image Set", "purple", 7),
    ("Cosplay", "red", 8),
    ("Asian Porn", "rose", 9),
    ("Misc", "gray", 10),
)

# Names a custom category may not take (lower-case). "__uncategorized__" is the
# library filter's sentinel for "no category".
RESERVED_NAMES: frozenset[str] = frozenset({"__uncategorized__"})

CategoryMap = dict[str, str]


async def load_category_map(db: AsyncSession) -> CategoryMap:
    """Return {lower-case name: registry name} for every registered category."""
    names = (await db.execute(select(GalleryCategory.name))).scalars().all()
    return {name.lower(): name for name in names}


def resolve_with_map(raw: object, category_map: CategoryMap) -> str | None:
    """Map a raw value to its registry name, or None when unusable or unregistered."""
    normalized = normalize_category(raw)
    if normalized is None:
        return None
    return category_map.get(normalized.lower())


async def resolve_category(db: AsyncSession, raw: object) -> str | None:
    """Single-value convenience wrapper; skips the query for unusable input."""
    if normalize_category(raw) is None:
        return None
    return resolve_with_map(raw, await load_category_map(db))
