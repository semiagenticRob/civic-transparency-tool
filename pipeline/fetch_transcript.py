"""
Fetches and cleans a transcript from a YouTube video.

Usage:
    python -m pipeline.fetch_transcript <video_url_or_id>

Returns the transcript as a list of timed segments and a joined plain-text string.
"""

import re
import sys
from dataclasses import dataclass

from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound


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
    This lets Claude return approximate timestamp_seconds for quotes.
    """
    lines = []
    last_stamp = -interval_seconds
    for seg in segments:
        if seg.start - last_stamp >= interval_seconds:
            lines.append(f"\n[{_seconds_to_hms(seg.start)}]")
            last_stamp = seg.start
        lines.append(seg.text)
    return " ".join(lines)


def fetch_transcript(video_url_or_id: str) -> tuple[list[Segment], str]:
    """
    Fetch the transcript for a YouTube video.

    Returns:
        segments: list of Segment objects with timing
        full_text: plain-text transcript joined with spaces
    """
    video_id = extract_video_id(video_url_or_id)
    api = YouTubeTranscriptApi()

    try:
        fetched = api.fetch(video_id, languages=["en"])
    except TranscriptsDisabled:
        raise RuntimeError(f"Transcripts are disabled for video {video_id}")
    except NoTranscriptFound:
        transcript = api.list(video_id).find_generated_transcript(["en"])
        fetched = transcript.fetch()

    segments = [
        Segment(start=snip.start, duration=snip.duration, text=snip.text.strip())
        for snip in fetched
    ]

    full_text = " ".join(s.text for s in segments)
    # Clean up common auto-caption artifacts
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
