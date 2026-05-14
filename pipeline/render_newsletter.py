"""
Render a MeetingAnalysis into an Eyes on Arvada-style HTML newsletter
(inline-styled, Beehiiv-compatible).

Routes to one of three Jinja templates based on analysis.meeting_type:
  - newsletter_business.html.j2
  - newsletter_workshop.html.j2
  - newsletter_study.html.j2

Beehiiv strips <style> and <link> tags — every styling decision must be
applied via the `style` attribute on individual elements.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .analyze_meeting import (
    BusinessAnalysis,
    MeetingAnalysis,
    StudyAnalysis,
    WorkshopAnalysis,
)


@dataclass
class RenderedNewsletter:
    subject: str
    subtitle: str
    body_html: str


_TEMPLATE_DIR = Path(__file__).parent / "templates"

_TEMPLATE_BY_TYPE = {
    "business": "newsletter_business.html.j2",
    "workshop": "newsletter_workshop.html.j2",
    "study_session": "newsletter_study.html.j2",
}


def _format_date(d: datetime) -> str:
    """Return e.g. 'TUESDAY, MAY 5, 2026' (no leading zero on day)."""
    return d.strftime("%A").upper() + ", " + d.strftime("%B").upper() + f" {d.day}, {d.year}"


def _derive_subtitle(analysis: MeetingAnalysis) -> str:
    summary = (analysis.meeting_summary or "").strip()
    if isinstance(analysis, BusinessAnalysis) and analysis.tonight_at_a_glance.synopsis:
        return analysis.tonight_at_a_glance.synopsis.strip()[:200]
    if "." in summary:
        return summary.split(".")[0].strip() + "."
    return summary[:200]


def _build_council_lookup(city_config: dict) -> dict:
    """Map normalized councilmember name → enriched member dict (with computed photo_url).

    Templates look members up by `pos.name` to attach a headshot, title, district,
    and phone alongside the LLM-extracted preference + quote. Returns an empty
    dict when no photo_base_url is configured.
    """
    base = (city_config.get("newsletter") or {}).get("photo_base_url") or ""
    lookup: dict[str, dict] = {}
    for m in city_config.get("council_members", []) or []:
        name = (m.get("name") or "").strip()
        if not name:
            continue
        photo_url = ""
        fname = m.get("photo_filename")
        if base and fname:
            photo_url = f"{base.rstrip('/')}/{fname}"
        enriched = dict(m)
        enriched["photo_url"] = photo_url
        lookup[name.lower()] = enriched
    return lookup


def _meeting_video_url(analysis: MeetingAnalysis) -> str | None:
    """Best-effort: pull a meeting video URL from any quote that carries one."""
    quotes: list = []
    if isinstance(analysis, BusinessAnalysis):
        for h in analysis.public_hearings:
            quotes.extend(h.city_staff_commentary)
            quotes.extend(h.outside_party_commentary)
            quotes.extend(h.councilmember_commentary)
            quotes.extend(h.public_commentary)
        quotes.extend(analysis.non_scheduled_public_comment)
        for p in analysis.presentations:
            quotes.extend(p.presenter_quotes)
    elif isinstance(analysis, WorkshopAnalysis):
        for t in analysis.workshop_topics:
            for mp in t.member_positions:
                quotes.append(mp.quote)
    elif isinstance(analysis, StudyAnalysis):
        for b in analysis.briefings:
            quotes.extend(b.presenter_quotes)

    for q in quotes:
        url = getattr(q, "video_url", None)
        if url:
            # Strip the &t= fragment to get a meeting-level URL
            return url.split("&t=")[0]
    return None


def render_newsletter(
    analysis: MeetingAnalysis,
    city_config: dict,
    meeting_date: datetime,
) -> RenderedNewsletter:
    """Render the analysis to HTML, dispatching by meeting_type."""
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    template_name = _TEMPLATE_BY_TYPE.get(analysis.meeting_type)
    if not template_name:
        raise ValueError(
            f"No template registered for meeting_type {analysis.meeting_type!r}; "
            f"expected one of {list(_TEMPLATE_BY_TYPE)}"
        )

    template = env.get_template(template_name)

    body_html = template.render(
        analysis=analysis,
        city=city_config,
        newsletter=city_config["newsletter"],
        formatted_date=_format_date(meeting_date),
        schedule_portal_url=city_config.get("schedule_portal_url"),
        meeting_video_url=_meeting_video_url(analysis),
        council_by_name=_build_council_lookup(city_config),
    )

    subject = analysis.lead_headline or f"{city_config['newsletter']['name']} — {meeting_date.strftime('%B %d')}"
    subtitle = _derive_subtitle(analysis)

    return RenderedNewsletter(subject=subject, subtitle=subtitle, body_html=body_html)
