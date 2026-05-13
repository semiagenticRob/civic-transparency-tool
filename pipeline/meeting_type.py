"""
Detects which type of City Council meeting a video covers, based on title keywords.

CivicClerk's OData API doesn't expose a meeting-type field — it returns `eventName`
and `categoryId` (the same category for every Arvada council meeting). YouTube titles
and CivicClerk event names follow the same naming convention, so we classify from
the title.

Three types are supported, each driving a different newsletter prompt + template:

  - business: Council makes official decisions (motions, ordinances, resolutions).
    Public comment is taken. Public hearings live here.
  - workshop: Council examines topics in depth, no formal vote, no public comment.
  - study_session: Informal learning session. Observation-only via Zoom.

Matching is longest-keyword-wins so phrases like "City Council Workshop Meeting"
classify as workshop, not business.
"""

from __future__ import annotations

import logging
from typing import Literal


log = logging.getLogger(__name__)


MeetingType = Literal["business", "workshop", "study_session"]


_DEFAULT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "workshop": ["workshop"],
    "study_session": ["study session"],
    "business": ["city council meeting", "special city council"],
}


def detect_meeting_type(title: str, city_config: dict) -> MeetingType:
    """
    Classify a meeting from its video / event title.

    Reads `meeting_type_keywords` from city_config (falling back to a sensible
    default). Matching is case-insensitive and longest-keyword-wins so more
    specific phrases beat shorter ones — e.g. "study session" beats "session"
    and a title containing both "workshop" and "council meeting" resolves to
    workshop because that's the more specific signal.

    Returns "business" with a warning when no keyword matches; this is the
    safest fallback because business-meeting coverage has the most structured
    output and won't fabricate workshop topics if the meeting is actually a
    business meeting.
    """
    type_keywords = city_config.get("meeting_type_keywords") or _DEFAULT_TYPE_KEYWORDS
    lowered = title.lower()

    matches: list[tuple[int, MeetingType]] = []
    for meeting_type, keywords in type_keywords.items():
        for keyword in keywords:
            if keyword.lower() in lowered:
                matches.append((len(keyword), meeting_type))  # type: ignore[arg-type]

    if not matches:
        log.warning(
            "Could not detect meeting type from title %r; defaulting to 'business'. "
            "Consider adding a matching keyword to meeting_type_keywords in the city config.",
            title,
        )
        return "business"

    # Longest match wins; if tie, dict-insertion order from city_config breaks it.
    matches.sort(key=lambda m: m[0], reverse=True)
    return matches[0][1]
