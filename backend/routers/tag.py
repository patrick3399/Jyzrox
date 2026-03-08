"""Tag, Alias, and Implication management endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, desc, or_

from core.auth import require_auth
from core.database import async_session
from db.models import Tag, TagAlias, TagImplication

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
    filters = []
    if prefix:
        filters.append(Tag.name.like(f"{prefix}%"))
    if namespace:
        filters.append(Tag.namespace == namespace)

    async with async_session() as session:
        data_query = (
            select(Tag)
            .where(*filters)
            .order_by(desc(Tag.count))
            .limit(limit)
            .offset(offset)
        )
        rows = (await session.execute(data_query)).scalars().all()

        count_query = select(func.count()).select_from(Tag).where(*filters)
        total = (await session.execute(count_query)).scalar()

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
        query = (
            select(
                TagAlias.alias_namespace,
                TagAlias.alias_name,
                TagAlias.canonical_id,
                Tag.namespace.label("canonical_namespace"),
                Tag.name.label("canonical_name"),
            )
            .join(Tag, TagAlias.canonical_id == Tag.id)
            .order_by(TagAlias.alias_name)
            .limit(limit)
        )
        if tag_id:
            query = query.where(TagAlias.canonical_id == tag_id)

        rows = (await session.execute(query)).all()

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
        tag = (await session.execute(
            select(Tag.id).where(Tag.id == req.canonical_id)
        )).fetchone()
        if not tag:
            raise HTTPException(status_code=404, detail="Canonical tag not found")

        # Upsert alias
        existing = (await session.execute(
            select(TagAlias).where(
                TagAlias.alias_namespace == req.alias_namespace,
                TagAlias.alias_name == req.alias_name,
            )
        )).scalar_one_or_none()

        if existing:
            existing.canonical_id = req.canonical_id
        else:
            session.add(TagAlias(
                alias_namespace=req.alias_namespace,
                alias_name=req.alias_name,
                canonical_id=req.canonical_id,
            ))
        await session.commit()
    return {"status": "ok"}


@router.delete("/aliases")
async def delete_alias(
    alias_namespace: str = Query(...),
    alias_name: str = Query(...),
    _: dict = Depends(require_auth),
):
    async with async_session() as session:
        alias = (await session.execute(
            select(TagAlias).where(
                TagAlias.alias_namespace == alias_namespace,
                TagAlias.alias_name == alias_name,
            )
        )).scalar_one_or_none()
        if alias:
            session.delete(alias)
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
    ant = Tag.__table__.alias("ant")
    con = Tag.__table__.alias("con")

    async with async_session() as session:
        query = (
            select(
                TagImplication.antecedent_id,
                TagImplication.consequent_id,
                ant.c.namespace.label("ant_ns"),
                ant.c.name.label("ant_name"),
                con.c.namespace.label("con_ns"),
                con.c.name.label("con_name"),
            )
            .join(ant, TagImplication.antecedent_id == ant.c.id)
            .join(con, TagImplication.consequent_id == con.c.id)
            .order_by(ant.c.name)
            .limit(limit)
        )
        if tag_id:
            query = query.where(
                or_(
                    TagImplication.antecedent_id == tag_id,
                    TagImplication.consequent_id == tag_id,
                )
            )

        rows = (await session.execute(query)).all()

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
        result = (await session.execute(
            select(TagImplication).where(
                TagImplication.antecedent_id == req.consequent_id,
                TagImplication.consequent_id == req.antecedent_id,
            )
        )).scalar_one_or_none()
        if result:
            raise HTTPException(status_code=400, detail="Circular implication detected")

        # Check if already exists
        existing = (await session.execute(
            select(TagImplication).where(
                TagImplication.antecedent_id == req.antecedent_id,
                TagImplication.consequent_id == req.consequent_id,
            )
        )).scalar_one_or_none()
        if not existing:
            session.add(TagImplication(
                antecedent_id=req.antecedent_id,
                consequent_id=req.consequent_id,
            ))
            await session.commit()
    return {"status": "ok"}


@router.delete("/implications")
async def delete_implication(
    antecedent_id: int = Query(...),
    consequent_id: int = Query(...),
    _: dict = Depends(require_auth),
):
    async with async_session() as session:
        impl = (await session.execute(
            select(TagImplication).where(
                TagImplication.antecedent_id == antecedent_id,
                TagImplication.consequent_id == consequent_id,
            )
        )).scalar_one_or_none()
        if impl:
            session.delete(impl)
            await session.commit()
    return {"status": "ok"}
