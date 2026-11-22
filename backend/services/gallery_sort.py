"""Sort specs, ORDER BY and keyset helpers for gallery lists.

Pure helpers shared by the Library search endpoint (and any list that needs
direction-aware keyset pagination). Order is always ``<expr> <dir>, id <dir>``
so ascending and descending walks are exact reverses of each other except for
the NULL placement defined by each spec's ``nulls`` policy:

- ``natural``: PostgreSQL default (NULL is the largest value), emitted explicitly as
  ``DESC NULLS FIRST`` / ``ASC NULLS LAST`` so SQLite (tests) orders like
  PostgreSQL. These equal the defaults, so the plain btree indexes on
  ``added_at`` / ``content_updated_at`` stay usable (verified with EXPLAIN).
  Never emit ``DESC NULLS LAST`` here: that would make those indexes unusable.
- ``last``: NULL rows (undated / unrated) come at the end in both directions.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import and_, asc, desc, or_
from sqlalchemy.sql.elements import ColumnElement

Direction = Literal["asc", "desc"]
NullPolicy = Literal["natural", "last"]


@dataclass(frozen=True)
class SortSpec:
    key: str
    default_dir: Direction
    nulls: NullPolicy
    kind: Literal["datetime", "int", "text"]


SORT_SPECS: dict[str, SortSpec] = {
    "added_at": SortSpec("added_at", "desc", "natural", "datetime"),
    "content_updated_at": SortSpec("content_updated_at", "desc", "natural", "datetime"),
    "posted_at": SortSpec("posted_at", "desc", "last", "datetime"),
    "rating": SortSpec("rating", "desc", "last", "int"),
    "pages": SortSpec("pages", "desc", "last", "int"),
    "title": SortSpec("title", "asc", "last", "text"),
}

# images.added_at (nullable) for the cross-gallery image browser; not a gallery sort.
IMAGE_ADDED_AT_SPEC = SortSpec("added_at", "desc", "natural", "datetime")


def resolve_direction(spec: SortSpec, raw: str | None) -> Direction:
    """Return ``raw`` when it is a valid direction, else the sort's default."""
    if raw == "asc":
        return "asc"
    if raw == "desc":
        return "desc"
    return spec.default_dir


def order_by(spec: SortSpec, expr, id_col, direction: Direction) -> list:
    """ORDER BY clauses: ``expr <dir>`` (NULL policy applied) then ``id <dir>``."""
    o = asc(expr) if direction == "asc" else desc(expr)
    if spec.nulls == "last":
        # Explicit in both directions: PostgreSQL ASC is already NULLS LAST (same
        # plan), but SQLite (tests) sorts NULLs first on ASC.
        o = o.nulls_last()
    elif direction == "asc":
        o = o.nulls_last()  # PostgreSQL's ASC default
    else:
        o = o.nulls_first()  # PostgreSQL's DESC default
    return [o, asc(id_col) if direction == "asc" else desc(id_col)]


def parse_cursor_value(spec: SortSpec, raw: str | None):
    """Parse a cursor ``v``. None -> None (NULL row). Raises ValueError if malformed.

    Legacy cursors encoded NULL as "": still read as NULL for datetime/int kinds. For
    text, "" is a real empty-string value.
    """
    if raw is None:
        return None
    if raw == "" and spec.kind != "text":
        return None
    if spec.kind == "datetime":
        return datetime.fromisoformat(raw)
    if spec.kind == "int":
        return int(raw)
    return raw


def keyset_after(spec: SortSpec, expr, id_col, direction: Direction, value, cursor_id: int) -> ColumnElement:
    """Rows strictly after (value, cursor_id) in ``order_by(spec, expr, id_col, direction)``."""
    after = (lambda a, b: a > b) if direction == "asc" else (lambda a, b: a < b)
    id_after = after(id_col, cursor_id)
    nulls_at_end = spec.nulls == "last" or direction == "asc"
    if value is None:
        # Cursor sits on a NULL row.
        if nulls_at_end:
            return and_(expr.is_(None), id_after)
        return or_(and_(expr.is_(None), id_after), expr.is_not(None))  # natural + desc: NULLs first
    core = or_(after(expr, value), and_(expr == value, id_after))
    return or_(core, expr.is_(None)) if nulls_at_end else core


def encode_value(value) -> str | None:
    """Cursor ``v`` for a row's sort value (NULL -> JSON null)."""
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)
