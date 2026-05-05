"""
Fetches and cleans a YouTube transcript.

Two backends, picked by env:
  * SOCIALKIT_API_KEY set → use SocialKit's hosted transcript API (residential
    egress, no IP-block headaches). Free tier: 20 credits/mo.
  * Otherwise → use yt-dlp locally (works fine from a residential connection;
    fails on data-center IPs like GitHub Actions runners).

Returns a list of timed Segment objects plus a joined plain-text string.
"""

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import requests
import yt_dlp

# yt-dlp languages we'll try, in priority order
_PREFERRED_LANGS = ["en", "en-US", "en-GB", "en-uYU-mmqFLq8", "en-JkeT_87f4cc"]

_SOCIALKIT_ENDPOINT = "https://api.socialkit.dev/youtube/transcript"


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


def format_with_timestamps(segments: list, interval_seconds: int = 30) -> str:
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


# ─── SocialKit backend ─────────────────────────────────────────────────────

def _fetch_via_socialkit(video_id: str, api_key: str) -> list:
    """Call SocialKit's hosted YouTube Transcript API.

    Endpoint: GET https://api.socialkit.dev/youtube/transcript
    Auth: access_key query param
    Response: { success, data: { transcriptSegments: [{text, start, duration, timestamp}], ... } }
    """
    params = {
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "access_key": api_key,
    }
    resp = requests.get(_SOCIALKIT_ENDPOINT, params=params, timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"SocialKit API error {resp.status_code}: {resp.text[:300]}")

    payload = resp.json()
    if not payload.get("success"):
        raise RuntimeError(f"SocialKit returned success=false: {str(payload)[:300]}")

    segments = []
    for raw in payload.get("data", {}).get("transcriptSegments", []):
        text = (raw.get("text") or "").strip()
        if not text:
            continue
        segments.append(Segment(
            start=float(raw.get("start", 0.0)),
            duration=float(raw.get("duration", 0.0)),
            text=text,
        ))
    return segments


# ─── yt-dlp backend ─────────────────────────────────────────────────────────

def _find_caption_url(info: dict) -> tuple:
    """Pick the best (manual > automatic, en > variant) json3 caption URL."""
    for src in ("subtitles", "automatic_captions"):
        caps = info.get(src) or {}
        candidates = list(_PREFERRED_LANGS)
        candidates += [k for k in caps if k.startswith("en") and k not in candidates]
        for lang in candidates:
            for entry in caps.get(lang, []):
                if entry.get("ext") == "json3" and entry.get("url"):
                    return lang, entry["url"]
    sub_keys = list((info.get("subtitles") or {}).keys())[:8]
    auto_keys = list((info.get("automatic_captions") or {}).keys())[:8]
    raise RuntimeError(
        f"No English caption track found. video_id={info.get('id')!r} "
        f"subtitles_keys={sub_keys} automatic_caption_keys={auto_keys}"
    )


def _parse_json3(data: dict) -> list:
    segments = []
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


def _fetch_via_yt_dlp(video_id: str) -> list:
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        "skip_download": True,
        "ignore_no_formats_error": True,
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"player_client": ["web", "android", "tv_simply"]}},
    }
    cookie_file = os.environ.get("YT_COOKIES_FILE")
    if cookie_file and Path(cookie_file).exists():
        ydl_opts["cookiefile"] = cookie_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    _lang, caption_url = _find_caption_url(info)
    resp = requests.get(caption_url, timeout=30)
    resp.raise_for_status()
    return _parse_json3(resp.json())


# ─── Public entry point ─────────────────────────────────────────────────────

def fetch_transcript(video_url_or_id: str) -> tuple:
    """
    Fetch the transcript for a YouTube video.

    Picks SocialKit (hosted, residential egress) when SOCIALKIT_API_KEY is set,
    otherwise falls back to yt-dlp (works locally on residential connections,
    fails on data-center IPs).

    Returns:
        segments: list of Segment objects with timing
        full_text: plain-text transcript joined with spaces (auto-caption noise stripped)
    """
    video_id = extract_video_id(video_url_or_id)

    socialkit_key = os.environ.get("SOCIALKIT_API_KEY")
    if socialkit_key:
        segments = _fetch_via_socialkit(video_id, socialkit_key)
    else:
        segments = _fetch_via_yt_dlp(video_id)

    if not segments:
        raise RuntimeError(f"Caption track for {video_id} was empty")

    full_text = " ".join(s.text for s in segments)
    full_text = re.sub(r"\[.*?\]", "", full_text)        # strip [Music], [Applause], etc.
    full_text = re.sub(r"\s+", " ", full_text).strip()

    return segments, full_text


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m pipeline.fetch_transcript <video_url_or_id>")
        sys.exit(1)

    segs, text = fetch_transcript(sys.argv[1])
    print(f"Fetched {len(segs)} segments ({len(text)} chars)\n")
    print(text[:2000], "..." if len(text) > 2000 else "")
