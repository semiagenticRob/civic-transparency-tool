"""
Eyes on Arvada — scheduled monitor entry point.

Run by .github/workflows/monitor.yml on a cron schedule. Walks the city's
YouTube playlist for unprocessed meeting videos, runs the pipeline for each,
and emails the editor when a Beehiiv draft is ready.

Local usage:
    python -m automation.monitor                           # process new videos
    python -m automation.monitor --city arvada --dry-run   # preview HTML, don't publish
    python -m automation.monitor --video-id <id>           # force-process one video
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import state, youtube_monitor, orchestrator, notifier


REPO_ROOT = Path(__file__).parent.parent


def load_city_config(city: str) -> dict:
    config_path = REPO_ROOT / "config" / "cities" / f"{city}.json"
    return json.loads(config_path.read_text())


def parse_meeting_date_from_title(title: str, fallback: datetime) -> datetime:
    """Try to extract a date like 'April 28 2026' from a YouTube title.
    Falls back to the provided datetime if not parseable."""
    import re
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
        title,
    )
    if not m:
        return fallback
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return fallback


def process_video(
    video: youtube_monitor.Video,
    city_config: dict,
    dry_run: bool,
) -> Optional[orchestrator.RunResult]:
    """Run the pipeline for a single video. Returns None on hard failure."""
    meeting_date = parse_meeting_date_from_title(video.title, video.published_at)
    print(f"  → analyzing {video.video_id} ({video.title})")
    try:
        result = orchestrator.run_for_video(
            video_id=video.video_id,
            city_config=city_config,
            meeting_date=meeting_date,
            publish=not dry_run,
        )
    except Exception:
        traceback.print_exc()
        return None

    if dry_run:
        preview_path = Path("/tmp") / f"preview_{video.video_id}.html"
        preview_path.write_text(result.body_html)
        print(f"  ✓ dry-run preview written to {preview_path}")
        print(f"    subject: {result.subject}")
        return result

    if result.draft_url:
        print(f"  ✓ Beehiiv draft posted: {result.draft_url}")
    elif result.error:
        print(f"  ⚠ Beehiiv publish skipped: {result.error[:120]}")
    else:
        print("  ⚠ Beehiiv not configured — delivering via email only")

    # Email delivery is the canonical handoff to the editor — the rendered
    # HTML lands in their inbox with an attached file for Beehiiv paste-in.
    notify_email = os.environ.get("NOTIFY_EMAIL")
    if not notify_email:
        print("  ✗ NOTIFY_EMAIL not set — no way to deliver draft, marking failed")
        return result

    try:
        notifier.deliver_draft(
            to_email=notify_email,
            subject_line=result.subject,
            body_html=result.body_html,
            draft_url=result.draft_url or None,
            publish_error=result.error,
        )
        print(f"  ✓ draft emailed to {notify_email}")
    except Exception as e:
        print(f"  ✗ email delivery failed: {e}")
        return result

    state.mark_processed(
        video_id=video.video_id,
        draft_id=result.draft_id or "email-only",
        draft_url=result.draft_url or "",
        meeting_date=result.meeting_date,
    )
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="arvada")
    ap.add_argument("--dry-run", action="store_true", help="render HTML but don't publish or notify")
    ap.add_argument("--video-id", help="force-process a single video, ignoring state")
    args = ap.parse_args()

    city_config = load_city_config(args.city)

    if args.video_id:
        # Single-video mode — useful for testing
        v = youtube_monitor.Video(
            video_id=args.video_id,
            title=f"(forced) {args.video_id}",
            published_at=datetime.now(timezone.utc),
            url=f"https://www.youtube.com/watch?v={args.video_id}",
        )
        process_video(v, city_config, dry_run=args.dry_run)
        return 0

    playlist_id = city_config.get("youtube_playlist_id")
    if not playlist_id:
        print(f"No youtube_playlist_id in config for {args.city}", file=sys.stderr)
        return 1

    keywords = city_config.get("meeting_keywords", [])
    processed = state.load_processed_ids()
    videos = youtube_monitor.fetch_playlist_videos(playlist_id)
    print(f"Playlist {playlist_id}: {len(videos)} videos in feed")

    new_meeting_videos = [
        v for v in videos
        if v.video_id not in processed
        and youtube_monitor.is_meeting_video(v.title, keywords)
    ]
    print(f"  {len(new_meeting_videos)} new meeting videos to process")

    if not new_meeting_videos:
        return 0

    # Process oldest first so the order in state.json matches publish order
    for video in reversed(new_meeting_videos):
        process_video(video, city_config, dry_run=args.dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main())
