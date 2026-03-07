"""Tag, Alias, and Implication management endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.auth import require_auth
from core.database import async_session
from sqlalchemy import text

router = APIRouter(tags=["tags"])


# ── List tags ────────────────────────────────────────────────────────

@router.get("/")
async def list_tags(
    prefix: Optional[str] = None,
    namespace: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    _: dict = Depends(require_auth),
):
    async with async_session() as session:
        conditions = []
        params: dict = {"limit": limit, "offset": offset}
        if prefix:
            conditions.append("name LIKE :prefix")
            params["prefix"] = f"{prefix}%"
        if namespace:
            conditions.append("namespace = :namespace")
            params["namespace"] = namespace
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        result = await session.execute(
            text(f"SELECT id, namespace, name, count FROM tags {where} ORDER BY count DESC LIMIT :limit OFFSET :offset"),
            params,
        )
        rows = result.fetchall()
        count_result = await session.execute(
            text(f"SELECT COUNT(*) FROM tags {where}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar()
    return {"total": total, "tags": [{"id": r.id, "namespace": r.namespace, "name": r.name, "count": r.count} for r in rows]}


# ── Aliases ──────────────────────────────────────────────────────────

class AliasRequest(BaseModel):
    alias_namespace: str
    alias_name: str
    canonical_id: int


@router.get("/aliases")
async def list_aliases(
    tag_id: Optional[int] = None,
    limit: int = 50,
    _: dict = Depends(require_auth),
):
    async with async_session() as session:
        if tag_id:
            result = await session.execute(
                text("""
                    SELECT a.alias_namespace, a.alias_name, a.canonical_id,
                           t.namespace AS canonical_namespace, t.name AS canonical_name
                    FROM tag_aliases a JOIN tags t ON a.canonical_id = t.id
                    WHERE a.canonical_id = :tid
                    ORDER BY a.alias_name LIMIT :limit
                """),
                {"tid": tag_id, "limit": limit},
            )
        else:
            result = await session.execute(
                text("""
                    SELECT a.alias_namespace, a.alias_name, a.canonical_id,
                           t.namespace AS canonical_namespace, t.name AS canonical_name
                    FROM tag_aliases a JOIN tags t ON a.canonical_id = t.id
                    ORDER BY a.alias_name LIMIT :limit
                """),
                {"limit": limit},
            )
        rows = result.fetchall()
    return [
        {
            "alias_namespace": r.alias_namespace,
            "alias_name": r.alias_name,
            "canonical_id": r.canonical_id,
            "canonical_namespace": r.canonical_namespace,
            "canonical_name": r.canonical_name,
        }
        for r in rows
    ]


@router.post("/aliases")
async def create_alias(req: AliasRequest, _: dict = Depends(require_auth)):
    async with async_session() as session:
        tag = await session.execute(
            text("SELECT id FROM tags WHERE id = :id"), {"id": req.canonical_id}
        )
        if not tag.fetchone():
            raise HTTPException(status_code=404, detail="Canonical tag not found")
        await session.execute(
            text("""
                INSERT INTO tag_aliases (alias_namespace, alias_name, canonical_id)
                VALUES (:ns, :name, :cid)
                ON CONFLICT (alias_namespace, alias_name) DO UPDATE SET canonical_id = :cid
            """),
            {"ns": req.alias_namespace, "name": req.alias_name, "cid": req.canonical_id},
        )
        await session.commit()
    return {"status": "ok"}


@router.delete("/aliases")
async def delete_alias(
    alias_namespace: str = Query(...),
    alias_name: str = Query(...),
    _: dict = Depends(require_auth),
):
    async with async_session() as session:
        await session.execute(
            text("DELETE FROM tag_aliases WHERE alias_namespace = :ns AND alias_name = :name"),
            {"ns": alias_namespace, "name": alias_name},
        )
        await session.commit()
    return {"status": "ok"}


# ── Implications ─────────────────────────────────────────────────────

class ImplicationRequest(BaseModel):
    antecedent_id: int
    consequent_id: int


@router.get("/implications")
async def list_implications(
    tag_id: Optional[int] = None,
    limit: int = 50,
    _: dict = Depends(require_auth),
):
    async with async_session() as session:
        if tag_id:
            result = await session.execute(
                text("""
                    SELECT i.antecedent_id, i.consequent_id,
                           a.namespace AS ant_ns, a.name AS ant_name,
                           c.namespace AS con_ns, c.name AS con_name
                    FROM tag_implications i
                    JOIN tags a ON i.antecedent_id = a.id
                    JOIN tags c ON i.consequent_id = c.id
                    WHERE i.antecedent_id = :tid OR i.consequent_id = :tid
                    ORDER BY a.name LIMIT :limit
                """),
                {"tid": tag_id, "limit": limit},
            )
        else:
            result = await session.execute(
                text("""
                    SELECT i.antecedent_id, i.consequent_id,
                           a.namespace AS ant_ns, a.name AS ant_name,
                           c.namespace AS con_ns, c.name AS con_name
                    FROM tag_implications i
                    JOIN tags a ON i.antecedent_id = a.id
                    JOIN tags c ON i.consequent_id = c.id
                    ORDER BY a.name LIMIT :limit
                """),
                {"limit": limit},
            )
        rows = result.fetchall()
    return [
        {
            "antecedent_id": r.antecedent_id,
            "consequent_id": r.consequent_id,
            "antecedent": f"{r.ant_ns}:{r.ant_name}",
            "consequent": f"{r.con_ns}:{r.con_name}",
        }
        for r in rows
    ]


@router.post("/implications")
async def create_implication(req: ImplicationRequest, _: dict = Depends(require_auth)):
    if req.antecedent_id == req.consequent_id:
        raise HTTPException(status_code=400, detail="Cannot imply self")
    async with async_session() as session:
        # Check for circular implication (simple 1-hop check)
        result = await session.execute(
            text("SELECT 1 FROM tag_implications WHERE antecedent_id = :con AND consequent_id = :ant"),
            {"con": req.consequent_id, "ant": req.antecedent_id},
        )
        if result.fetchone():
            raise HTTPException(status_code=400, detail="Circular implication detected")
        await session.execute(
            text("""
                INSERT INTO tag_implications (antecedent_id, consequent_id)
                VALUES (:ant, :con)
                ON CONFLICT DO NOTHING
            """),
            {"ant": req.antecedent_id, "con": req.consequent_id},
        )
        await session.commit()
    return {"status": "ok"}


@router.delete("/implications")
async def delete_implication(
    antecedent_id: int = Query(...),
    consequent_id: int = Query(...),
    _: dict = Depends(require_auth),
):
    async with async_session() as session:
        await session.execute(
            text("DELETE FROM tag_implications WHERE antecedent_id = :ant AND consequent_id = :con"),
            {"ant": antecedent_id, "con": consequent_id},
        )
        await session.commit()
    return {"status": "ok"}
