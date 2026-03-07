"""Session-based authentication (Redis)."""

from fastapi import Cookie, HTTPException, status

from core.redis_client import get_redis


async def require_auth(
    vault_session: str | None = Cookie(default=None),
) -> dict:
    """FastAPI dependency: require valid session cookie."""
    if not vault_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        user_id_str, token = vault_session.split(":", 1)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    session_data = await get_redis().get(f"session:{user_id_str}:{token}")
    if not session_data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    return {"user_id": int(user_id_str)}
