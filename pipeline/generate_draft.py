"""
Markdown summary of a MeetingAnalysis — used by the manual CLI as a quick
human-readable preview. The canonical newsletter output is HTML rendered by
pipeline/render_newsletter.py; this module is for skim-readable drafts.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from .analyze_meeting import (
    BusinessAnalysis,
    MeetingAnalysis,
    StudyAnalysis,
    WorkshopAnalysis,
)


def _md_quote(speaker: str, text: str) -> str:
    return f"> \"{text}\"\n> — *{speaker}*"


def _business_md(analysis: BusinessAnalysis) -> str:
    lines: list[str] = []
    if analysis.tonight_at_a_glance.synopsis:
        lines.append("## Tonight at a Glance")
        lines.append(analysis.tonight_at_a_glance.synopsis)
        lines.append("")
        for h in analysis.tonight_at_a_glance.highlights:
            lines.append(f"- {h}")
        lines.append("")

    if analysis.presentations:
        lines.append("## Presentations")
        for p in analysis.presentations:
            lines.append(f"### {p.topic}")
            if p.presenter_name:
                lines.append(f"*Presented by {p.presenter_name} — {p.presenter_role}*\n")
            for para in p.prose_paragraphs:
                lines.append(para + "\n")
        lines.append("")

    if analysis.non_scheduled_public_comment:
        lines.append("## Public Comment · Not on the Agenda")
        for q in analysis.non_scheduled_public_comment:
            lines.append(_md_quote(q.speaker, q.text))
            lines.append("")

    if analysis.consent_agenda:
        lines.append("## Consent Agenda")
        for item in analysis.consent_agenda:
            lines.append(f"**{item.official_title}** — *{item.vote_tally}* {item.dissent_excused}\n")
            if item.plain_english_summary:
                lines.append(f"*{item.plain_english_summary}*\n")

    if analysis.resolutions:
        lines.append("## Resolutions")
        for item in analysis.resolutions:
            lines.append(f"**{item.official_title}** — *{item.vote_tally}* {item.dissent_excused}\n")
            if item.plain_english_summary:
                lines.append(f"*{item.plain_english_summary}*\n")

    if analysis.ordinances:
        lines.append("## Ordinances")
        for ord_item in analysis.ordinances:
            reading = {1: "First reading", 2: "Second reading", 3: "Third reading (final)"}.get(ord_item.reading_number, "Reading")
            lines.append(f"**{ord_item.official_title}** ({reading}) — *{ord_item.vote_tally}* {ord_item.dissent_excused}\n")
            if ord_item.plain_english_summary:
                lines.append(f"*{ord_item.plain_english_summary}*\n")
            if ord_item.coming_back_at:
                lines.append(f"*Coming back: {ord_item.coming_back_at}*\n")

    for h in analysis.public_hearings:
        lines.append("## Public Hearing")
        if h.what_is_being_heard:
            lines.append(h.what_is_being_heard + "\n")
        for section_label, quotes in [
            ("From the City", h.city_staff_commentary),
            ("From Outside Parties", h.outside_party_commentary),
            ("From Council", h.councilmember_commentary),
            ("From the Public", h.public_commentary),
        ]:
            if quotes:
                lines.append(f"### {section_label}")
                for q in quotes:
                    lines.append(_md_quote(q.speaker, q.text) + "\n")
        if h.vote_breakdown.tally:
            lines.append(f"**The Vote:** {h.vote_breakdown.result} {h.vote_breakdown.tally}\n")
        if h.whip_count:
            lines.append("**Whip count:**")
            for m in h.whip_count:
                emoji = {"Yes": "✅", "No": "❌", "Abstain": "⚪", "Excused": "—"}.get(m.vote, "•")
                lines.append(f"- {emoji} {m.name}: {m.vote}" + (f" — {m.rationale}" if m.rationale else ""))
            lines.append("")

    return "\n".join(lines)


def _workshop_md(analysis: WorkshopAnalysis) -> str:
    lines: list[str] = []
    for topic in analysis.workshop_topics:
        lines.append(f"## Workshop · {topic.title}")
        if topic.tagline:
            lines.append(f"**{topic.tagline}**\n")
        if topic.lede:
            lines.append(topic.lede + "\n")

        if topic.options:
            lines.append("### Options at a glance")
            for opt in topic.options:
                lines.append(f"- **Option {opt.number} — {opt.label}** ({opt.cost})")
                lines.append(f"  {opt.summary}")
            lines.append("")

        if topic.member_positions:
            lines.append("### Member Preferences — Not a Vote")
            for pos in topic.member_positions:
                lines.append(f"- **{pos.name}** leans toward {pos.option_preference}")
                if pos.quote and pos.quote.text:
                    lines.append(f"  > \"{pos.quote.text}\"")
            lines.append("")

        if topic.feeds_into:
            lines.append(f"*What this informs:* {topic.feeds_into}\n")

    return "\n".join(lines)


def _study_md(analysis: StudyAnalysis) -> str:
    lines: list[str] = []
    for briefing in analysis.briefings:
        lines.append(f"## Briefing · {briefing.topic}")
        if briefing.presenter_name:
            lines.append(f"*Presented by {briefing.presenter_name} — {briefing.presenter_role}*\n")
        for para in briefing.prose_paragraphs:
            lines.append(para + "\n")
        if briefing.external_resources:
            lines.append("**Sources & Resources:**")
            for r in briefing.external_resources:
                if r.url:
                    lines.append(f"- [{r.title}]({r.url})")
                else:
                    lines.append(f"- {r.title}")
            lines.append("")
        if briefing.presenter_quotes:
            for q in briefing.presenter_quotes[:2]:
                lines.append(_md_quote(q.speaker, q.text) + "\n")

    if analysis.questions_raised:
        lines.append("## Questions Council Raised")
        for q in analysis.questions_raised:
            lines.append(f"- {q}")
        lines.append("")

    return "\n".join(lines)


def generate_draft(
    analysis: MeetingAnalysis,
    city_config: dict,
    meeting_date: Optional[datetime] = None,
    output_dir: Optional[Path] = None,
) -> str:
    """
    Generate a Markdown summary from a typed MeetingAnalysis.

    Returns the draft as a string and optionally saves it to output_dir.
    """
    date_str = (meeting_date or datetime.now()).strftime("%B %d, %Y")
    city_name = city_config["name"]
    state = city_config["state"]
    meeting_type_label = {
        "business": "City Council Business Meeting",
        "workshop": "City Council Workshop",
        "study_session": "City Council Study Session",
    }.get(analysis.meeting_type, "City Council Meeting")

    header = (
        f"# {city_name} {meeting_type_label} | {date_str}\n\n"
        f"*{analysis.meeting_purpose_blurb}*\n\n"
        f"{analysis.meeting_summary}\n\n"
        f"---\n\n"
    )

    if isinstance(analysis, BusinessAnalysis):
        body = _business_md(analysis)
    elif isinstance(analysis, WorkshopAnalysis):
        body = _workshop_md(analysis)
    elif isinstance(analysis, StudyAnalysis):
        body = _study_md(analysis)
    else:
        body = "_Unknown meeting type._"

    footer = (
        f"\n---\n\n"
        f"*Independent, AI-assisted civic journalism. Not affiliated with the City of {city_name}, {state}.*\n"
    )

    draft = header + body + footer

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{city_name.lower().replace(' ', '-')}_{(meeting_date or datetime.now()).strftime('%Y-%m-%d')}.md"
        output_path = output_dir / filename
        output_path.write_text(draft)
        print(f"Draft saved to: {output_path}")

    return draft
