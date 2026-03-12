"""Audit logging helpers — fire-and-forget, failures never affect the main flow."""

import json
import logging

from sqlalchemy import text

from core.database import async_session

logger = logging.getLogger(__name__)


async def log_audit(
    user_id: int | None,
    action: str,
    detail: str = "",
    ip: str = "",
) -> None:
    """Insert a row into audit_logs.

    Parameters map to the DB schema as follows:
      - ``detail``  → ``details`` (JSONB stored as ``{"message": detail}``)
      - ``ip``      → ``ip_address`` (INET; empty string is stored as NULL)

    This function is fire-and-forget: exceptions are caught and logged as
    warnings so that audit failures never interrupt the request lifecycle.
    """
    try:
        details_json = json.dumps({"message": detail}) if detail else None
        ip_value = ip if ip else None
        async with async_session() as session:
            await session.execute(
                text(
                    "INSERT INTO audit_logs (user_id, action, details, ip_address, created_at) "
                    "VALUES (:uid, :act, :det::jsonb, :ip::inet, now())"
                ),
                {
                    "uid": user_id,
                    "act": action,
                    "det": details_json,
                    "ip": ip_value,
                },
            )
            await session.commit()
    except Exception as exc:
        logger.warning("Audit log failed (action=%s user_id=%s): %s", action, user_id, exc)
