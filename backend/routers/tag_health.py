"""Tag health report endpoints."""

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from core.auth import require_role
from core.database import async_session
from core.redis_client import get_redis
from db.models import Tag, TagAlias, TagImplication

router = APIRouter()
_admin = require_role("admin")
_member = require_role("member")


# ── Tag Health Report ──────────────────────────────────────────────────
#
# Detects orphan tags (count==0, not structural), suspected duplicates
# (normalized-name collisions within a namespace), and circular
# implications. See docs/superpowers/specs/2026-07-12-tag-health-report-design.md.

_TAG_HEALTH_IGNORE_REDIS_KEY = "setting:tag_health_ignored"

# Accepted ignore-key formats:
#   orphan:{tag_id}
#   dup:{namespace}:{normalized_name}   (normalized_name may be empty)
#   cycle:{id}(-{id})*
_TAG_HEALTH_IGNORE_KEY_RE = re.compile(r"^(orphan:\d+|dup:[^:]+:[^:]*|cycle:\d+(?:-\d+)*)$")


def _normalize_tag_name_key(namespace: str, normalized_name: str) -> str:
    return f"{namespace}:{normalized_name}"


def _find_implication_cycles(edges: list[tuple[int, int]]) -> list[list[int]]:
    """
    DFS-based cycle detection over the tag_implications graph.

    Returns a list of cycles, each represented as a list of tag ids in
    cyclic edge order, rotated so the smallest id comes first. Each
    distinct cycle (identified by its sorted-id key) is returned once.
    Self-loops (a -> a) are detected as single-node cycles.
    """
    adjacency: dict[int, list[int]] = {}
    for antecedent_id, consequent_id in edges:
        adjacency.setdefault(antecedent_id, []).append(consequent_id)

    visited: set[int] = set()
    seen_keys: set[str] = set()
    cycles: list[list[int]] = []

    def dfs(node: int, stack: list[int], on_stack: set[int]) -> None:
        visited.add(node)
        stack.append(node)
        on_stack.add(node)
        for neighbor in adjacency.get(node, []):
            if neighbor in on_stack:
                idx = stack.index(neighbor)
                cycle = stack[idx:]
                key = "-".join(str(n) for n in sorted(cycle))
                if key not in seen_keys:
                    seen_keys.add(key)
                    min_idx = cycle.index(min(cycle))
                    cycles.append(cycle[min_idx:] + cycle[:min_idx])
            elif neighbor not in visited:
                dfs(neighbor, stack, on_stack)
        stack.pop()
        on_stack.discard(node)

    for start in list(adjacency):
        if start not in visited:
            dfs(start, [], set())

    return cycles


async def _get_tag_health_ignored_keys() -> set[str]:
    """Read the tag-health ignore set from Redis, decoding bytes to str."""
    raw = await get_redis().smembers(_TAG_HEALTH_IGNORE_REDIS_KEY)
    keys: set[str] = set()
    for item in raw or set():
        keys.add(item.decode() if isinstance(item, (bytes, bytearray)) else str(item))
    return keys


@router.get("/health")
async def get_tag_health(
    limit: int = Query(default=200, ge=1, le=2000),
    _: dict = Depends(_admin),
):
    """
    Report orphan tags, suspected duplicate groups, and circular
    implications, filtered against the persisted ignore list.

    `limit` only caps the returned `orphans` list; `orphans_total` reflects
    the full (post-ignore) count. Duplicates and cycles are returned in full
    since they are expected to be small in practice.
    """
    from sqlalchemy import exists as sql_exists

    ignored = await _get_tag_health_ignored_keys()
    ignored_count = 0

    async with async_session() as session:
        # ---- Orphans: count==0, not an alias target, not part of any implication ----
        orphan_stmt = (
            select(Tag.id, Tag.namespace, Tag.name, Tag.count)
            .where(
                Tag.count == 0,
                ~sql_exists().where(TagAlias.canonical_id == Tag.id),
                ~sql_exists().where(
                    or_(TagImplication.antecedent_id == Tag.id, TagImplication.consequent_id == Tag.id)
                ),
            )
            .order_by(Tag.namespace, Tag.name)
        )
        orphan_rows = (await session.execute(orphan_stmt)).all()

        orphans_kept = []
        for r in orphan_rows:
            if f"orphan:{r.id}" in ignored:
                ignored_count += 1
            else:
                orphans_kept.append({"id": r.id, "namespace": r.namespace, "name": r.name, "count": r.count})
        orphans_total = len(orphans_kept)
        orphans = orphans_kept[:limit]

        # ---- Duplicates: same namespace + normalized name, portable across pg/sqlite ----
        normalized_expr = func.replace(func.replace(func.replace(func.lower(Tag.name), "_", ""), "-", ""), " ", "")
        dup_stmt = select(Tag.id, Tag.namespace, Tag.name, Tag.count, normalized_expr.label("norm"))
        dup_rows = (await session.execute(dup_stmt)).all()

        groups: dict[tuple[str, str], list[dict]] = {}
        for r in dup_rows:
            groups.setdefault((r.namespace, r.norm), []).append(
                {"id": r.id, "namespace": r.namespace, "name": r.name, "count": r.count}
            )

        duplicates = []
        for (namespace, norm), tags in groups.items():
            if len(tags) < 2:
                continue
            group_key = _normalize_tag_name_key(namespace, norm)
            if f"dup:{group_key}" in ignored:
                ignored_count += 1
                continue
            duplicates.append({"key": group_key, "tags": sorted(tags, key=lambda t: t["count"], reverse=True)})

        # ---- Implication cycles ----
        edge_rows = (await session.execute(select(TagImplication.antecedent_id, TagImplication.consequent_id))).all()
        raw_cycles = _find_implication_cycles([(r[0], r[1]) for r in edge_rows])

        implication_cycles = []
        if raw_cycles:
            node_ids = {n for cyc in raw_cycles for n in cyc}
            tag_rows = (await session.execute(select(Tag).where(Tag.id.in_(node_ids)))).scalars().all()
            tag_map = {t.id: t for t in tag_rows}
            for cyc in raw_cycles:
                cycle_key = "-".join(str(n) for n in sorted(cyc))
                if f"cycle:{cycle_key}" in ignored:
                    ignored_count += 1
                    continue
                path = [
                    {"id": n, "namespace": tag_map[n].namespace, "name": tag_map[n].name} for n in cyc if n in tag_map
                ]
                implication_cycles.append({"key": cycle_key, "path": path})

    return {
        "orphans": orphans,
        "orphans_total": orphans_total,
        "duplicates": duplicates,
        "implication_cycles": implication_cycles,
        "ignored_count": ignored_count,
    }


class TagHealthIgnoreRequest(BaseModel):
    key: str


@router.post("/health/ignore")
async def ignore_tag_health_item(body: TagHealthIgnoreRequest, _: dict = Depends(_admin)):
    """Add an orphan/duplicate/cycle key to the persisted ignore set."""
    if not _TAG_HEALTH_IGNORE_KEY_RE.match(body.key):
        raise HTTPException(status_code=400, detail="Invalid ignore key format")
    await get_redis().sadd(_TAG_HEALTH_IGNORE_REDIS_KEY, body.key)
    return {"status": "ok"}


@router.delete("/health/ignore")
async def unignore_tag_health_item(key: str = Query(...), _: dict = Depends(_admin)):
    """Remove a key from the tag-health ignore set."""
    await get_redis().srem(_TAG_HEALTH_IGNORE_REDIS_KEY, key)
    return {"status": "ok"}


@router.get("/health/ignored")
async def list_tag_health_ignored(_: dict = Depends(_admin)):
    """List currently ignored tag-health keys (for the UI's ignored/restore view)."""
    keys = await _get_tag_health_ignored_keys()
    return {"keys": sorted(keys)}
