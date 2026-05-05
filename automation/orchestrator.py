"""
Headless pipeline runner.

Given a YouTube video for a known city, fetch the transcript, run analysis
through OpenRouter, render the Eyes on Arvada HTML newsletter, post a draft
to Beehiiv, and update the dashboard JSON.

This is the part of the pipeline that's identical whether triggered manually
or by the scheduled monitor.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pipeline.fetch_transcript import fetch_transcript, format_with_timestamps
from pipeline.fetch_rss import fetch_all_feeds, format_for_prompt
from pipeline.analyze_meeting import analyze_meeting
from pipeline.render_newsletter import render_newsletter
from pipeline.save_dashboard_data import save_dashboard_data, enrich_with_rss

from . import beehiiv


@dataclass
class RunResult:
    video_id: str
    draft_id: str
    draft_url: str
    subject: str
    subtitle: str
    body_html: str
    meeting_date: str  # YYYY-MM-DD
    error: Optional[str] = None


def run_for_video(
    video_id: str,
    city_config: dict,
    meeting_date: Optional[datetime] = None,
    publish: bool = True,
) -> RunResult:
    """End-to-end: video_id → Beehiiv draft. If publish=False, returns the
    rendered HTML without posting to Beehiiv (useful for local preview)."""

    if meeting_date is None:
        meeting_date = datetime.now(timezone.utc)

    # 1. Transcript
    segments, _plain = fetch_transcript(video_id)
    transcript = format_with_timestamps(segments)

    # 2. RSS context (best-effort)
    feeds = {}
    rss_context = ""
    try:
        feeds = fetch_all_feeds(city_config)
        rss_context = format_for_prompt(feeds)
    except Exception:
        pass  # don't let flaky feeds block the pipeline

    # 3. LLM analysis (OpenRouter)
    analysis = analyze_meeting(
        transcript=transcript,
        city_config=city_config,
        rss_context=rss_context,
        video_id=video_id,
    )

    # 4. Render newsletter HTML
    rendered = render_newsletter(analysis, city_config, meeting_date)

    # 5. Persist dashboard data alongside (best-effort)
    try:
        latest_path = save_dashboard_data(
            analysis=analysis,
            city_config=city_config,
            meeting_date=meeting_date,
            video_url=f"https://www.youtube.com/watch?v={video_id}",
        )
        if feeds:
            import json as _json
            payload = _json.loads(latest_path.read_text())
            payload = enrich_with_rss(payload, feeds)
            latest_path.write_text(_json.dumps(payload, indent=2, ensure_ascii=False))
    except Exception:
        pass  # dashboard write is not critical to newsletter delivery

    # 6. Beehiiv draft
    draft_id = ""
    draft_url = ""
    error = None
    if publish:
        try:
            publication_id = os.environ["BEEHIIV_PUBLICATION_ID"]
            draft = beehiiv.create_draft(
                publication_id=publication_id,
                subject=rendered.subject,
                subtitle=rendered.subtitle,
                body_html=rendered.body_html,
            )
            draft_id = draft.draft_id
            draft_url = draft.draft_url
        except Exception as e:
            error = str(e)

    return RunResult(
        video_id=video_id,
        draft_id=draft_id,
        draft_url=draft_url,
        subject=rendered.subject,
        subtitle=rendered.subtitle,
        body_html=rendered.body_html,
        meeting_date=meeting_date.strftime("%Y-%m-%d"),
        error=error,
    )
