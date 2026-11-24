"""Synchronize normalized CTI-EACL24 reports through the existing graph pipeline.

This is an orchestration command, not a second graph writer. Database records
are created with the existing normalization and extraction services, and graph
writes are delegated to GraphSynchronizer.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import select

from app.collectors.base import CollectedRecord
from app.db.base import async_session_factory
from app.db.models import (
    CTIDocument,
    CTISource,
    DocumentStatus,
    GraphSyncState,
    RawSourceRecord,
    SourceType,
)
from app.extraction.service import persist_document_entities
from app.graph.client import Neo4jClient
from app.graph.sync import GraphSynchronizer
from app.normalization.service import normalize_record, serialize_raw_content

DATASET = "CTI-EACL24"
DEFAULT_INPUT = Path("data/correlation/processed/normalized_reports.jsonl")
DEFAULT_LOG_ROOT = Path("data/correlation/processed/v3/graph_sync_batches")
SOURCE_BASES = {
    "malpedia": "https://malpedia.caad.fkie.fraunhofer.de/",
    "thaicert": "https://www.thaicert.or.th/en/homepage/",
}


def _reports(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _source_url(report: dict[str, object]) -> str:
    value = str(report.get("source_url") or "").strip()
    if value:
        return value
    vendor = str(report.get("source_vendor") or "").casefold()
    if vendor in SOURCE_BASES:
        return SOURCE_BASES[vendor]
    raise ValueError(f"missing source URL for vendor {vendor!r}")


def _source_name(vendor: str) -> str:
    return f"{DATASET}/{vendor}"


def _source_base_url(report: dict[str, object]) -> str:
    parsed = urlsplit(_source_url(report))
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else _source_url(report)


def _record(report: dict[str, object]) -> CollectedRecord:
    report_id = str(report["report_id"])
    relative_path = str(report["relative_path"])
    return CollectedRecord(
        external_id=report_id,
        title=str(report.get("title") or report.get("original_filename") or report_id),
        content=str(report["normalized_text"]),
        source_url=_source_url(report),
        original_reference=relative_path,
        collected_at=datetime.now(timezone.utc),
        published_at=_parse_datetime(report.get("published_at")),
        payload={
            "dataset": DATASET,
            "dataset_report_id": report_id,
            "relative_path": relative_path,
            "source_vendor": str(report.get("source_vendor") or ""),
        },
        content_type="text/plain",
        metadata={"source_type": SourceType.RESEARCH.value, "dataset": DATASET},
    )


def _document_id(report_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"cybermind:{DATASET}:{report_id}")


def _canonical_key(source_id: UUID, report_id: str) -> str:
    return hashlib.sha256(f"{source_id}:{report_id}".encode()).hexdigest()


async def _ensure_source(
    session,
    report: dict[str, object],
    *,
    dry_run: bool,
) -> CTISource | None:
    vendor = str(report.get("source_vendor") or "").casefold()
    name = _source_name(vendor)
    source = await session.scalar(select(CTISource).where(CTISource.name == name))
    if source is not None or dry_run:
        return source
    source = CTISource(
        name=name,
        source_type=SourceType.RESEARCH,
        base_url=_source_base_url(report),
        reliability_score=None,
        terms_url=None,
        configuration={"dataset": DATASET, "vendor": vendor},
    )
    session.add(source)
    await session.flush()
    return source


async def _create_document(session, report: dict[str, object], source: CTISource) -> CTIDocument:
    record = _record(report)
    normalized = normalize_record(record)
    document_id = _document_id(str(report["report_id"]))
    raw = RawSourceRecord(
        source_id=source.id,
        external_id=record.external_id,
        content_hash=hashlib.sha256(
            serialize_raw_content(record).encode("utf-8")
        ).hexdigest(),
        source_url=record.source_url,
        retrieved_at=record.collected_at,
        payload=record.payload,
        raw_content=serialize_raw_content(record),
        content_type=record.content_type,
    )
    session.add(raw)
    await session.flush()
    document = CTIDocument(
        id=document_id,
        source_id=source.id,
        raw_record_id=raw.id,
        canonical_key=_canonical_key(source.id, str(report["report_id"])),
        title=normalized.original_title,
        normalized_content=normalized.normalized_text,
        original_title=normalized.original_title,
        normalized_title=normalized.normalized_title,
        normalized_text=normalized.normalized_text,
        original_url=normalized.original_url,
        content_hash=normalized.content_hash,
        document_type=normalized.document_type,
        normalization_status="normalized",
        document_status=DocumentStatus.NORMALIZED,
        published_at=normalized.published_at,
        retrieved_at=normalized.collected_at,
        language=normalized.language,
        provenance={
            **normalized.provenance,
            "dataset": DATASET,
            "dataset_report_id": str(report["report_id"]),
            "dataset_relative_path": str(report["relative_path"]),
        },
    )
    session.add(document)
    await session.flush()
    await persist_document_entities(session, document, text=normalized.normalized_text)
    return document


async def synchronize(
    *,
    input_path: Path,
    log_root: Path,
    offset: int,
    limit: int,
    dry_run: bool,
    resync: bool,
) -> dict[str, object]:
    reports = _reports(input_path)[offset : offset + limit]
    log_root.mkdir(parents=True, exist_ok=True)
    log_path = log_root / f"offset-{offset:06d}-limit-{limit:04d}.jsonl"
    settings_module = __import__("app.core.config", fromlist=["get_settings"])
    settings = settings_module.get_settings()
    client = None if dry_run else Neo4jClient(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
        settings.neo4j_database,
    )
    summary = {"selected": len(reports), "created": 0, "synced": 0, "skipped": 0, "failed": 0}
    try:
        async with async_session_factory() as session:
            for report in reports:
                report_id = str(report["report_id"])
                result: dict[str, object] = {"report_id": report_id}
                try:
                    vendor = str(report.get("source_vendor") or "").casefold()
                    source = await _ensure_source(session, report, dry_run=dry_run)
                    if dry_run:
                        result["status"] = "planned"
                        summary["created"] += 1
                    else:
                        assert source is not None
                        canonical = _canonical_key(source.id, report_id)
                        document = await session.scalar(
                            select(CTIDocument).where(CTIDocument.canonical_key == canonical)
                        )
                        if document is None:
                            document = await _create_document(session, report, source)
                            await session.commit()
                            summary["created"] += 1
                            result["document_id"] = str(document.id)
                        state = await session.scalar(
                            select(GraphSyncState).where(
                                GraphSyncState.resource_type == "document",
                                GraphSyncState.resource_id == document.id,
                            )
                        )
                        if state is not None and state.status == "synced" and not resync:
                            summary["skipped"] += 1
                            result.update(status="skipped", document_id=str(document.id))
                        else:
                            assert client is not None
                            synced = await GraphSynchronizer(
                                client, retries=settings.neo4j_sync_retries
                            ).sync_document(session, document.id)
                            await session.commit()
                            summary["synced"] += 1
                            result.update(
                                status="synced",
                                document_id=str(document.id),
                                nodes_written=synced.nodes_written,
                                relationships_written=synced.relationships_written,
                            )
                except Exception as exc:
                    await session.rollback()
                    summary["failed"] += 1
                    result.update(status="failed", reason=str(exc))
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(result, sort_keys=True) + "\n")
    finally:
        if client is not None:
            client.close()
    summary["log"] = str(log_path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--log-root", type=Path, default=DEFAULT_LOG_ROOT)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resync", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(synchronize(
        input_path=args.input,
        log_root=args.log_root,
        offset=args.offset,
        limit=args.limit,
        dry_run=args.dry_run,
        resync=args.resync,
    )), indent=2))


if __name__ == "__main__":
    main()
