"""
Processed-video state tracker.

A single JSON file at state/processed.json records every meeting video that
has been turned into a Beehiiv draft, so subsequent monitor runs skip it.
GitHub Actions commits this file back to main after each run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent.parent / "state" / "processed.json"


def _load(path: Path) -> dict:
    if not path.exists():
        return {"videos": []}
    return json.loads(path.read_text())


def load_processed_ids(path: Path = _DEFAULT_PATH) -> set[str]:
    """Return the set of video_ids already processed."""
    data = _load(path)
    return {entry["video_id"] for entry in data.get("videos", [])}


def mark_processed(
    video_id: str,
    draft_id: str,
    draft_url: str,
    meeting_date: str,
    path: Path = _DEFAULT_PATH,
) -> None:
    """Append a processed video and persist to disk."""
    data = _load(path)
    data.setdefault("videos", []).append({
        "video_id": video_id,
        "draft_id": draft_id,
        "draft_url": draft_url,
        "meeting_date": meeting_date,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
