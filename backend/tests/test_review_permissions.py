from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_current_analyst
from app.db.base import Base
from app.db.models import User, UserRole


@pytest.mark.asyncio
async def test_review_identity_requires_active_user():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        with pytest.raises(HTTPException) as missing:
            await get_current_analyst(session, None)
        assert missing.value.status_code == 401
        inactive = User(
            email="inactive@example.test",
            display_name="Inactive",
            role=UserRole.ANALYST,
            is_active=False,
        )
        session.add(inactive)
        await session.flush()
        with pytest.raises(HTTPException) as forbidden:
            await get_current_analyst(session, inactive.id)
        assert forbidden.value.status_code == 403
    await engine.dispose()
