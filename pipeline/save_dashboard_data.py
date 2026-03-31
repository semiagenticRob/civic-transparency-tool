"""
Saves structured meeting analysis as JSON for the React dashboard.

Writes to dashboard/public/data/<city_slug>/latest.json so the frontend
can fetch it as a static file. Also archives to meetings/<date>.json.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .analyze_meeting import MeetingAnalysis


def save_dashboard_data(
    analysis: MeetingAnalysis,
    city_config: dict,
    meeting_date: Optional[datetime] = None,
    dashboard_dir: Optional[Path] = None,
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

    payload = {
        "city": city_config["name"],
        "state": city_config["state"],
        "meeting_date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "meeting_summary": analysis.meeting_summary,
        "alerts": [],  # populated from RSS alerts if present
        "key_decisions": analysis.key_decisions,
        "notable_quotes": analysis.notable_quotes,
        "topics_discussed": analysis.topics_discussed,
        "consistency_flags": analysis.consistency_flags,
        "on_the_horizon": analysis.on_the_horizon,
        "upcoming": [],   # populated from RSS calendar feeds
        "recent_news": [], # populated from RSS news feed
        "council_members": city_config.get("council_members", []),
    }

    # Write latest.json (overwritten each run)
    latest_path = city_dir / "latest.json"
    latest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    # Archive historical copy
    archive_dir = city_dir / "meetings"
    archive_dir.mkdir(exist_ok=True)
    archive_path = archive_dir / f"{date_str}.json"
    archive_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    return latest_path


def enrich_with_rss(payload: dict, feeds: dict) -> dict:
    """
    Merge RSS feed data into a dashboard payload dict.
    Call this before save_dashboard_data if RSS data is available.
    """
    from .fetch_rss import FeedItem

    news_items = feeds.get("news", [])
    payload["recent_news"] = [item.title for item in news_items[:6]]

    calendar_items = feeds.get("calendar_council", []) + feeds.get("calendar_govt", [])
    payload["upcoming"] = [item.title for item in calendar_items[:8]]

    alert_items = feeds.get("alerts", [])
    payload["alerts"] = [
        {"title": item.title, "body": item.summary[:200] if item.summary else "", "severity": "warning"}
        for item in alert_items[:3]
    ]

    return payload
