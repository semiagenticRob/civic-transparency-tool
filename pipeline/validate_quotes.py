"""
Validates every quote in a MeetingAnalysis against the source transcript.

Each Quote produced by the LLM carries provenance fields (text, speaker,
timestamp_seconds, context_excerpt). This module fuzzy-matches the quote text
against the transcript within ±2 minutes of its claimed timestamp. Quotes that
fail validation are dropped from the analysis and a warning is logged so we can
spot prompt drift in dry-runs.

See memory/quote_provenance.md and the ANALYSIS_PROMPT_* quote-provenance block.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .analyze_meeting import (
    BusinessAnalysis,
    Briefing,
    MeetingAnalysis,
    PublicHearingItem,
    Quote,
    StudyAnalysis,
    WorkshopAnalysis,
)


log = logging.getLogger(__name__)


# Tunable thresholds — picked to be generous enough that minor whitespace /
# punctuation differences don't fail valid quotes, but tight enough that
# fabricated quotes don't slip through.
SIMILARITY_THRESHOLD = 0.92
TIMESTAMP_WINDOW_SECONDS = 120  # ±2 minutes


# Curly quotes, ellipsis, and other Unicode punctuation the LLM tends to
# substitute for ASCII. We normalize both sides before comparing.
_PUNCT_NORMALIZE = str.maketrans({
    "‘": "'", "’": "'",  # curly single quotes
    "“": '"', "”": '"',  # curly double quotes
    "–": "-", "—": "-",  # en/em dash
    "…": "...",               # ellipsis
    "\xa0": " ",                   # nbsp
})

_WS = re.compile(r"\s+")
_TIMESTAMP_TAG = re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?\]")


@dataclass
class ValidationReport:
    total: int = 0
    kept: int = 0
    dropped: int = 0
    drops: list[dict] = None  # populated lazily

    def __post_init__(self):
        if self.drops is None:
            self.drops = []


def _normalize(text: str) -> str:
    text = text.translate(_PUNCT_NORMALIZE)
    text = _TIMESTAMP_TAG.sub(" ", text)  # strip [MM:SS] markers from transcript
    return _WS.sub(" ", text).strip().lower()


def _best_match_ratio(needle: str, haystack: str) -> float:
    """
    Slide a window the size of `needle` across `haystack` and return the best
    similarity ratio. We use SequenceMatcher.quick_ratio() as a cheap pre-filter,
    then ratio() for the candidates above a low bar.
    """
    if not needle or not haystack:
        return 0.0

    # If the needle text appears as a substring of haystack (after normalization),
    # it's a perfect match. This is the most common path.
    if needle in haystack:
        return 1.0

    # Otherwise slide a window. SequenceMatcher set_seq2 caches the haystack
    # autojunk computation; we only rebuild for seq1 each window.
    n = len(needle)
    best = 0.0
    matcher = SequenceMatcher(None, "", "", autojunk=False)
    matcher.set_seq2(needle)

    # Step through the haystack in 1/4-needle increments — small enough to catch
    # offset matches, big enough not to be O(N²).
    step = max(1, n // 4)
    for start in range(0, max(1, len(haystack) - n + 1), step):
        chunk = haystack[start:start + n]
        matcher.set_seq1(chunk)
        if matcher.real_quick_ratio() < 0.7:
            continue
        ratio = matcher.ratio()
        if ratio > best:
            best = ratio
            if best >= 1.0:
                break
    return best


def _seconds_to_offset(seconds: int, total_seconds: int, transcript_len: int) -> int:
    """Linear-interpolate a character offset into the transcript from a timestamp."""
    if total_seconds <= 0:
        return 0
    frac = max(0.0, min(1.0, seconds / total_seconds))
    return int(frac * transcript_len)


def _estimate_transcript_duration(transcript: str) -> int:
    """Find the largest [HH:MM:SS] or [MM:SS] timestamp in the transcript."""
    max_seconds = 0
    for match in _TIMESTAMP_TAG.finditer(transcript):
        tag = match.group(0).strip("[]")
        parts = tag.split(":")
        try:
            if len(parts) == 3:
                h, m, s = (int(p) for p in parts)
                total = h * 3600 + m * 60 + s
            elif len(parts) == 2:
                m, s = (int(p) for p in parts)
                total = m * 60 + s
            else:
                continue
        except ValueError:
            continue
        if total > max_seconds:
            max_seconds = total
    return max_seconds


def _validate_quote(quote: Quote, transcript: str, transcript_norm: str, duration_seconds: int) -> tuple[bool, float, str]:
    """
    Returns (is_valid, similarity_ratio, reason_for_drop).
    """
    if not quote.text:
        return False, 0.0, "empty_text"
    if not quote.context_excerpt:
        return False, 0.0, "empty_context_excerpt"

    needle = _normalize(quote.text)

    # If we have a timestamp and the transcript carries timestamps, restrict the
    # search to a ±TIMESTAMP_WINDOW_SECONDS window around the claimed location.
    # Otherwise fall back to whole-transcript search.
    if quote.timestamp_seconds is not None and duration_seconds > 0:
        center = _seconds_to_offset(quote.timestamp_seconds, duration_seconds, len(transcript_norm))
        # Window width in characters proportional to ±2 min of duration
        window_chars = int(len(transcript_norm) * (TIMESTAMP_WINDOW_SECONDS / duration_seconds))
        # Bound window to at least 2000 chars to handle very short transcripts
        window_chars = max(window_chars, 2000)
        start = max(0, center - window_chars)
        end = min(len(transcript_norm), center + window_chars)
        haystack = transcript_norm[start:end]
        # If the windowed search fails, retry against full transcript before giving up
        ratio = _best_match_ratio(needle, haystack)
        if ratio < SIMILARITY_THRESHOLD:
            full_ratio = _best_match_ratio(needle, transcript_norm)
            ratio = max(ratio, full_ratio)
    else:
        ratio = _best_match_ratio(needle, transcript_norm)

    if ratio >= SIMILARITY_THRESHOLD:
        return True, ratio, ""
    return False, ratio, f"similarity_below_threshold ({ratio:.2f})"


def _validate_list(quotes: list[Quote], transcript: str, transcript_norm: str, duration_seconds: int, source_label: str, report: ValidationReport) -> list[Quote]:
    kept: list[Quote] = []
    for q in quotes:
        report.total += 1
        ok, ratio, reason = _validate_quote(q, transcript, transcript_norm, duration_seconds)
        if ok:
            kept.append(q)
            report.kept += 1
        else:
            report.dropped += 1
            report.drops.append({
                "source": source_label,
                "speaker": q.speaker,
                "text_preview": q.text[:140],
                "timestamp_seconds": q.timestamp_seconds,
                "similarity": round(ratio, 3),
                "reason": reason,
            })
            log.warning(
                "Dropped quote from %s (%s): %s — speaker=%s, ts=%s, text=%r",
                source_label, reason, ratio, q.speaker, q.timestamp_seconds, q.text[:80],
            )
    return kept


def _validate_briefing(b: Briefing, transcript: str, transcript_norm: str, duration_seconds: int, report: ValidationReport) -> None:
    b.presenter_quotes = _validate_list(
        b.presenter_quotes, transcript, transcript_norm, duration_seconds,
        source_label=f"briefing:{b.topic[:40]}",
        report=report,
    )


def _validate_hearing(h: PublicHearingItem, transcript: str, transcript_norm: str, duration_seconds: int, report: ValidationReport) -> None:
    label = f"hearing:{h.what_is_being_heard[:40]}"
    h.city_staff_commentary = _validate_list(
        h.city_staff_commentary, transcript, transcript_norm, duration_seconds, f"{label}:city", report,
    )
    h.outside_party_commentary = _validate_list(
        h.outside_party_commentary, transcript, transcript_norm, duration_seconds, f"{label}:outside", report,
    )
    h.councilmember_commentary = _validate_list(
        h.councilmember_commentary, transcript, transcript_norm, duration_seconds, f"{label}:council", report,
    )
    h.public_commentary = _validate_list(
        h.public_commentary, transcript, transcript_norm, duration_seconds, f"{label}:public", report,
    )


def validate_quotes(analysis: MeetingAnalysis, transcript: str) -> ValidationReport:
    """
    Walk every Quote field in the analysis and drop those that fail to match
    the transcript. Mutates `analysis` in place and returns a ValidationReport.
    """
    transcript_norm = _normalize(transcript)
    duration = _estimate_transcript_duration(transcript)
    report = ValidationReport()

    if isinstance(analysis, BusinessAnalysis):
        for p in analysis.presentations:
            _validate_briefing(p, transcript, transcript_norm, duration, report)
        analysis.non_scheduled_public_comment = _validate_list(
            analysis.non_scheduled_public_comment, transcript, transcript_norm, duration,
            "non_scheduled_public_comment", report,
        )
        for h in analysis.public_hearings:
            _validate_hearing(h, transcript, transcript_norm, duration, report)
    elif isinstance(analysis, WorkshopAnalysis):
        for topic in analysis.workshop_topics:
            kept_positions = []
            for pos in topic.member_positions:
                # MemberPosition carries a single Quote
                report.total += 1
                ok, ratio, reason = _validate_quote(pos.quote, transcript, transcript_norm, duration)
                if ok:
                    kept_positions.append(pos)
                    report.kept += 1
                else:
                    report.dropped += 1
                    report.drops.append({
                        "source": f"workshop_position:{pos.name}",
                        "speaker": pos.quote.speaker,
                        "text_preview": pos.quote.text[:140],
                        "timestamp_seconds": pos.quote.timestamp_seconds,
                        "similarity": round(ratio, 3),
                        "reason": reason,
                    })
                    log.warning(
                        "Dropped workshop position (%s) for %s: %s — text=%r",
                        reason, pos.name, ratio, pos.quote.text[:80],
                    )
            topic.member_positions = kept_positions
    elif isinstance(analysis, StudyAnalysis):
        for b in analysis.briefings:
            _validate_briefing(b, transcript, transcript_norm, duration, report)
    else:
        log.warning("validate_quotes: unknown analysis type %s; skipping", type(analysis).__name__)

    log.info(
        "Quote validation: %d kept / %d dropped (of %d total)",
        report.kept, report.dropped, report.total,
    )
    return report
