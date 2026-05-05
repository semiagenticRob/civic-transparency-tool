"""
YouTube playlist monitor.

YouTube exposes a public RSS feed for any playlist:
  https://www.youtube.com/feeds/videos.xml?playlist_id={id}

Returns the most recent ~15 entries by default. Free, no auth, no rate limit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import feedparser


@dataclass
class Video:
    video_id: str
    title: str
    published_at: datetime
    url: str


_VIDEO_ID_RE = re.compile(r"yt:video:([A-Za-z0-9_-]{11})")


def fetch_playlist_videos(playlist_id: str) -> list[Video]:
    """Return videos from the playlist's RSS feed, newest first."""
    feed = feedparser.parse(
        f"https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}"
    )

    out: list[Video] = []
    for entry in feed.entries:
        # Each entry has yt:videoId; feedparser exposes it as yt_videoid
        video_id = entry.get("yt_videoid") or _extract_video_id(entry)
        if not video_id:
            continue
        try:
            published = datetime.fromisoformat(entry.published.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            published = datetime.now()
        out.append(Video(
            video_id=video_id,
            title=entry.get("title", ""),
            published_at=published,
            url=f"https://www.youtube.com/watch?v={video_id}",
        ))

    return out


def _extract_video_id(entry) -> Optional[str]:
    """Fallback parser for the yt:videoId field if feedparser doesn't expose it."""
    raw = entry.get("id") or ""
    match = _VIDEO_ID_RE.search(raw)
    return match.group(1) if match else None


def is_meeting_video(title: str, keywords: list[str]) -> bool:
    """True if the video title looks like a council meeting (matches any keyword case-insensitively)."""
    if not keywords:
        return True
    lowered = title.lower()
    return any(kw.lower() in lowered for kw in keywords)
