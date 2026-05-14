"""
CivicClerk public OData client.

CivicClerk (the meeting-portal vendor used by Arvada and many other cities)
exposes meetings via OData at https://{subdomain}.api.civicclerk.com/v1/Events.
No auth required.

Schema may shift since the vendor doesn't formally publish the API. We fetch
defensively and skip rows that don't have the fields we need.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import requests


log = logging.getLogger(__name__)


@dataclass
class Meeting:
    id: int
    title: str           # legacy alias of event_name, kept for back-compat
    start_at: datetime
    location: Optional[str]
    agenda_url: Optional[str]
    event_name: str = ""
    event_template_name: str = ""
    agenda_id: int = 0
    agenda_name: str = ""


def _parse_event_row(row: dict) -> Optional[Meeting]:
    """Build a Meeting from one CivicClerk Events row. Returns None if essential fields are missing."""
    try:
        start_at = datetime.fromisoformat(row["startDateTime"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None

    agenda_url = None
    for doc in row.get("publishedFiles", []) or []:
        type_name = ""
        type_field = doc.get("type")
        if isinstance(type_field, dict):
            type_name = (type_field.get("name") or "").lower()
        elif isinstance(type_field, str):
            type_name = type_field.lower()
        if "agenda" in type_name and (doc.get("fileUrl") or doc.get("url")):
            agenda_url = doc.get("fileUrl") or doc.get("url")
            break

    loc = row.get("location") or row.get("eventLocation")
    location_str: Optional[str] = None
    if isinstance(loc, dict):
        location_str = loc.get("name") or loc.get("address1")
    elif isinstance(loc, str):
        location_str = loc

    event_name = row.get("eventName") or "(unnamed meeting)"
    return Meeting(
        id=row.get("id"),
        title=event_name,
        start_at=start_at,
        location=location_str,
        agenda_url=agenda_url,
        event_name=event_name,
        event_template_name=(row.get("eventTemplateName") or "").strip(),
        agenda_id=row.get("agendaId") or 0,
        agenda_name=row.get("agendaName") or "",
    )


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
        m = _parse_event_row(row)
        if m is not None:
            out.append(m)
    return out


def fetch_events_on_date(
    subdomain: str,
    category_id: int,
    local_date: datetime,
    tz_name: str,
) -> list[Meeting]:
    """Return all events under `category_id` whose start time falls on `local_date` in `tz_name`.

    `local_date` only needs to carry a date (time is ignored). We compute the [00:00, 24:00)
    window in the city's timezone, convert to UTC, and filter CivicClerk by that range.
    """
    tz = ZoneInfo(tz_name)
    day_start_local = datetime(local_date.year, local_date.month, local_date.day, tzinfo=tz)
    day_end_local = day_start_local + timedelta(days=1)
    day_start_utc = day_start_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    day_end_utc = day_end_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    url = f"https://{subdomain}.api.civicclerk.com/v1/Events"
    params = {
        "$filter": (
            f"startDateTime ge {day_start_utc} and startDateTime lt {day_end_utc} "
            f"and categoryId in ({category_id})"
        ),
        "$orderby": "startDateTime asc",
        "$top": "20",
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    payload = resp.json()

    out: list[Meeting] = []
    for row in payload.get("value", []):
        m = _parse_event_row(row)
        if m is not None:
            out.append(m)
    return out


def fetch_agenda_items(subdomain: str, agenda_id: int) -> list[str]:
    """Return the flat list of human-readable agenda item names for a Meeting (agendaId).

    Drops empty strings. Includes both top-level section headers and child items, since
    either may show up as spoken phrases in the transcript.
    """
    if not agenda_id:
        return []
    url = f"https://{subdomain}.api.civicclerk.com/v1/Meetings/{agenda_id}"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning("Failed to fetch agenda items for agendaId=%s: %s", agenda_id, e)
        return []
    payload = resp.json()

    out: list[str] = []
    for it in payload.get("items", []) or []:
        name = (it.get("agendaObjectItemName") or "").strip()
        if name:
            out.append(name)
    return out
