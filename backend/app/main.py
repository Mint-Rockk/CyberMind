import asyncio
import hashlib
import hmac
import logging
import sys
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from time import monotonic
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.router import router
from app.core.config import get_settings
from app.db.base import async_session_factory
from app.db.models import CTISource
from app.demo.routes import router as demo_router
from app.ingestion.scheduler import collection_scheduler

# psycopg's Windows async implementation requires selector-based I/O.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

settings = get_settings()
settings.validate_production_security()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    collection_scheduler.start()
    try:
        async def schedule_persisted_sources() -> None:
            async with async_session_factory() as session:
                sources = (await session.execute(
                    select(CTISource).where(CTISource.is_active.is_(True))
                )).scalars().all()
                for source in sources:
                    collection_scheduler.schedule_source(source)

        await asyncio.wait_for(schedule_persisted_sources(), timeout=5)
    except (SQLAlchemyError, TimeoutError):
        logger.exception("Unable to load scheduled CTI sources during startup")
    yield
    collection_scheduler.shutdown()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Foundational API for the CyberMind external CTI platform.",
    lifespan=lifespan,
)

_request_windows: dict[str, deque[float]] = defaultdict(deque)


def _valid_bearer_token(value: str | None) -> bool:
    if not value or not value.startswith("Bearer "):
        return False
    try:
        analyst_id, signature = value[7:].split(".", 1)
        UUID(analyst_id)
    except (ValueError, AttributeError):
        return False
    expected = hmac.new(
        settings.auth_secret.encode("utf-8"),
        analyst_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


@app.middleware("http")
async def production_api_guard(request: Request, call_next):
    if settings.app_env.lower() in {"production", "prod"} and request.url.path.startswith("/api/v1/"):
        if request.url.path != "/api/v1/health" and not _valid_bearer_token(
            request.headers.get("authorization")
        ):
            return JSONResponse(status_code=401, content={"detail": "Bearer authentication required"})
        now = monotonic()
        bucket = _request_windows[request.client.host if request.client else "unknown"]
        while bucket and now - bucket[0] >= 60:
            bucket.popleft()
        if len(bucket) >= settings.rate_limit_per_minute:
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
        bucket.append(now)
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(demo_router)


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"service": "cybermind-api", "status": "ok"}
