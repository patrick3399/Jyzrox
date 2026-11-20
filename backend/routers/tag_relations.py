"""Tag alias and implication endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select

from core.auth import require_auth, require_role
from core.database import async_session
from db.models import Tag, TagAlias, TagImplication
from services.tag_router_helpers import (
    has_cycle as _has_cycle,
)

router = APIRouter()
_admin = require_role("admin")
_member = require_role("member")


# ── Aliases ──────────────────────────────────────────────────────────


class AliasRequest(BaseModel):
    alias_namespace: str
    alias_name: str
    canonical_id: int


@router.get("/aliases")
async def list_aliases(
    tag_id: int | None = None,
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
async def create_alias(req: AliasRequest, _: dict = Depends(_admin)):
    async with async_session() as session:
        tag = (await session.execute(select(Tag.id).where(Tag.id == req.canonical_id))).fetchone()
        if not tag:
            raise HTTPException(status_code=404, detail="Canonical tag not found")

        # Normalize to lowercase so aliases are case-insensitive — edge case #127.
        ns = req.alias_namespace.lower()
        name = req.alias_name.lower()

        # Upsert alias
        existing = (
            await session.execute(
                select(TagAlias).where(
                    TagAlias.alias_namespace == ns,
                    TagAlias.alias_name == name,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.canonical_id = req.canonical_id
        else:
            session.add(
                TagAlias(
                    alias_namespace=ns,
                    alias_name=name,
                    canonical_id=req.canonical_id,
                )
            )
        await session.commit()
    return {"status": "ok"}


@router.delete("/aliases")
async def delete_alias(
    alias_namespace: str = Query(...),
    alias_name: str = Query(...),
    _: dict = Depends(_admin),
):
    async with async_session() as session:
        alias = (
            await session.execute(
                select(TagAlias).where(
                    TagAlias.alias_namespace == alias_namespace.lower(),
                    TagAlias.alias_name == alias_name.lower(),
                )
            )
        ).scalar_one_or_none()
        if alias:
            await session.delete(alias)
            await session.commit()
    return {"status": "ok"}


# ── Implications ─────────────────────────────────────────────────────


class ImplicationRequest(BaseModel):
    antecedent_id: int
    consequent_id: int


@router.get("/implications")
async def list_implications(
    tag_id: int | None = None,
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
async def create_implication(req: ImplicationRequest, _: dict = Depends(_admin)):
    if req.antecedent_id == req.consequent_id:
        raise HTTPException(status_code=400, detail="Cannot imply self")
    async with async_session() as session:
        # Check for circular implication via BFS (detects chains of any length)
        if await _has_cycle(session, req.consequent_id, req.antecedent_id):
            raise HTTPException(status_code=400, detail="Circular implication detected")

        # Check if already exists
        existing = (
            await session.execute(
                select(TagImplication).where(
                    TagImplication.antecedent_id == req.antecedent_id,
                    TagImplication.consequent_id == req.consequent_id,
                )
            )
        ).scalar_one_or_none()
        if not existing:
            session.add(
                TagImplication(
                    antecedent_id=req.antecedent_id,
                    consequent_id=req.consequent_id,
                )
            )
            await session.commit()
    return {"status": "ok"}


@router.delete("/implications")
async def delete_implication(
    antecedent_id: int = Query(...),
    consequent_id: int = Query(...),
    _: dict = Depends(_admin),
):
    async with async_session() as session:
        impl = (
            await session.execute(
                select(TagImplication).where(
                    TagImplication.antecedent_id == antecedent_id,
                    TagImplication.consequent_id == consequent_id,
                )
            )
        ).scalar_one_or_none()
        if impl:
            await session.delete(impl)
            await session.commit()
    return {"status": "ok"}
