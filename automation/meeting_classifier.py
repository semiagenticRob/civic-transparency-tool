"""
Authoritative meeting-type classification using CivicClerk.

The YouTube channel publishes most council videos with the same generic title
("Arvada City Council Meeting - <date>"), so the title-keyword classifier in
pipeline/meeting_type.py is unreliable: workshops are routinely misclassified
as business meetings. CivicClerk is the city's own system of record and tags
each meeting with an authoritative eventName / eventTemplateName.

This module wraps that lookup with a decision tree that also handles the case
where multiple CivicClerk events exist on the same date (Arvada has done this:
e.g. April 7 had both a study session and a business meeting). When the date
is ambiguous, we score each candidate's agenda items against the actual video
transcript and pick the agenda that was actually being discussed.

Returns (meeting_type, source) so the caller can log which signal won.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from pipeline.meeting_type import MeetingType, detect_meeting_type

from . import civicclerk


log = logging.getLogger(__name__)


# Substrings checked (case-insensitive) against CivicClerk eventName,
# eventTemplateName, and agendaName. Order matters: more specific first.
_TYPE_PATTERNS: list[tuple[str, MeetingType]] = [
    ("study session", "study_session"),
    ("workshop", "workshop"),
    ("business meeting", "business"),
    ("special city council", "business"),
]


# Words too generic to discriminate between meeting types — drop from agenda
# tokens before scoring. Procedural items ("call to order", "adjournment",
# "roll call") show up in every council agenda regardless of type.
_AGENDA_STOPWORDS = {
    "the", "of", "and", "to", "a", "an", "for", "on", "in", "at", "by", "or",
    "from", "with", "is", "are", "be", "this", "that",
    "call", "order", "roll", "adjournment", "councilmembers", "councilmember",
    "council", "meeting", "city", "minute", "minutes", "approval", "comments",
    "comment", "none",
}


def classify_event_type(meeting: civicclerk.Meeting) -> Optional[MeetingType]:
    """Map a CivicClerk Meeting's name fields to our internal MeetingType, or None if unmappable."""
    haystack = " ".join([
        meeting.event_name or "",
        meeting.event_template_name or "",
        meeting.agenda_name or "",
    ]).lower()
    for pattern, mtype in _TYPE_PATTERNS:
        if pattern in haystack:
            return mtype
    return None


def _tokenize(text: str) -> set[str]:
    """Lowercase word tokens of length ≥ 3, with stopwords removed."""
    words = re.findall(r"[a-z][a-z'-]{2,}", text.lower())
    return {w for w in words if w not in _AGENDA_STOPWORDS}


def _agenda_score(agenda_items: list[str], distinctive_tokens: set[str], transcript_text: str) -> int:
    """Count how many of an agenda's distinctive tokens appear in the transcript."""
    transcript_lower = transcript_text.lower()
    hits = 0
    for tok in distinctive_tokens:
        if tok in transcript_lower:
            hits += 1
    return hits


def _disambiguate_by_agenda(
    candidates: list[civicclerk.Meeting],
    subdomain: str,
    transcript_text: str,
) -> Optional[tuple[civicclerk.Meeting, int]]:
    """When multiple events share a date, fetch each agenda, drop tokens shared by all
    candidates, and pick the agenda whose distinctive tokens appear most in the transcript.

    Returns (winning_meeting, score) or None if all candidates score zero.
    """
    agendas: list[tuple[civicclerk.Meeting, set[str]]] = []
    for m in candidates:
        items = civicclerk.fetch_agenda_items(subdomain, m.agenda_id)
        tokens = _tokenize(" ".join(items))
        agendas.append((m, tokens))

    # Tokens that appear in every candidate's agenda are uninformative.
    if agendas:
        shared = set.intersection(*(toks for _, toks in agendas)) if all(toks for _, toks in agendas) else set()
    else:
        shared = set()

    scored: list[tuple[civicclerk.Meeting, int]] = []
    for m, toks in agendas:
        distinctive = toks - shared
        score = _agenda_score([], distinctive, transcript_text)
        log.info(
            "Agenda match: event=%s (id=%s) distinctive_tokens=%d transcript_hits=%d",
            m.event_name, m.id, len(distinctive), score,
        )
        scored.append((m, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    if not scored or scored[0][1] == 0:
        return None
    # Require a clear winner: top score must beat the runner-up.
    if len(scored) > 1 and scored[0][1] == scored[1][1]:
        log.warning("Agenda match tie between top candidates; no clear winner")
        return None
    return scored[0]


def classify_meeting_for_video(
    *,
    city_config: dict,
    video_title: str,
    meeting_date: datetime,
    transcript_text: str,
) -> tuple[MeetingType, str]:
    """Return (meeting_type, source) where source is one of:

      - 'civicclerk:single'         — exactly one CivicClerk event on the date
      - 'civicclerk:agenda_match'   — multiple events, picked the one whose agenda items
                                       best match the transcript
      - 'title_fallback'            — CivicClerk lookup didn't resolve; fell back to
                                       the YouTube-title keyword classifier
    """
    cc_cfg = city_config.get("civicclerk") or {}
    subdomain = cc_cfg.get("subdomain")
    category_id = cc_cfg.get("category_id")
    tz_name = city_config.get("timezone") or "UTC"

    def _fallback(reason: str) -> tuple[MeetingType, str]:
        log.warning("CivicClerk classification fell through (%s); using title-keyword fallback", reason)
        return detect_meeting_type(video_title or "", city_config), "title_fallback"

    if not subdomain or not category_id:
        return _fallback("no civicclerk config")

    try:
        events = civicclerk.fetch_events_on_date(subdomain, category_id, meeting_date, tz_name)
    except Exception as e:
        return _fallback(f"fetch_events_on_date raised: {e}")

    if not events:
        return _fallback("no events on date")

    if len(events) == 1:
        mtype = classify_event_type(events[0])
        if mtype is None:
            return _fallback(f"unmappable event name: {events[0].event_name!r}")
        log.info(
            "CivicClerk classification: event=%s (id=%s) → %s",
            events[0].event_name, events[0].id, mtype,
        )
        return mtype, "civicclerk:single"

    # Multiple events on the same date — disambiguate via agenda-item ↔ transcript correlation.
    log.info("Multiple CivicClerk events on date (%d); disambiguating via agenda match", len(events))
    winner = _disambiguate_by_agenda(events, subdomain, transcript_text)
    if winner is None:
        return _fallback("agenda match inconclusive among multiple events")
    chosen, score = winner
    mtype = classify_event_type(chosen)
    if mtype is None:
        return _fallback(f"winning event has unmappable name: {chosen.event_name!r}")
    log.info(
        "CivicClerk agenda match: event=%s (id=%s, score=%d) → %s",
        chosen.event_name, chosen.id, score, mtype,
    )
    return mtype, "civicclerk:agenda_match"
