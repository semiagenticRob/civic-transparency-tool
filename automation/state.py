"""
Processed-video state tracker.

A single JSON file at state/processed.json records every meeting video that
has been turned into a Beehiiv draft, so subsequent monitor runs skip it.
GitHub Actions commits this file back to main after each run.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent.parent / "state" / "processed.json"


def _load(path: Path) -> dict:
    if not path.exists():
        return {"videos": []}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        # Atomic writes prevent new corruption, but a pre-existing corrupt file
        # (manual edit, merge conflict, legacy non-atomic write) would otherwise
        # crash the monitor before any video is processed. Surface the problem
        # loudly and continue with an empty state — better to re-process a few
        # videos than to wedge the entire pipeline.
        print(
            f"warning: {path} is not valid JSON ({exc}); treating as empty. "
            f"Inspect/restore the file to avoid re-processing.",
            file=sys.stderr,
        )
        return {"videos": []}


def _save(data: dict, path: Path) -> None:
    """Atomically replace path with the serialized data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        # On any failure (disk full, serialization, permission) clean up the
        # tempfile so we don't leak `.tmp` files in state/.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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
    videos = data.setdefault("videos", [])
    if any(entry.get("video_id") == video_id for entry in videos):
        return
    videos.append({
        "video_id": video_id,
        "draft_id": draft_id,
        "draft_url": draft_url,
        "meeting_date": meeting_date,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    })
    _save(data, path)
