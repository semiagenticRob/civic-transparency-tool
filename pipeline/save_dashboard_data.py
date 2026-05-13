"""
Saves structured meeting analysis as JSON for the React dashboard.

Writes to dashboard/public/data/<city_slug>/latest.json so the frontend
can fetch it as a static file. Also archives to meetings/<date>.json.

The payload always includes a `meeting_type` field (business / workshop /
study_session) so future dashboard work can branch on it. Per the locked
plan, dashboard UI changes are deferred — for now we derive legacy-compatible
fields (`key_decisions`, `notable_quotes`, etc.) from the new structures so
the existing dashboard components keep rendering.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .analyze_meeting import (
    BusinessAnalysis,
    MeetingAnalysis,
    Quote,
    StudyAnalysis,
    WorkshopAnalysis,
)


def _to_serializable(obj: Any) -> Any:
    """Recursively convert dataclasses to dicts for JSON serialization."""
    if is_dataclass(obj):
        return {k: _to_serializable(v) for k, v in asdict(obj).items() if k != "raw_response"}
    if isinstance(obj, list):
        return [_to_serializable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    return obj


def _quote_to_legacy(q: Quote, member_profiles: dict[str, Optional[str]]) -> dict:
    """Translate a new-shape Quote into the legacy notable_quotes shape the
    existing dashboard expects."""
    return {
        "speaker": q.speaker,
        "quote": q.text,
        "context": q.context_excerpt,
        "timestamp_seconds": q.timestamp_seconds,
        "video_url": q.video_url,
        "speaker_profile_url": member_profiles.get(q.speaker),
    }


def _derive_legacy_fields(
    analysis: MeetingAnalysis,
    member_profiles: dict[str, Optional[str]],
) -> dict:
    """Map the new typed analysis onto the legacy dashboard fields so existing
    React components keep rendering until the dashboard is updated."""
    legacy_quotes: list[dict] = []
    legacy_decisions: list[dict] = []
    topics_discussed: list[str] = []

    if isinstance(analysis, BusinessAnalysis):
        for hearing in analysis.public_hearings:
            for q in (
                hearing.councilmember_commentary
                + hearing.city_staff_commentary
                + hearing.public_commentary
                + hearing.outside_party_commentary
            ):
                legacy_quotes.append(_quote_to_legacy(q, member_profiles))
            if hearing.vote_breakdown.tally:
                votes: dict[str, str] = {m.name: m.vote for m in hearing.whip_count if m.name}
                legacy_decisions.append({
                    "motion": hearing.vote_breakdown.motion_text or hearing.what_is_being_heard,
                    "result": hearing.vote_breakdown.result or "",
                    "vote_breakdown": hearing.vote_breakdown.tally,
                    "votes": votes,
                    "significance": hearing.follow_up_direction or "",
                })
        for item in analysis.consent_agenda + analysis.resolutions:
            legacy_decisions.append({
                "motion": item.official_title,
                "result": "Passed" if "PASS" in (item.vote_tally or "").upper() else item.vote_tally,
                "vote_breakdown": item.vote_tally,
                "votes": {},
                "significance": item.plain_english_summary,
            })
        for ord_item in analysis.ordinances:
            legacy_decisions.append({
                "motion": ord_item.official_title,
                "result": "Passed" if "PASS" in (ord_item.vote_tally or "").upper() else ord_item.vote_tally,
                "vote_breakdown": ord_item.vote_tally,
                "votes": {},
                "significance": ord_item.plain_english_summary,
            })
        for pres in analysis.presentations:
            topics_discussed.append(pres.topic)
        for hearing in analysis.public_hearings:
            if hearing.what_is_being_heard:
                topics_discussed.append(hearing.what_is_being_heard.split(".")[0][:80])

    elif isinstance(analysis, WorkshopAnalysis):
        for topic in analysis.workshop_topics:
            topics_discussed.append(topic.title)
            for mp in topic.member_positions:
                if mp.quote.text:
                    legacy_quotes.append(_quote_to_legacy(mp.quote, member_profiles))

    elif isinstance(analysis, StudyAnalysis):
        for briefing in analysis.briefings:
            topics_discussed.append(briefing.topic)
            for q in briefing.presenter_quotes:
                legacy_quotes.append(_quote_to_legacy(q, member_profiles))

    return {
        "key_decisions": legacy_decisions,
        "notable_quotes": legacy_quotes,
        "topics_discussed": topics_discussed,
    }


def save_dashboard_data(
    analysis: MeetingAnalysis,
    city_config: dict,
    meeting_date: Optional[datetime] = None,
    dashboard_dir: Optional[Path] = None,
    video_url: str = "",
) -> Path:
    """
    Serialize a MeetingAnalysis to JSON and write it to the dashboard data directory.
    Returns the path to the written latest.json file.
    """
    if dashboard_dir is None:
        dashboard_dir = Path(__file__).parent.parent / "dashboard" / "public" / "data"

    city_slug = city_config["name"].lower().replace(" ", "-")
    city_dir = dashboard_dir / city_slug
    city_dir.mkdir(parents=True, exist_ok=True)

    date_str = (meeting_date or datetime.now()).strftime("%Y-%m-%d")

    council_members = [
        {
            "name": m["name"],
            "title": m["title"],
            "district": m.get("district"),
            "profile_url": m.get("profile_url"),
        }
        for m in city_config.get("council_members", [])
    ]

    member_profiles = {m["name"]: m.get("profile_url") for m in city_config.get("council_members", [])}
    legacy = _derive_legacy_fields(analysis, member_profiles)

    # The type_specific block carries the full typed analysis for future dashboard work.
    type_specific = _to_serializable(analysis)

    payload = {
        "city": city_config["name"],
        "state": city_config["state"],
        "meeting_date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "video_url": video_url or None,

        # New fields
        "meeting_type": analysis.meeting_type,
        "meeting_purpose_blurb": analysis.meeting_purpose_blurb,
        "lead_headline": analysis.lead_headline,
        "schedule_portal_url": city_config.get("schedule_portal_url"),
        "type_specific": type_specific,

        # Legacy-compatible fields (kept for the existing dashboard UI)
        "meeting_summary": analysis.meeting_summary,
        "alerts": [],
        "key_decisions": legacy["key_decisions"],
        "notable_quotes": legacy["notable_quotes"],
        "topics_discussed": legacy["topics_discussed"],
        "consistency_flags": [],
        "on_the_horizon": "",
        "upcoming": [],
        "recent_news": [],
        "council_members": council_members,
    }

    latest_path = city_dir / "latest.json"
    latest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    archive_dir = city_dir / "meetings"
    archive_dir.mkdir(exist_ok=True)
    archive_path = archive_dir / f"{date_str}.json"
    archive_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    return latest_path


def enrich_with_rss(payload: dict, feeds: dict) -> dict:
    """
    Merge RSS feed data into a dashboard payload dict.
    Stores {title, url} objects so the frontend can render hyperlinks.
    """
    news_items = feeds.get("news", [])
    payload["recent_news"] = [
        {"title": item.title, "url": item.link or None}
        for item in news_items[:6]
    ]

    calendar_items = feeds.get("calendar_council", []) + feeds.get("calendar_govt", [])
    payload["upcoming"] = [
        {"title": item.title, "url": item.link or None}
        for item in calendar_items[:8]
    ]

    alert_items = feeds.get("alerts", [])
    payload["alerts"] = [
        {
            "title": item.title,
            "body": item.summary[:200] if item.summary else "",
            "severity": "warning",
            "url": item.link or None,
        }
        for item in alert_items[:3]
    ]

    return payload
