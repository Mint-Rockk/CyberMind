from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session
from app.db.models import GeneratedReport, Investigation
from app.db.schemas import GeneratedReportRequest, GeneratedReportResponse
from app.reports.service import generate_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", response_model=GeneratedReportResponse, status_code=201)
async def create_report(
    request: GeneratedReportRequest,
    session: AsyncSession = Depends(get_db_session),
) -> GeneratedReport:
    investigation = await session.get(Investigation, request.investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    try:
        report = await generate_report(
            session,
            investigation,
            report_type=request.report_type,
            report_format=request.report_format,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(report)
    return report


@router.get("", response_model=list[GeneratedReportResponse])
async def list_reports(
    investigation_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_db_session),
) -> list[GeneratedReport]:
    query = select(GeneratedReport).order_by(GeneratedReport.created_at.desc()).limit(limit)
    if investigation_id:
        query = query.where(GeneratedReport.investigation_id == investigation_id)
    result = await session.execute(query)
    return list(result.scalars().all())


@router.get("/{report_id}", response_model=GeneratedReportResponse)
async def get_report(
    report_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> GeneratedReport:
    report = await session.get(GeneratedReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/{report_id}/download")
async def download_report(
    report_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    report = await session.get(GeneratedReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.report_format != "pdf" or not report.content_bytes:
        raise HTTPException(status_code=409, detail="This report has no PDF download")
    return Response(
        content=report.content_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="cybermind-report-{report.id}.pdf"',
        },
    )
