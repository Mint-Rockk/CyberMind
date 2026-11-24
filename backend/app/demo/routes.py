from __future__ import annotations

from html import escape
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from app.demo.data import REPORTS, SITES, feed_payload, report_by_id, reports_for_site, site_by_slug

router = APIRouter(tags=["fictional demo sources"])


def _layout(site: dict[str, str], content: str, *, title: str) -> str:
    accent = escape(site["accent"], quote=True)
    name = escape(site["name"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · {name}</title>
<style>
:root{{--bg:#08111f;--panel:#101d2d;--line:#24364b;--text:#e9f1fb;--muted:#9aadc2;--accent:{accent}}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(ellipse at 75% -10%,color-mix(in srgb,var(--accent) 18%,transparent),transparent 42%),var(--bg);color:var(--text);font:16px/1.65 Inter,Segoe UI,Arial,sans-serif}}
a{{color:var(--accent);text-decoration:none}}a:hover{{text-decoration:underline}}header{{border-bottom:1px solid var(--line);background:#091321eF}}.wrap{{max-width:1120px;margin:auto;padding:20px 24px}}.brand{{display:flex;align-items:center;gap:12px;font-weight:800;letter-spacing:.02em}}.mark{{height:36px;width:36px;border:2px solid var(--accent);border-radius:11px;display:grid;place-items:center;color:var(--accent)}}nav{{display:flex;gap:20px;align-items:center}}.top{{display:flex;justify-content:space-between;align-items:center;gap:20px}}.hero{{padding:58px 0 42px}}.eyebrow,.tag{{text-transform:uppercase;letter-spacing:.14em;color:var(--accent);font-size:.72rem;font-weight:700}}h1{{line-height:1.12;font-size:clamp(2rem,5vw,3.8rem);max-width:850px;margin:.7rem 0}}h2{{line-height:1.25}}p{{color:var(--muted)}}.banner{{border:1px solid color-mix(in srgb,var(--accent) 40%,var(--line));border-radius:12px;background:color-mix(in srgb,var(--accent) 9%,var(--panel));padding:12px 16px;color:#d9e7f5}}.controls{{display:flex;gap:12px;flex-wrap:wrap;margin:28px 0}}input,select{{color:var(--text);background:#0b1726;border:1px solid var(--line);padding:11px 13px;border-radius:8px}}input{{flex:1;min-width:220px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:16px}}.card{{border:1px solid var(--line);background:linear-gradient(145deg,#122236,var(--panel));padding:20px;border-radius:14px;display:flex;flex-direction:column;min-height:235px}}.card h2{{font-size:1.17rem;margin:.5rem 0}}.summary{{flex:1}}.meta{{font-size:.84rem;color:var(--muted)}}.pill{{display:inline-flex;border:1px solid var(--line);padding:3px 9px;border-radius:99px;color:var(--muted);font-size:.76rem}}.article{{max-width:850px;margin:36px auto;padding:32px;border:1px solid var(--line);border-radius:16px;background:var(--panel)}}.article-body{{white-space:pre-wrap;color:#d5e0ed}}footer{{border-top:1px solid var(--line);margin-top:60px;color:var(--muted);font-size:.83rem}}code{{color:var(--accent)}}@media(max-width:600px){{.top{{align-items:flex-start;flex-direction:column}}.hero{{padding-top:35px}}.article{{padding:20px}}}}
</style></head><body>
<header><div class="wrap top"><a class="brand" href="/demo-sites/{escape(site['slug'])}/"><span class="mark">C</span>{name}</a>
<nav><a href="/demo-sites/{escape(site['slug'])}/">Latest reports</a><a href="/demo-sites/{escape(site['slug'])}/feed.json">JSON feed</a><a href="/api/v1/sources">CyberMind sources</a></nav></div></header>
<main class="wrap">{content}</main>
<footer><div class="wrap">Fictional CyberMind demonstration publication. Articles and attribution are synthetic, not real-world intelligence.</div></footer>
</body></html>"""


def _site_or_404(slug: str) -> dict[str, str]:
    site = site_by_slug(slug)
    if site is None:
        raise HTTPException(status_code=404, detail="Demo site not found")
    return site


@router.get("/demo-sites", response_class=HTMLResponse, include_in_schema=False)
async def demo_site_directory() -> HTMLResponse:
    cards = "".join(
        f'<article class="card"><span class="eyebrow">{escape(site["category"])}</span>'
        f'<h2><a href="/demo-sites/{escape(site["slug"])}/">{escape(site["name"])}</a></h2>'
        f'<p class="summary">{escape(site["description"])}</p>'
        f'<a href="/demo-sites/{escape(site["slug"])}/feed.json">Open JSON feed</a></article>'
        for site in SITES
    )
    content = (
        '<section class="hero"><p class="eyebrow">CyberMind simulation network</p>'
        '<h1>Five independent desks. One fictional intelligence landscape.</h1>'
        '<p>Browse source publications, inspect their articles, and collect their feeds into CyberMind.</p>'
        '<div class="banner">All names, campaigns, organisations, indicators, and findings on these sites are synthetic demo data.</div>'
        '</section><section class="grid">' + cards + '</section>'
    )
    site = SITES[0]
    return HTMLResponse(_layout(site, content, title="Demo intelligence network"))


@router.get("/demo-sites/{slug}/feed.json")
async def demo_feed(slug: str) -> JSONResponse:
    _site_or_404(slug)
    return JSONResponse(feed_payload(slug))


@router.get("/demo-sites/{slug}/")
async def demo_homepage(
    slug: str,
    q: str | None = Query(default=None, max_length=100),
    category: str | None = Query(default=None, max_length=64),
) -> HTMLResponse:
    site = _site_or_404(slug)
    reports = reports_for_site(slug)
    if q:
        query = q.casefold()
        reports = [
            report for report in reports
            if query in " ".join((report["title"], report["summary"], report["content"])).casefold()
        ]
    if category:
        reports = [report for report in reports if report["category"] == category]
    categories = sorted({report["category"] for report in reports_for_site(slug)})
    options = '<option value="">All categories</option>' + "".join(
        f'<option value="{escape(value)}"{" selected" if value == category else ""}>{escape(value.replace("_", " ").title())}</option>'
        for value in categories
    )
    cards = "".join(
        f'<article class="card"><span class="eyebrow">{escape(report["category"].replace("_", " "))}</span>'
        f'<h2><a href="{escape(report["url"])}">{escape(report["title"])}</a></h2>'
        f'<p class="summary">{escape(report["summary"])}</p>'
        f'<div class="meta">{escape(report["published"][:10])} · {escape(report["source_name"])}</div></article>'
        for report in reports
    )
    if not cards:
        cards = '<p class="banner">No reports match the current search.</p>'
    content = (
        f'<section class="hero"><p class="eyebrow">{escape(site["category"])} · latest intelligence</p>'
        f'<h1>{escape(site["name"])}</h1><p>{escape(site["description"])}</p>'
        '<div class="banner">This publication contains fictional demonstration intelligence only. '
        'It is designed for local ingestion, analyst review, and pipeline testing.</div></section>'
        f'<form class="controls" method="get"><input name="q" value="{escape(q or "", quote=True)}" placeholder="Search reports">'
        f'<select name="category">{options}</select><button type="submit">Filter</button></form>'
        f'<p class="meta">{len(reports)} report(s) · <a href="/demo-sites/{escape(slug)}/feed.json">Machine-readable JSON feed</a></p>'
        f'<section class="grid">{cards}</section>'
    )
    return HTMLResponse(_layout(site, content, title=site["name"]))


@router.get("/demo-sites/{slug}/reports/{report_id}")
async def demo_report_page(slug: str, report_id: str) -> HTMLResponse:
    site = _site_or_404(slug)
    report = report_by_id(report_id)
    if report is None or report["source_slug"] != slug:
        raise HTTPException(status_code=404, detail="Report not found")
    related = "".join(
        f'<li><a href="/demo-sites/{escape(report_by_id(item)["source_slug"])}/reports/{quote(item, safe="")}">'
        f'{escape(report_by_id(item)["title"])}</a></li>'
        for item in report["related_report_ids"]
        if report_by_id(item) is not None
    )
    campaign_label = escape(report["campaign_name"] or "No campaign attribution")
    content = (
        f'<article class="article"><p class="eyebrow">{escape(report["category"].replace("_", " "))} · {escape(report["published"][:10])}</p>'
        f'<h1>{escape(report["title"])}</h1><p>{escape(report["summary"])}</p>'
        f'<span class="pill">{campaign_label}</span>'
        f'<div class="article-body">{escape(report["content"])}</div>'
        f'<h2>Related reading</h2><ul>{related or "<li>No explicit related report references.</li>"}</ul>'
        f'<p class="meta">Stable article ID: <code>{escape(report["id"])}</code> · '
        f'<a href="/demo-sites/{escape(slug)}/feed.json">Source feed</a></p></article>'
    )
    return HTMLResponse(_layout(site, content, title=report["title"]))
