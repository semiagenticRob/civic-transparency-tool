"""
CivicClerk public OData client.

CivicClerk (the meeting-portal vendor used by Arvada and many other cities)
exposes meetings via OData at https://{subdomain}.api.civicclerk.com/v1/Events.
No auth required.

Schema may shift since the vendor doesn't formally publish the API. We fetch
defensively and skip rows that don't have the fields we need.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests


@dataclass
class Meeting:
    id: int
    title: str
    start_at: datetime
    location: Optional[str]
    agenda_url: Optional[str]


def fetch_upcoming_meetings(
    subdomain: str,
    category_id: int,
    since: Optional[datetime] = None,
    limit: int = 25,
) -> list[Meeting]:
    """Return meetings under `category_id` that start at or after `since` (default: now UTC)."""
    if since is None:
        since = datetime.now(timezone.utc)

    iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    url = f"https://{subdomain}.api.civicclerk.com/v1/Events"
    params = {
        "$filter": f"startDateTime ge {iso} and categoryId in ({category_id})",
        "$orderby": "startDateTime asc",
        "$top": str(limit),
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    payload = resp.json()

    out: list[Meeting] = []
    for row in payload.get("value", []):
        try:
            start_at = datetime.fromisoformat(row["startDateTime"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue

        # Find first agenda-like document attached to the event, if any
        agenda_url = None
        for doc in row.get("publishedFiles", []) or []:
            name = (doc.get("type", {}) or {}).get("name", "").lower()
            if "agenda" in name and doc.get("fileUrl"):
                agenda_url = doc["fileUrl"]
                break

        out.append(Meeting(
            id=row.get("id"),
            title=row.get("eventName", "(unnamed meeting)"),
            start_at=start_at,
            location=(row.get("location") or {}).get("name") if isinstance(row.get("location"), dict) else row.get("location"),
            agenda_url=agenda_url,
        ))

    return out
