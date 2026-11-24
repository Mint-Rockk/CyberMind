import logging
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.db.base import async_session_factory
from app.db.models import CTISource
from app.ingestion.service import create_and_run_job

logger = logging.getLogger(__name__)


class CollectionScheduler:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler()

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def schedule_source(self, source: CTISource) -> None:
        self.remove_source(source.id)
        interval_minutes = (source.configuration or {}).get("schedule_minutes")
        if not source.is_active or not interval_minutes:
            return
        self.scheduler.add_job(
            self._run_source,
            "interval",
            minutes=max(1, int(interval_minutes)),
            args=[source.id],
            id=f"source-{source.id}",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

    def remove_source(self, source_id: UUID) -> None:
        job_id = f"source-{source_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

    async def _run_source(self, source_id: UUID) -> None:
        async with async_session_factory() as session:
            try:
                await create_and_run_job(session, source_id, run_now=True)
            except Exception:
                logger.exception("Scheduled ingestion failed for source %s", source_id)


collection_scheduler = CollectionScheduler()
