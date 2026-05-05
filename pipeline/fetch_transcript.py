"""
Fetches and cleans a YouTube transcript using yt-dlp.

Why yt-dlp instead of youtube-transcript-api: the simpler library hits
https://www.youtube.com/api/timedtext directly, which YouTube anti-bot blocks
from data-center IP ranges (including GitHub Actions runners). yt-dlp has
to extract a video player payload first to get fresh signed caption URLs,
which sails through.

Returns a list of timed Segment objects plus a joined plain-text string.
"""

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import requests
import yt_dlp

# Languages we'll try, in priority order
_PREFERRED_LANGS = ["en", "en-US", "en-GB", "en-uYU-mmqFLq8", "en-JkeT_87f4cc"]


def extract_video_id(url_or_id: str) -> str:
    """Accept a full YouTube URL or a bare video ID and return the video ID."""
    patterns = [
        r"(?:v=|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})",
        r"^([A-Za-z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from: {url_or_id}")


@dataclass
class Segment:
    start: float
    duration: float
    text: str


def _seconds_to_hms(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def format_with_timestamps(segments: list[Segment], interval_seconds: int = 30) -> str:
    """
    Return a transcript string with periodic timestamps injected, e.g.:
        [00:05:32] We need to consider the budget implications...
    Timestamps are inserted at roughly every `interval_seconds`.
    This lets the LLM return approximate timestamp_seconds for quotes.
    """
    lines = []
    last_stamp = -interval_seconds
    for seg in segments:
        if seg.start - last_stamp >= interval_seconds:
            lines.append(f"\n[{_seconds_to_hms(seg.start)}]")
            last_stamp = seg.start
        lines.append(seg.text)
    return " ".join(lines)


def _find_caption_url(info: dict) -> tuple[str, str]:
    """Pick the best (manual > automatic, en > variant) json3 caption URL.
    Returns (lang_code, url) or raises if none found."""
    for src in ("subtitles", "automatic_captions"):
        caps = info.get(src) or {}
        # Try preferred languages first, then any en* variant, then any
        candidates = list(_PREFERRED_LANGS)
        candidates += [k for k in caps if k.startswith("en") and k not in candidates]
        for lang in candidates:
            for entry in caps.get(lang, []):
                if entry.get("ext") == "json3" and entry.get("url"):
                    return lang, entry["url"]
    raise RuntimeError("No English caption track found")


def _parse_json3(data: dict) -> list[Segment]:
    segments: list[Segment] = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs).strip()
        if not text:
            continue
        start = (event.get("tStartMs") or 0) / 1000.0
        duration = (event.get("dDurationMs") or 0) / 1000.0
        segments.append(Segment(start=start, duration=duration, text=text))
    return segments


def fetch_transcript(video_url_or_id: str) -> tuple[list[Segment], str]:
    """
    Fetch the transcript for a YouTube video via yt-dlp + the timedtext API.

    Returns:
        segments: list of Segment objects with timing
        full_text: plain-text transcript joined with spaces (auto-caption noise stripped)
    """
    video_id = extract_video_id(video_url_or_id)
    url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        "skip_download": True,
        # We only want the captions metadata. Some player_clients return no
        # downloadable video formats (especially when authenticated) — skip
        # the format-availability check so extraction doesn't fail there.
        "ignore_no_formats_error": True,
        "quiet": True,
        "no_warnings": True,
        # The 'android' player_client reliably returns caption URLs even from
        # data-center IPs; the default 'web' client does not.
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }

    # Pass YouTube cookies if available — needed for data-center IPs (like
    # GitHub Actions runners) that hit "Sign in to confirm you're not a bot".
    # Locally, just set YT_COOKIES_FILE=/path/to/cookies.txt.
    cookie_file = os.environ.get("YT_COOKIES_FILE")
    if cookie_file and Path(cookie_file).exists():
        ydl_opts["cookiefile"] = cookie_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    _lang, caption_url = _find_caption_url(info)

    resp = requests.get(caption_url, timeout=30)
    resp.raise_for_status()
    segments = _parse_json3(resp.json())

    if not segments:
        raise RuntimeError(f"Caption track for {video_id} was empty")

    full_text = " ".join(s.text for s in segments)
    full_text = re.sub(r"\[.*?\]", "", full_text)       # remove [Music], [Applause], etc.
    full_text = re.sub(r"\s+", " ", full_text).strip()

    return segments, full_text


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m pipeline.fetch_transcript <video_url_or_id>")
        sys.exit(1)

    segs, text = fetch_transcript(sys.argv[1])
    print(f"Fetched {len(segs)} segments ({len(text)} chars)\n")
    print(text[:2000], "..." if len(text) > 2000 else "")
