"""
Headless pipeline runner.

Given a YouTube video for a known city, fetch the transcript, run analysis
through OpenRouter, render the Eyes on Arvada HTML newsletter, and update
the dashboard JSON. This is the part of the pipeline that's identical
whether triggered manually or by the scheduled monitor.

Note: publication (Beehiiv) and editor delivery (Resend) are *not* the
orchestrator's concern. The caller (monitor.py or a future web API) decides
what to do with the rendered output.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from pipeline.fetch_transcript import fetch_transcript, format_with_timestamps
from pipeline.fetch_rss import fetch_all_feeds, format_for_prompt
from pipeline.analyze_meeting import analyze_meeting
from pipeline.render_newsletter import render_newsletter
from pipeline.save_dashboard_data import save_dashboard_data, enrich_with_rss
from pipeline.validate_quotes import validate_quotes

from .meeting_classifier import classify_meeting_for_video


log = logging.getLogger(__name__)


@dataclass
class RunResult:
    video_id: str
    subject: str
    subtitle: str
    body_html: str
    meeting_date: str  # YYYY-MM-DD
    meeting_type: str = ""
    meeting_type_source: str = ""
    quotes_kept: int = 0
    quotes_dropped: int = 0


def run_for_video(
    video_id: str,
    city_config: dict,
    meeting_date: Optional[datetime] = None,
    video_title: str = "",
) -> RunResult:
    """End-to-end: video_id → rendered newsletter + persisted dashboard data.

    `video_title` is used to detect the meeting type (business / workshop /
    study_session) before the LLM call. When empty, falls back to "business"
    with a warning."""

    if meeting_date is None:
        meeting_date = datetime.now(timezone.utc)

    # 1. Transcript
    segments, plain_transcript = fetch_transcript(video_id)
    transcript = format_with_timestamps(segments)

    # 2. Classify meeting type. CivicClerk is authoritative; when the date has
    #    multiple events (e.g. study session + business meeting on the same day),
    #    we disambiguate by correlating each event's agenda items against the
    #    transcript. Falls back to the YouTube-title keyword classifier only if
    #    CivicClerk lookup can't resolve it.
    meeting_type, meeting_type_source = classify_meeting_for_video(
        city_config=city_config,
        video_title=video_title or "",
        meeting_date=meeting_date,
        transcript_text=plain_transcript,
    )

    # 3. RSS context (best-effort)
    feeds = {}
    rss_context = ""
    try:
        feeds = fetch_all_feeds(city_config)
        rss_context = format_for_prompt(feeds)
    except Exception as exc:
        log.warning("RSS fetch failed (continuing without context): %s", exc)

    # 4. LLM analysis — picks the prompt + dataclass matching the meeting type
    analysis = analyze_meeting(
        transcript=transcript,
        city_config=city_config,
        meeting_type=meeting_type,
        rss_context=rss_context,
        video_id=video_id,
    )

    # 5. Validate every extracted quote against the transcript — drops quotes
    #    that fail fuzzy-match against the source. See pipeline/validate_quotes.py.
    quote_report = validate_quotes(analysis, transcript)

    # 6. Render newsletter HTML
    rendered = render_newsletter(analysis, city_config, meeting_date)

    # 7. Persist dashboard data alongside (best-effort — failure here doesn't
    #    block newsletter delivery, but the failure is logged so a silently
    #    stale dashboard is visible in CI logs).
    try:
        latest_path = save_dashboard_data(
            analysis=analysis,
            city_config=city_config,
            meeting_date=meeting_date,
            video_url=f"https://www.youtube.com/watch?v={video_id}",
        )
        if feeds:
            payload = json.loads(latest_path.read_text())
            payload = enrich_with_rss(payload, feeds)
            latest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    except Exception as exc:
        log.warning("dashboard write failed (continuing): %s", exc)

    return RunResult(
        video_id=video_id,
        subject=rendered.subject,
        subtitle=rendered.subtitle,
        body_html=rendered.body_html,
        meeting_date=meeting_date.strftime("%Y-%m-%d"),
        meeting_type=meeting_type,
        meeting_type_source=meeting_type_source,
        quotes_kept=quote_report.kept,
        quotes_dropped=quote_report.dropped,
    )
