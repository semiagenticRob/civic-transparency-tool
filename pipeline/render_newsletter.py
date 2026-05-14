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


def _build_workshop_topic_rows(analysis: WorkshopAnalysis, city_config: dict) -> dict:
    """Pre-compute the Member Preferences table rows for each workshop topic.

    Joins every configured councilmember against the LLM-extracted member_positions
    and the members_present roll call, producing a status per row:

      - "aligned"        — leaned toward an Option N
      - "off_menu"       — proposed a direction not in options[]
      - "no_preference"  — present, spoke or appeared in roll, but did not pick
      - "absent"         — not in members_present and not in member_positions

    Returns {topic_title: [row, ...]} where each row is a plain dict for Jinja.
    """
    council = city_config.get("council_members", []) or []
    council_lookup = _build_council_lookup(city_config)
    present = {n.lower() for n in (analysis.members_present or [])}

    result: dict[str, list[dict]] = {}
    for topic in analysis.workshop_topics:
        pos_by_name = {
            (p.name or "").strip().lower(): p
            for p in topic.member_positions
        }
        rows: list[dict] = []
        for m in council:
            name = (m.get("name") or "").strip()
            if not name:
                continue
            key = name.lower()
            member_dict = council_lookup.get(key, dict(m))
            pos = pos_by_name.get(key)
            if pos is not None:
                rows.append({
                    "name": name,
                    "member": member_dict,
                    "status": pos.status,
                    "option_preference": pos.option_preference,
                    "off_menu_summary": pos.off_menu_summary,
                    "quote": pos.quote,
                })
            elif key in present or not present:
                # If present-roster is empty, default to "spoke or present but
                # didn't weigh in" rather than marking everyone absent.
                rows.append({
                    "name": name,
                    "member": member_dict,
                    "status": "no_preference",
                    "option_preference": "",
                    "off_menu_summary": "",
                    "quote": None,
                })
            else:
                rows.append({
                    "name": name,
                    "member": member_dict,
                    "status": "absent",
                    "option_preference": "",
                    "off_menu_summary": "",
                    "quote": None,
                })
        result[topic.title] = rows
    return result


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

    workshop_topic_rows = (
        _build_workshop_topic_rows(analysis, city_config)
        if isinstance(analysis, WorkshopAnalysis) else {}
    )

    body_html = template.render(
        analysis=analysis,
        city=city_config,
        newsletter=city_config["newsletter"],
        formatted_date=_format_date(meeting_date),
        schedule_portal_url=city_config.get("schedule_portal_url"),
        meeting_video_url=_meeting_video_url(analysis),
        council_by_name=_build_council_lookup(city_config),
        workshop_topic_rows=workshop_topic_rows,
    )

    subject = analysis.lead_headline or f"{city_config['newsletter']['name']} — {meeting_date.strftime('%B %d')}"
    subtitle = _derive_subtitle(analysis)

    return RenderedNewsletter(subject=subject, subtitle=subtitle, body_html=body_html)
