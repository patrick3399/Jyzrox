"""Tag, Alias, and Implication management endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from core.database import async_session
from core.auth import require_auth
from sqlalchemy import text

router = APIRouter(tags=["tags"])

class TagResponse(BaseModel):
    id: int
    namespace: str
    name: str
    count: int

@router.get("/")
async def list_tags(
    prefix: Optional[str] = None,
    limit: int = 20,
    _: dict = Depends(require_auth),
):
    async with async_session() as session:
        if prefix:
            result = await session.execute(
                text("SELECT id, namespace, name, count FROM tags WHERE name LIKE :prefix ORDER BY count DESC LIMIT :limit"),
                {"prefix": f"{prefix}%", "limit": limit}
            )
        else:
            result = await session.execute(
                text("SELECT id, namespace, name, count FROM tags ORDER BY count DESC LIMIT :limit"),
                {"limit": limit}
            )
        rows = result.fetchall()
        return [{"id": r.id, "namespace": r.namespace, "name": r.name, "count": r.count} for r in rows]

class AliasRequest(BaseModel):
    alias_namespace: str
    alias_name: str
    canonical_id: int

@router.post("/alias")
async def create_alias(req: AliasRequest, _: dict = Depends(require_auth)):
    async with async_session() as session:
        await session.execute(
            text("""
                INSERT INTO tag_aliases (alias_namespace, alias_name, canonical_id) 
                VALUES (:ns, :name, :cid) 
                ON CONFLICT DO NOTHING
            """),
            {"ns": req.alias_namespace, "name": req.alias_name, "cid": req.canonical_id}
        )
        await session.commit()
    return {"status": "ok"}

class ImplicationRequest(BaseModel):
    antecedent_id: int
    consequent_id: int

@router.post("/implication")
async def create_implication(req: ImplicationRequest, _: dict = Depends(require_auth)):
    async with async_session() as session:
        await session.execute(
            text("""
                INSERT INTO tag_implications (antecedent_id, consequent_id) 
                VALUES (:ant, :con) 
                ON CONFLICT DO NOTHING
            """),
            {"ant": req.antecedent_id, "con": req.consequent_id}
        )
        await session.commit()
    return {"status": "ok"}
