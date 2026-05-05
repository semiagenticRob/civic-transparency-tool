"""
Render a MeetingAnalysis into an Eyes on Arvada-style HTML newsletter
(inline-styled, Beehiiv-compatible).

Beehiiv strips <style> and <link> tags — every styling decision must be
applied via the `style` attribute on individual elements.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .analyze_meeting import MeetingAnalysis


@dataclass
class RenderedNewsletter:
    subject: str
    subtitle: str
    body_html: str


_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _format_date(d: datetime) -> str:
    """Return e.g. 'TUESDAY, MAY 5, 2026' (no leading zero on day)."""
    # %-d is non-portable; do it manually
    return d.strftime("%A").upper() + ", " + d.strftime("%B").upper() + f" {d.day}, {d.year}"


def render_newsletter(
    analysis: MeetingAnalysis,
    city_config: dict,
    meeting_date: datetime,
) -> RenderedNewsletter:
    """
    Render the analysis to HTML matching the Eyes on Arvada newsletter design.
    """
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    photo_base = city_config["newsletter"]["photo_base_url"].rstrip("/")
    members = city_config.get("council_members", [])

    # Pick lead_decision and lead_workshop for the whip count
    lead_decision = analysis.key_decisions[0] if analysis.key_decisions else None
    lead_workshop = analysis.workshop_topics[0] if analysis.workshop_topics else None

    # Build whip-count rows — one per council member
    whip_rows = []
    for m in members:
        decision_vote = None
        if lead_decision:
            decision_vote = lead_decision.get("votes", {}).get(m["name"])
        workshop_position = None
        if lead_workshop:
            for mp in lead_workshop.get("member_positions", []):
                if mp.get("name") == m["name"]:
                    workshop_position = mp.get("position")
                    break
        whip_rows.append({
            "name": m["name"],
            "title": m["title"],
            "district": m.get("district"),
            "phone": m.get("phone"),
            "photo_url": f"{photo_base}/{m['photo_filename']}" if m.get("photo_filename") else None,
            "decision_vote": decision_vote,
            "workshop_position": workshop_position,
        })

    # Quote allocation: first quote → lead pull quote, subsequent → workshop sections
    quotes = list(analysis.notable_quotes)
    lead_pull_quote = quotes.pop(0) if quotes else None
    workshop_sections = []
    for topic in analysis.workshop_topics:
        workshop_sections.append({
            "topic": topic,
            "pull_quote": quotes.pop(0) if quotes else None,
        })
    remaining_quotes = quotes  # any leftover

    # Note: analysis.editors_note_prompts is intentionally NOT rendered into the
    # newsletter — Eyes on Arvada is positioned as nonpartisan, so editorial
    # commentary doesn't belong in the published email. The field still flows
    # through the dashboard JSON for internal use.

    template = env.get_template("newsletter.html.j2")
    body_html = template.render(
        analysis=analysis,
        city=city_config,
        newsletter=city_config["newsletter"],
        formatted_date=_format_date(meeting_date),
        whip_rows=whip_rows,
        lead_decision=lead_decision,
        lead_pull_quote=lead_pull_quote,
        workshop_sections=workshop_sections,
        remaining_quotes=remaining_quotes,
    )

    subject = analysis.lead_headline or f"{city_config['newsletter']['name']} — {meeting_date.strftime('%B %d')}"
    summary = (analysis.meeting_summary or "").strip()
    if "." in summary:
        subtitle = summary.split(".")[0].strip() + "."
    else:
        subtitle = summary[:200]

    return RenderedNewsletter(subject=subject, subtitle=subtitle, body_html=body_html)
