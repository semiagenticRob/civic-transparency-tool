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
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.loader import CityConfigError, CityConfigNotFoundError, load_city_config

from . import beehiiv, civicclerk, state, youtube_monitor, orchestrator, notifier


REPO_ROOT = Path(__file__).parent.parent


def _extract_date_from_title(title: str) -> Optional[datetime]:
    """Return the calendar date mentioned in a YouTube title (e.g. 'April 28 2026'), or None."""
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
        title,
    )
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_meeting_date_from_title(title: str, fallback: datetime) -> datetime:
    """Try to extract a date like 'April 28 2026' from a YouTube title.
    Falls back to the provided datetime if not parseable."""
    return _extract_date_from_title(title) or fallback


def is_council_meeting_video(
    video: youtube_monitor.Video,
    city_config: dict,
) -> tuple[bool, str]:
    """Decide whether a YouTube video corresponds to a real council meeting.

    Primary signal: parse a date from the video title and look up CivicClerk
    events on that date under the city's council category. This is the same
    source of truth used by the meeting-type classifier downstream.

    Falls back to the legacy title-keyword filter only when the title has no
    parseable date or CivicClerk is unreachable, so a vendor outage can't
    silently drop meetings.

    Returns (is_meeting, reason). The reason is logged so rejections surface
    in CI output rather than hiding behind a "0 new meeting videos" line.
    """
    cc_cfg = city_config.get("civicclerk") or {}
    subdomain = cc_cfg.get("subdomain")
    category_id = cc_cfg.get("category_id")
    tz_name = city_config.get("timezone") or "UTC"
    keywords = city_config.get("meeting_keywords", [])

    def _keyword_fallback(prefix: str) -> tuple[bool, str]:
        if youtube_monitor.is_meeting_video(video.title, keywords):
            return True, f"{prefix}; title keywords matched"
        return False, f"{prefix}; title keywords did not match"

    meeting_date = _extract_date_from_title(video.title)
    if meeting_date is None:
        return _keyword_fallback("no parseable date in title")

    if not subdomain or not category_id:
        return _keyword_fallback("no civicclerk config")

    try:
        events = civicclerk.fetch_events_on_date(subdomain, category_id, meeting_date, tz_name)
    except Exception as e:
        return _keyword_fallback(f"civicclerk lookup failed ({e})")

    if events:
        names = ", ".join(sorted({(e.event_name or "").strip() for e in events if e.event_name}))
        return True, f"civicclerk: {len(events)} event(s) on {meeting_date.date()} ({names})"

    return False, f"no civicclerk events on {meeting_date.date()}"


def _publish_to_beehiiv(
    subject: str,
    subtitle: str,
    body_html: str,
) -> tuple[str, str, Optional[str]]:
    """Best-effort Beehiiv publish. Returns (draft_id, draft_url, error).

    Beehiiv's posts API is gated behind enterprise tiers as of 2026-05; when
    it 403s we still want the editor to receive the draft via email, so
    failures are non-fatal and surface to the editor in the email header.
    """
    publication_id = os.environ.get("BEEHIIV_PUBLICATION_ID")
    if not publication_id:
        return "", "", None
    try:
        draft = beehiiv.create_draft(
            publication_id=publication_id,
            subject=subject,
            subtitle=subtitle,
            body_html=body_html,
        )
        return draft.draft_id, draft.draft_url, None
    except Exception as e:
        return "", "", str(e)


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
            video_title=video.title,
        )
    except Exception:
        traceback.print_exc()
        return None

    print(f"    meeting_type: {result.meeting_type} (source: {result.meeting_type_source or 'unknown'})")

    if dry_run:
        preview_path = Path("/tmp") / f"preview_{video.video_id}.html"
        preview_path.write_text(result.body_html)
        print(f"  ✓ dry-run preview written to {preview_path}")
        print(f"    subject: {result.subject}")
        return result

    draft_id, draft_url, publish_error = _publish_to_beehiiv(
        subject=result.subject,
        subtitle=result.subtitle,
        body_html=result.body_html,
    )

    if draft_url:
        print(f"  ✓ Beehiiv draft posted: {draft_url}")
    elif publish_error:
        print(f"  ⚠ Beehiiv publish skipped: {publish_error[:120]}")
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
            draft_url=draft_url or None,
            publish_error=publish_error,
        )
        print(f"  ✓ draft emailed to {notify_email}")
    except Exception as e:
        print(f"  ✗ email delivery failed: {e}")
        return result

    state.mark_processed(
        video_id=video.video_id,
        draft_id=draft_id or "email-only",
        draft_url=draft_url or "",
        meeting_date=result.meeting_date,
    )
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Scheduled monitor: process new council meeting videos and email the editor.",
        epilog="Examples:\n  python -m automation.monitor\n  python -m automation.monitor --city arvada --dry-run\n  python -m automation.monitor --video-id <youtube_id>",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--city",
        default="arvada",
        help="City config slug matching config/cities/<slug>.json (default: %(default)s)",
    )
    ap.add_argument("--dry-run", action="store_true", help="render HTML but don't publish or notify")
    ap.add_argument("--video-id", help="force-process a single video, ignoring state")
    args = ap.parse_args()

    try:
        city_config = load_city_config(args.city)
    except (CityConfigNotFoundError, CityConfigError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.video_id:
        # Single-video mode — useful for testing. Pull the real video metadata
        # from the playlist when possible so the title-based date parser and the
        # CivicClerk-based classifier see the actual title + publish date,
        # not synthesized placeholders.
        playlist_id = city_config.get("youtube_playlist_id")
        v: Optional[youtube_monitor.Video] = None
        if playlist_id:
            for candidate in youtube_monitor.fetch_playlist_videos(playlist_id):
                if candidate.video_id == args.video_id:
                    v = candidate
                    print(f"Resolved {args.video_id} from playlist: {v.title!r}")
                    break
        if v is None:
            print(f"⚠ {args.video_id} not in playlist feed; using placeholder metadata "
                  "(meeting-type detection will likely fall back to title keywords)")
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

    processed = state.load_processed_ids()
    videos = youtube_monitor.fetch_playlist_videos(playlist_id)
    print(f"Playlist {playlist_id}: {len(videos)} videos in feed")

    new_meeting_videos: list[youtube_monitor.Video] = []
    for v in videos:
        if v.video_id in processed:
            continue
        is_meeting, reason = is_council_meeting_video(v, city_config)
        if is_meeting:
            print(f"  ✓ {v.video_id} {v.title!r} — {reason}")
            new_meeting_videos.append(v)
        else:
            print(f"  ⊘ {v.video_id} {v.title!r} — {reason}")
    print(f"  {len(new_meeting_videos)} new meeting videos to process")

    if not new_meeting_videos:
        return 0

    # Process oldest first so the order in state.json matches publish order
    for video in reversed(new_meeting_videos):
        process_video(video, city_config, dry_run=args.dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main())
