import hashlib
import hmac
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session
from app.db.models import User, UserRole
from app.core.config import get_settings


async def get_current_analyst(
    session: AsyncSession = Depends(get_db_session),
    x_analyst_id: UUID | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> User:
    if isinstance(authorization, str) and authorization.startswith("Bearer "):
        try:
            token_id, signature = authorization[7:].split(".", 1)
            candidate = UUID(token_id)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Invalid bearer token") from exc
        expected = hmac.new(
            get_settings().auth_secret.encode("utf-8"),
            token_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=401, detail="Invalid bearer token")
        x_analyst_id = candidate
    if x_analyst_id is None:
        raise HTTPException(status_code=401, detail="Analyst authentication is required")
    user = await session.get(User, x_analyst_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=403, detail="Active analyst identity required")
    return user


async def require_admin(
    session: AsyncSession = Depends(get_db_session),
    x_analyst_id: UUID | None = Header(default=None),
) -> User:
    user = await get_current_analyst(session, x_analyst_id)
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Administrator permission required")
    return user
