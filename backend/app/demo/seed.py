from __future__ import annotations

import asyncio
from collections.abc import Callable
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory
from app.db.models import CTISource, SourceType
from app.demo.data import SITES

DEMO_FEED_ROOT = "http://127.0.0.1:8000/demo-sites"


async def seed_demo_sources(
    session_factory: Callable[[], AsyncSession] = async_session_factory,
) -> int:
    async with session_factory() as session:
        sources = list((await session.execute(select(CTISource))).scalars().all())
        for source in sources:
            if not (source.configuration or {}).get("local_demo_feed"):
                source.is_active = False

        for site in SITES:
            source = await session.scalar(
                select(CTISource).where(CTISource.name == site["name"])
            )
            configuration = {
                "local_demo_feed": True,
                "demo_site_slug": site["slug"],
                "demo_category": site["category"],
                "response_path": "items",
                "schedule_minutes": 60,
            }
            if source is None:
                session.add(
                    CTISource(
                        name=site["name"],
                        source_type=SourceType.ADVISORY,
                        base_url=f"{DEMO_FEED_ROOT}/{site['slug']}/feed.json",
                        reliability_score=0.8,
                        is_active=True,
                        configuration=configuration,
                    )
                )
            else:
                source.source_type = SourceType.ADVISORY
                source.base_url = f"{DEMO_FEED_ROOT}/{site['slug']}/feed.json"
                source.reliability_score = 0.8
                source.is_active = True
                source.terms_url = None
                source.configuration = configuration
        await session.commit()
    return len(SITES)


def main() -> None:
    loop = (
        asyncio.SelectorEventLoop()
        if sys.platform == "win32"
        else asyncio.new_event_loop()
    )
    asyncio.set_event_loop(loop)
    try:
        count = loop.run_until_complete(seed_demo_sources())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
    print(f"Configured {count} fictional local CTI sources; existing report and graph data was preserved.")


if __name__ == "__main__":
    main()
