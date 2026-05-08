"""User CRUD endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.db import Pool, get_pool
from app.db.users.repository import get_or_create_user, get_user_by_oid, get_all_users
from app.dependencies import CurrentUser, get_admin_user

router = APIRouter(prefix="/users", tags=["users"])


class UpsertUserRequest(BaseModel):
    azure_oid: str
    email: str
    display_name: str | None = None


def _serialize_user(user) -> dict:
    d = asdict(user)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


@router.post("")
async def upsert_user(body: UpsertUserRequest):
    """Create or update a user."""
    pool: Pool = await get_pool()
    user = await get_or_create_user(
        pool, azure_oid=body.azure_oid, email=body.email, display_name=body.display_name,
    )
    return _serialize_user(user)


@router.get("/{azure_oid}")
async def get_user(azure_oid: str):
    """Get a user by azure_oid."""
    pool: Pool = await get_pool()
    user = await get_user_by_oid(pool, azure_oid)
    if not user:
        return {"error": "User not found"}, 404
    return _serialize_user(user)


@router.get("")
async def list_users(_: CurrentUser = Depends(get_admin_user)):
    """List all users (admin only)."""
    pool: Pool = await get_pool()
    users = await get_all_users(pool)
    return {"users": [_serialize_user(u) for u in users]}
