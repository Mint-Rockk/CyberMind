from __future__ import annotations

from html import escape
from io import BytesIO
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GeneratedReport, Investigation


REPORT_TYPES = {"executive", "technical", "campaign"}


async def generate_report(
    session: AsyncSession,
    investigation: Investigation,
    *,
    report_type: str,
    report_format: str,
) -> GeneratedReport:
    if report_type not in REPORT_TYPES:
        raise ValueError("Unsupported report type")
    if report_format not in {"pdf", "markdown"}:
        raise ValueError("Unsupported report format")

    markdown = build_report_markdown(investigation, report_type)
    pdf_bytes = _render_pdf(markdown) if report_format == "pdf" else None
    metadata = {
        "generator": "cybermind_deterministic_report_renderer_v1",
        "report_type": report_type,
        "grounding": "investigation_retrieval_only",
        "evidence_count": len(investigation.evidence_references),
        "provider_metadata": investigation.provider_metadata,
        "limitations": _limitations(investigation),
    }
    report = GeneratedReport(
        investigation_id=investigation.id,
        title=f"{report_type.title()} threat intelligence report",
        report_format=report_format,
        content=markdown,
        content_bytes=pdf_bytes,
        generation_metadata=metadata,
    )
    session.add(report)
    await session.flush()
    return report


def build_report_markdown(investigation: Investigation, report_type: str) -> str:
    output = investigation.model_output or {}
    refs = investigation.evidence_references or []
    ref_by_id = {str(ref.get("evidence_id")): ref for ref in refs}
    lines = [
        f"# {report_type.title()} Threat Intelligence Report",
        "",
        f"**Investigation:** {investigation.title}",
        f"**Generated from query:** {investigation.request_query or investigation.objective or 'Not recorded'}",
        "",
    ]
    sections = [
        ("1. Executive summary", "confirmed_facts"),
        ("2. Threat overview", "model_interpretations"),
        ("3. Related CTI reports", None),
        ("4. Threat actors", "actor_analysis"),
        ("5. Malware and tools", "malware_analysis"),
        ("6. Indicators of compromise", None),
        ("7. Vulnerabilities", "vulnerability_analysis"),
        ("8. MITRE ATT&CK techniques", "attack_technique_analysis"),
        ("9. Timeline", "timeline"),
        ("10. Cross-source correlation results", None),
        ("11. Supporting evidence", None),
        ("12. Source references", None),
        ("13. Confidence and limitations", None),
        ("14. Defensive recommendations", "recommendations"),
    ]
    for heading, key in sections:
        lines.extend([f"## {heading}", ""])
        if key:
            lines.extend(_output_items(output.get(key, [])))
        elif heading == "3. Related CTI reports":
            lines.extend(_related_reports(refs))
        elif heading == "6. Indicators of compromise":
            lines.extend(_evidence_by_type(refs, {"extracted_entity", "semantic_chunk"}))
        elif heading == "10. Cross-source correlation results":
            lines.extend(_correlations(refs))
        elif heading == "11. Supporting evidence":
            lines.extend(_supporting_evidence(refs))
        elif heading == "12. Source references":
            lines.extend(_source_references(refs))
        elif heading == "13. Confidence and limitations":
            lines.extend(_limitations_lines(investigation))
        if lines[-1] != "":
            lines.append("")

    lines.extend(["### Inferred information", ""])
    lines.extend(_output_items(output.get("inferred_relationships", [])))
    return "\n".join(lines)


def _output_items(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- No grounded evidence available for this section.", ""]
    return [
        f"- {item.get('text', 'Unspecified claim')} "
        f"(evidence: {', '.join(item.get('evidence_ids', [])) or 'not supplied'})"
        for item in items
    ] + [""]


def _related_reports(refs: list[dict[str, Any]]) -> list[str]:
    reports = [
        f"- {ref.get('document_title') or ref.get('document_id') or 'Untitled report'} "
        f"(evidence: {ref.get('evidence_id', 'unknown')})"
        for ref in refs
        if ref.get("document_id")
    ]
    return reports + [""] if reports else _output_items([])


def _evidence_by_type(refs: list[dict[str, Any]], types: set[str]) -> list[str]:
    items = [
        f"- {ref.get('document_title') or ref.get('evidence_id') or 'Evidence item'} "
        f"(evidence: {ref.get('evidence_id', 'unknown')})"
        for ref in refs
        if ref.get("evidence_type") in types
    ]
    return items + [""] if items else _output_items([])


def _correlations(refs: list[dict[str, Any]]) -> list[str]:
    items = []
    for ref in refs:
        if ref.get("evidence_type") != "stored_correlation":
            continue
        provenance = ref.get("provenance") or {}
        items.append(
            f"- {ref.get('document_title', 'Stored correlation')} "
            f"(evidence: {ref.get('evidence_id', 'unknown')}; "
            f"predictor: {provenance.get('predictor_type', 'not recorded')} "
            f"version {provenance.get('predictor_version', 'not recorded')})"
        )
    return items + [""] if items else _output_items([])


def _supporting_evidence(refs: list[dict[str, Any]]) -> list[str]:
    return [
        f"- [{ref.get('evidence_id', 'unknown')}] "
        f"{ref.get('document_title') or ref.get('source_url') or 'No passage supplied'}"
        for ref in refs
    ] + ([""] if refs else _output_items([]))


def _source_references(refs: list[dict[str, Any]]) -> list[str]:
    items = [
        f"- [{ref.get('evidence_id', 'unknown')}] {ref.get('source_url') or 'Source URL unavailable'}"
        for ref in refs
    ]
    return items + [""] if items else _output_items([])


def _limitations(investigation: Investigation) -> list[str]:
    metadata = investigation.provider_metadata or {}
    limitations = ["Claims are limited to evidence retrieved for this investigation."]
    if not investigation.evidence_references:
        limitations.append("No evidence references were available.")
    if metadata.get("retrieval_warnings"):
        limitations.append(f"Retrieval warnings: {', '.join(metadata['retrieval_warnings'])}.")
    if metadata.get("provider") == "baseline_heuristic":
        limitations.append("Correlation values came from a baseline heuristic, not a trained model.")
    return limitations


def _limitations_lines(investigation: Investigation) -> list[str]:
    return [f"- {item}" for item in _limitations(investigation)] + [""]


def _render_pdf(markdown: str) -> bytes:
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
    )
    styles = getSampleStyleSheet()
    story = []
    for line in markdown.splitlines():
        if line.startswith("# "):
            story.append(Paragraph(escape(line[2:]), styles["Title"]))
        elif line.startswith("## "):
            story.append(Paragraph(escape(line[3:]), styles["Heading2"]))
        elif line.startswith("### "):
            story.append(Paragraph(escape(line[4:]), styles["Heading3"]))
        elif line.startswith("- "):
            story.append(Paragraph(f"&#8226; {escape(line[2:])}", styles["BodyText"]))
        elif line:
            story.append(Paragraph(escape(line), styles["BodyText"]))
        story.append(Spacer(1, 5))
    document.build(story)
    return output.getvalue()
