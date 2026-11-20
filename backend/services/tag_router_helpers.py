"""Shared helpers for the tag routers."""

import base64
import json
from collections import deque

from fastapi import HTTPException
from sqlalchemy import or_, select

from core.utils import escape_like, zh_variants
from db.models import Tag, TagImplication, TagTranslation


def translation_match(q: str, language: str):
    """ILIKE-contains `q` on the translation column.

    For Chinese the DB mixes scripts (imports are simplified, manual edits may
    not be), so also match q's simplified/traditional forms.
    """
    terms = zh_variants(q) if language.startswith("zh") else [q]
    return or_(*(TagTranslation.translation.ilike(f"%{escape_like(t)}%", escape="\\") for t in terms))


def encode_tag_cursor(tag: Tag) -> str:
    payload = {"id": tag.id, "count": tag.count}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_tag_cursor(cursor: str) -> dict:
    try:
        return json.loads(base64.urlsafe_b64decode(cursor + "=="))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


async def has_cycle(session, from_id: int, target_id: int, max_depth: int = 50) -> bool:
    """
    BFS from `from_id` along existing implications.
    Returns True if `target_id` is reachable (i.e. adding target→from would create a cycle).
    Caps traversal at max_depth visited nodes; conservatively returns True if the limit is hit.
    """
    visited: set[int] = set()
    queue: deque[int] = deque([from_id])
    while queue and len(visited) < max_depth:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        if current == target_id:
            return True
        rows = (
            (await session.execute(select(TagImplication.consequent_id).where(TagImplication.antecedent_id == current)))
            .scalars()
            .all()
        )
        queue.extend(r for r in rows if r not in visited)
    # If we hit the limit, conservatively assume a cycle exists
    return len(visited) >= max_depth
