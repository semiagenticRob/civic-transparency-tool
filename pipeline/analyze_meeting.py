"""
Sends a meeting transcript to an LLM via OpenRouter and returns a structured analysis.

This module supports three meeting types — business, workshop, and study_session —
each with its own prompt and dataclass tuned to that meeting's structure and
journalistic priorities.

OpenRouter (https://openrouter.ai) gives us model flexibility — set city_config['llm']['model']
to anything OpenRouter exposes (anthropic/claude-sonnet-4.6, openai/gpt-4o, etc).

The Quote dataclass is shared across all three meeting types and carries the
provenance fields a downstream validator needs: verbatim text, speaker,
timestamp_seconds, context_excerpt. See pipeline/validate_quotes.py.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Union

from openai import OpenAI

from .meeting_type import MeetingType


log = logging.getLogger(__name__)


_OPTION_PREFERENCE_RE = re.compile(r"^\s*option\s+(\d+)\s*$", re.IGNORECASE)


def _normalize_option_preference(raw: str, valid_numbers: set[int]) -> Optional[str]:
    """Return a canonical 'Option N' string if `raw` clearly maps to one of the
    topic's numbered options; otherwise None. Defends the workshop newsletter's
    short-label invariant against LLM drift (prose, parentheticals, compound
    phrases, off-menu actions).
    """
    if not raw:
        return None
    m = _OPTION_PREFERENCE_RE.match(raw)
    if not m:
        return None
    n = int(m.group(1))
    if valid_numbers and n not in valid_numbers:
        return None
    return f"Option {n}"


# ─────────────────────────────────────────────────────────────────────────────
# Shared dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Quote:
    """A single attributed quote with the provenance fields the validator needs."""
    speaker: str = "Unidentified"
    text: str = ""
    timestamp_seconds: Optional[int] = None
    context_excerpt: str = ""
    video_url: Optional[str] = None  # enriched after LLM call when video_id is known

    @classmethod
    def from_dict(cls, d: dict) -> "Quote":
        ts = d.get("timestamp_seconds")
        if isinstance(ts, str):
            try:
                ts = int(ts)
            except ValueError:
                ts = None
        return cls(
            speaker=d.get("speaker", "Unidentified") or "Unidentified",
            text=d.get("text", "") or d.get("quote", "") or "",
            timestamp_seconds=ts if isinstance(ts, int) else None,
            context_excerpt=d.get("context_excerpt", "") or d.get("context", "") or "",
        )


@dataclass
class ExternalResource:
    """A document, dataset, or external page referenced during the meeting."""
    title: str = ""
    url: str = ""
    kind: str = "external_page"  # report | dataset | agreement | memo | video_timestamp | external_page

    @classmethod
    def from_dict(cls, d: dict) -> "ExternalResource":
        return cls(
            title=d.get("title", ""),
            url=d.get("url", ""),
            kind=d.get("kind", "external_page"),
        )


@dataclass
class ItemLinks:
    """External links displayed beneath a consent/resolution/ordinance/hearing item."""
    agenda_packet_url: Optional[str] = None
    text_url: Optional[str] = None
    video_deep_link: Optional[str] = None
    calendar_url: Optional[str] = None  # first-reading ordinances only

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "ItemLinks":
        if not d:
            return cls()
        return cls(
            agenda_packet_url=d.get("agenda_packet_url") or None,
            text_url=d.get("text_url") or None,
            video_deep_link=d.get("video_deep_link") or None,
            calendar_url=d.get("calendar_url") or None,
        )


@dataclass
class MemberVote:
    name: str = ""
    vote: str = ""  # Yes | No | Abstain | Absent | Excused
    rationale: str = ""  # one-line summary of stated reasoning


@dataclass
class VoteBreakdown:
    motion_text: str = ""  # verbatim motion language
    result: str = ""  # Passed | Failed | Tabled
    tally: str = ""  # e.g. "5–1"


# ─────────────────────────────────────────────────────────────────────────────
# Business Meeting dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class GlanceBlock:
    synopsis: str = ""  # 1–2 line synopsis
    highlights: list[str] = field(default_factory=list)  # 3–5 bullet items


@dataclass
class AgendaItem:
    """Consent / resolution item. Carries verbatim agenda language + plain-English clarifier."""
    official_title: str = ""  # verbatim from agenda packet
    plain_english_summary: str = ""
    vote_tally: str = ""  # e.g. "PASSED 6–0", "REFERRED", "TABLED"
    dissent_excused: str = ""  # e.g. "Excused: Davis · No: Lovisone"
    links: ItemLinks = field(default_factory=ItemLinks)


@dataclass
class OrdinanceItem(AgendaItem):
    reading_number: int = 1  # 1 | 2 | 3
    coming_back_at: Optional[str] = None  # e.g. "Second reading May 19"


@dataclass
class PublicHearingItem:
    """The dominant element of a business-meeting newsletter."""
    what_is_being_heard: str = ""
    city_staff_commentary: list[Quote] = field(default_factory=list)
    outside_party_commentary: list[Quote] = field(default_factory=list)
    councilmember_commentary: list[Quote] = field(default_factory=list)
    public_commentary: list[Quote] = field(default_factory=list)
    vote_breakdown: VoteBreakdown = field(default_factory=VoteBreakdown)
    whip_count: list[MemberVote] = field(default_factory=list)
    follow_up_direction: Optional[str] = None
    links: ItemLinks = field(default_factory=ItemLinks)


@dataclass
class Briefing:
    """A presentation given to council (study session, or item 6 of a business meeting)."""
    topic: str = ""
    presenter_name: str = ""
    presenter_role: str = ""
    duration_minutes: Optional[int] = None
    prose_paragraphs: list[str] = field(default_factory=list)  # 2–3 paragraphs
    presenter_quotes: list[Quote] = field(default_factory=list)
    external_resources: list[ExternalResource] = field(default_factory=list)
    video_deep_link: Optional[str] = None


@dataclass
class BusinessAnalysis:
    meeting_type: MeetingType = "business"
    meeting_summary: str = ""
    lead_headline: str = ""
    meeting_purpose_blurb: str = ""
    tonight_at_a_glance: GlanceBlock = field(default_factory=GlanceBlock)
    presentations: list[Briefing] = field(default_factory=list)
    non_scheduled_public_comment: list[Quote] = field(default_factory=list)
    consent_agenda: list[AgendaItem] = field(default_factory=list)
    resolutions: list[AgendaItem] = field(default_factory=list)
    ordinances: list[OrdinanceItem] = field(default_factory=list)
    public_hearings: list[PublicHearingItem] = field(default_factory=list)
    raw_response: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Workshop dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class WorkshopOption:
    number: int = 0
    label: str = ""
    cost: str = ""
    summary: str = ""
    endorsement: Optional[str] = None


MemberPositionStatus = Literal["aligned", "off_menu", "no_preference"]


@dataclass
class MemberPosition:
    """A councilmember's stance on workshop options, with their actual words.

    status:
      - "aligned"        — leaned toward one of the topic's numbered options;
                           option_preference is "Option N" and quote is verbatim.
      - "off_menu"       — proposed a direction not in the options[] menu;
                           off_menu_summary holds a short noun phrase describing
                           it and quote is verbatim.
      - "no_preference"  — spoke about the topic but did not stake out a clear
                           preference (asked clarifying questions, etc.);
                           option_preference and off_menu_summary are empty and
                           quote is optional.
    """
    name: str = ""
    status: MemberPositionStatus = "aligned"
    option_preference: str = ""        # e.g. "Option 3" (only when status="aligned")
    off_menu_summary: str = ""         # short noun phrase (only when status="off_menu")
    quote: Quote = field(default_factory=Quote)


@dataclass
class WorkshopTopic:
    title: str = ""
    tagline: str = ""
    lede: str = ""
    options: list[WorkshopOption] = field(default_factory=list)
    member_positions: list[MemberPosition] = field(default_factory=list)
    feeds_into: str = ""  # which upcoming business meeting this likely surfaces in


@dataclass
class WorkshopAnalysis:
    meeting_type: MeetingType = "workshop"
    meeting_summary: str = ""
    lead_headline: str = ""
    meeting_purpose_blurb: str = ""
    members_present: list[str] = field(default_factory=list)  # roll call / who-spoke list
    workshop_topics: list[WorkshopTopic] = field(default_factory=list)
    raw_response: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Study Session dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class StudyAnalysis:
    meeting_type: MeetingType = "study_session"
    meeting_summary: str = ""
    lead_headline: str = ""
    meeting_purpose_blurb: str = ""
    briefings: list[Briefing] = field(default_factory=list)
    questions_raised: list[str] = field(default_factory=list)
    raw_response: str = ""


# Union for callers
MeetingAnalysis = Union[BusinessAnalysis, WorkshopAnalysis, StudyAnalysis]


# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────


SYSTEM_PROMPT = """You are an expert civic journalist specializing in local government accountability.
Your job is to analyze city council meeting transcripts and produce clear, factual, non-partisan summaries
for a general public audience. You care about accuracy, attribution, and transparency.

When analyzing transcripts:
- Be precise about who said what. If speaker attribution is unclear from context, label the speaker "Unidentified".
- Distinguish between formal votes (motion + roll-call), workshop discussions (no vote, but stances expressed),
  and study-session briefings (no decisions, presenters share information).
- Use plain language. Avoid jargon. A resident with no government background should understand everything.
- Never editorialize or take political positions. Present facts and let readers draw conclusions.
- Return only valid JSON. Do not include markdown code fences or commentary."""


# Shared quote-provenance instruction block embedded in every prompt.
# See memory/quote_provenance.md and pipeline/validate_quotes.py.
_QUOTE_PROVENANCE_BLOCK = """
QUOTE PROVENANCE — NON-NEGOTIABLE

Every Quote object you produce must satisfy ALL FOUR rules:

1. VERBATIM: The `text` field must be the speaker's words reproduced word-for-word from the transcript.
   Do not paraphrase inside quotation marks. Do not "clean up" the speaker's wording.
2. CORRECT SPEAKER: Attribute the quote only to the person who actually said it. If the transcript does not
   unambiguously identify the speaker, set `speaker` to "Unidentified". Never guess attribution.
3. TIMESTAMP: Include `timestamp_seconds` (total seconds, e.g. 3750 for [01:02:30]) of where the quote
   appears in the transcript.
4. CONTEXT EXCERPT: Include `context_excerpt` — 30 to 60 words of surrounding transcript text that contain
   the quote, so a downstream validator can verify the quote and a reader can see it in context.

If you cannot satisfy ALL FOUR rules for a candidate quote, OMIT it entirely. A missing quote is far better
than a misattributed or misquoted one. Quote errors damage the publication's credibility.
"""


ANALYSIS_PROMPT_BUSINESS = """Analyze the following CITY COUNCIL BUSINESS MEETING transcript for {city_name}, {state}.

Meeting purpose: {meeting_purpose_blurb}

COUNCIL MEMBERS:
{council_members}

TRANSCRIPT:
{transcript}

UPCOMING AGENDA / RSS CONTEXT:
{rss_context}

Arvada business meetings follow a fixed 12-item agenda. Items 1–4 (call to order, moment of reflection,
roll call, approval of minutes) are procedural — IGNORE them entirely.

Extract content in the following structure. Sections may be empty when nothing material occurred at that
agenda position, but never omit the field.

{{
  "meeting_summary": "2–3 sentence plain-English summary of the meeting.",
  "lead_headline": "Single newspaper-style headline (<80 chars) capturing the most consequential action.",
  "tonight_at_a_glance": {{
    "synopsis": "1–2 line synopsis of tonight's major actions.",
    "highlights": ["3–5 short bullet phrases summarizing the major actions"]
  }},
  "presentations": [
    {{
      "topic": "Short presentation title",
      "presenter_name": "Name",
      "presenter_role": "Title, organization",
      "duration_minutes": null,
      "prose_paragraphs": ["1 paragraph max — only when materially newsworthy"],
      "presenter_quotes": [{{ "speaker": "...", "text": "...", "timestamp_seconds": 0, "context_excerpt": "..." }}],
      "external_resources": [{{ "title": "...", "url": "", "kind": "report" }}],
      "video_deep_link": null
    }}
  ],
  "non_scheduled_public_comment": [
    {{ "speaker": "Name or 'Unidentified'", "text": "verbatim quote", "timestamp_seconds": 0, "context_excerpt": "..." }}
  ],
  "consent_agenda": [
    {{
      "official_title": "Verbatim agenda-packet language for this consent item",
      "plain_english_summary": "1–2 sentence clarifier in plain English",
      "vote_tally": "PASSED 6–0",
      "dissent_excused": "Excused: Davis",
      "links": {{ "agenda_packet_url": null, "text_url": null, "video_deep_link": null }}
    }}
  ],
  "resolutions": [
    {{
      "official_title": "Verbatim resolution language (e.g. 'A Resolution of the City Council ...')",
      "plain_english_summary": "1–2 sentence clarifier",
      "vote_tally": "PASSED 6–0",
      "dissent_excused": "Excused: Davis",
      "links": {{ "agenda_packet_url": null, "text_url": null, "video_deep_link": null }}
    }}
  ],
  "ordinances": [
    {{
      "official_title": "Verbatim ordinance language (e.g. 'Council Bill No. 25-014, Series 2025: An Ordinance ...')",
      "plain_english_summary": "1–2 sentence clarifier",
      "vote_tally": "PASSED 5–1 or REFERRED to second reading",
      "dissent_excused": "Excused: Davis · No: Lovisone",
      "reading_number": 1,
      "coming_back_at": "Second reading May 19" ,
      "links": {{ "agenda_packet_url": null, "text_url": null, "video_deep_link": null, "calendar_url": null }}
    }}
  ],
  "public_hearings": [
    {{
      "what_is_being_heard": "Full explanation of the matter under hearing, 2–4 sentences.",
      "city_staff_commentary": [Quote objects from staff/legal/city attorney],
      "outside_party_commentary": [Quote objects from applicants, attorneys, experts — empty array if none],
      "councilmember_commentary": [Quote objects from each member who spoke],
      "public_commentary": [Quote objects from residents who spoke at the hearing],
      "vote_breakdown": {{ "motion_text": "verbatim motion language", "result": "Passed", "tally": "4–2" }},
      "whip_count": [
        {{ "name": "Lauren Simpson", "vote": "Yes", "rationale": "One-line summary of stated reasoning" }}
      ],
      "follow_up_direction": "What council asked staff to do next, or null",
      "links": {{ "agenda_packet_url": null, "text_url": null, "video_deep_link": null }}
    }}
  ]
}}

PRIORITY GUIDANCE:
- Public Hearings (agenda item 10) is the BULK of the newsletter — extract every councilmember who spoke,
  every staff/legal voice, every outside party, and every resident who spoke during the hearing's public-comment
  window. Each gets a Quote object with full provenance.
- Consent agenda (item 8): reproduce the official_title VERBATIM from the agenda packet. Do not paraphrase
  inside this field — that's the source-of-truth language. The plain_english_summary is your own clarifier.
- Resolutions (item 9): same rule — official_title is verbatim, plain_english_summary is your clarifier.
- Ordinances (item 11): same rule. Set `reading_number` to 1, 2, or 3. For first-reading items, populate
  `coming_back_at` with the date phrase staff announced (e.g. "Second reading May 19"). For third-reading
  items, set coming_back_at to null.
- Recognitions, presentations, non-scheduled public comment (items 5–7): return empty arrays when nothing
  material happened. Don't pad.
- Do not expose agenda item numbers in any reader-facing text. The structure carries them.

{quote_provenance}
""".strip()


ANALYSIS_PROMPT_WORKSHOP = """Analyze the following CITY COUNCIL WORKSHOP transcript for {city_name}, {state}.

Meeting purpose: {meeting_purpose_blurb}

COUNCIL MEMBERS:
{council_members}

TRANSCRIPT:
{transcript}

UPCOMING AGENDA / RSS CONTEXT:
{rss_context}

A workshop is NOT a voting meeting. Council examines topics in depth but takes no formal votes.
Public comment is NOT taken at a workshop. Workshop discussion typically informs a future business
meeting where the same topic returns as a formal motion.

Extract content in the following structure:

{{
  "meeting_summary": "2–3 sentence plain-English summary of what was debated.",
  "lead_headline": "Single newspaper-style headline (<80 chars).",
  "members_present": ["Lauren Simpson", "Randy Moorman", "..."],
  "workshop_topics": [
    {{
      "title": "Short topic title (e.g. 'Solid Waste & Composting')",
      "tagline": "1-line subhed",
      "lede": "2–4 sentence intro explaining what staff brought forward and why.",
      "options": [
        {{
          "number": 1,
          "label": "Short name of the option",
          "cost": "$X/mo or 'Cost TBD'",
          "summary": "1–2 sentences explaining the option in plain language",
          "endorsement": "Who supported this, or null"
        }}
      ],
      "member_positions": [
        {{
          "name": "Councilmember name",
          "status": "aligned",
          "option_preference": "Option 3",
          "off_menu_summary": "",
          "quote": {{
            "speaker": "Same councilmember name",
            "text": "Their actual words — verbatim.",
            "timestamp_seconds": 0,
            "context_excerpt": "30–60 words of surrounding transcript"
          }}
        }}
      ],
      "feeds_into": "Which future business meeting this discussion likely surfaces in, e.g. 'Likely June 2 business meeting agenda', or empty string if unclear"
    }}
  ]
}}

PRIORITY GUIDANCE:
- DO NOT FABRICATE A VOTE. Workshops produce preferences, not votes. The member_positions field captures
  who leaned which way, in their own words. There is no "Yes/No" — only "leans toward Option X."
- Capture every option that staff or council put on the table, numbered as the meeting numbered them.
  Reproduce option labels and costs as they were stated. Do not invent numbers.

members_present field:
- List the full names of every councilmember who appears to be present at the meeting. Use a roll
  call if one was read; otherwise infer from who speaks during the transcript. Use the exact names
  from the COUNCIL MEMBERS list above. If you cannot determine presence, include the member's name
  here (defaulting to "present") — only OMIT a name if there is direct evidence the member was
  absent (e.g. another speaker said "Councilmember X is absent tonight" or the member sent regrets).

member_positions — every entry MUST have a `status` field that is one of these three values:

  "aligned" — the member clearly leaned toward one of the numbered options.
    - option_preference MUST be EXACTLY "Option N" where N is the integer number of one of the
      options in this topic's options[] array. No prose, no parentheticals, no compound labels.
    - off_menu_summary MUST be the empty string "".
    - quote MUST be a verbatim Quote object with the member's own reasoning.
    - Valid examples: "Option 1", "Option 2", "Option 5".
    - INVALID examples (do not produce these): "Option 3 (and tiered pricing)",
      "Support advisory group (Option 1) and promote autopay".

  "off_menu" — the member proposed a direction not in the options[] menu, or backed an orthogonal
  action staff did not put on the table.
    - option_preference MUST be the empty string "".
    - off_menu_summary MUST be a short noun phrase (≤ 60 characters, no trailing period) describing
      the direction. Examples: "Jefferson County mitigation crews", "Renewables for PSPS resilience",
      "Reporting on payment compliance and liens".
    - quote MUST be a verbatim Quote object with the member's own words.

  "no_preference" — the member spoke about the topic but did not stake out a clear preference.
  Use this when the member only asked clarifying questions, expressed support for multiple options
  without naming a primary, or commented procedurally.
    - option_preference and off_menu_summary MUST both be the empty string "".
    - quote is OPTIONAL. If you include one, it must be verbatim. Otherwise leave quote.text "".

- A member appears at most ONCE per topic in member_positions. If a member spoke about multiple
  options, pick the SINGLE most clearly-aligned option and use status "aligned"; otherwise prefer
  "off_menu" or "no_preference" over forcing a fit.
- Do NOT include members in member_positions just to fill out a roster. If a member did not speak
  about a given topic, simply omit them from that topic's member_positions; the newsletter renderer
  will mark them as "Did not weigh in" based on members_present.

{quote_provenance}
""".strip()


ANALYSIS_PROMPT_STUDY = """Analyze the following CITY COUNCIL STUDY SESSION transcript for {city_name}, {state}.

Meeting purpose: {meeting_purpose_blurb}

COUNCIL MEMBERS:
{council_members}

TRANSCRIPT:
{transcript}

UPCOMING AGENDA / RSS CONTEXT:
{rss_context}

A study session is an INFORMAL LEARNING SESSION. Council takes no formal votes and no public comment
is taken. Presenters share information to inform future workshop or business-meeting discussions.

Extract content in the following structure:

{{
  "meeting_summary": "2–3 sentence summary of what council learned about.",
  "lead_headline": "Single newspaper-style headline (<80 chars).",
  "briefings": [
    {{
      "topic": "Short topic title (e.g. 'Wildfire preparedness & FEMA grant deployment')",
      "presenter_name": "Name of the primary presenter",
      "presenter_role": "Their title and organization (e.g. 'Fire Chief, Arvada Fire Protection District')",
      "duration_minutes": 38,
      "prose_paragraphs": [
        "Paragraph 1: What was presented — the core content, methodology, headline numbers.",
        "Paragraph 2: The substantive detail — where the money goes, who is affected, what changes.",
        "Paragraph 3: Open issues — gaps, timelines, what comes next, what council asked for."
      ],
      "presenter_quotes": [
        {{
          "speaker": "Presenter name",
          "text": "Verbatim quote from the presentation",
          "timestamp_seconds": 0,
          "context_excerpt": "30–60 words of surrounding transcript"
        }}
      ],
      "external_resources": [
        {{ "title": "Full name of the document or dataset cited", "url": "", "kind": "report" }}
      ],
      "video_deep_link": null
    }}
  ],
  "questions_raised": [
    "One-line summaries of substantive questions council asked the presenter"
  ]
}}

PRIORITY GUIDANCE:
- DO NOT produce single-sentence "key facts" lines. Every briefing must carry 2–3 paragraphs of prose
  telling the fuller story. A single-paragraph briefing is a flag that something is wrong.
- `external_resources` is REQUIRED, not optional. Presenters almost always cite reports, datasets, agreements,
  or expert sources. Extract every one by full title. URLs may be empty if not discoverable in the transcript,
  but the title must be there so the resource can be linked later.
- Treat every briefing as a standalone presentation. Do NOT designate a "lead" — they are equals.
- `questions_raised` captures what council asked the presenter, in your own one-line summaries. These are
  not quotes; they're paraphrased questions for editorial use.

{quote_provenance}
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────────────────────────────────────


_PROMPT_BY_TYPE: dict[MeetingType, str] = {
    "business": ANALYSIS_PROMPT_BUSINESS,
    "workshop": ANALYSIS_PROMPT_WORKSHOP,
    "study_session": ANALYSIS_PROMPT_STUDY,
}


def analyze_meeting(
    transcript: str,
    city_config: dict,
    meeting_type: MeetingType,
    rss_context: str = "",
    model: Optional[str] = None,
    video_id: str = "",
) -> MeetingAnalysis:
    """
    Send the transcript through OpenRouter using the prompt for `meeting_type`
    and return the appropriate dataclass (BusinessAnalysis | WorkshopAnalysis |
    StudyAnalysis).
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set. Get a key at https://openrouter.ai/keys")

    if model is None:
        model = city_config.get("llm", {}).get("model", "anthropic/claude-sonnet-4.6")

    if meeting_type not in _PROMPT_BY_TYPE:
        raise ValueError(f"Unknown meeting_type {meeting_type!r}; expected one of {list(_PROMPT_BY_TYPE)}")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        default_headers={
            "HTTP-Referer": "https://github.com/semiagenticRob/civic-transparency-tool",
            "X-Title": "Civic Transparency Tool",
        },
    )

    council_members_text = "\n".join(
        f"- {m['name']} ({m['title']})"
        for m in city_config.get("council_members", [])
    ) or "Council members not configured — infer names from transcript."

    purpose_blurb = (
        city_config.get("meeting_purpose_blurbs", {}).get(meeting_type)
        or "Meeting purpose not configured in city config."
    )

    # Truncate very long transcripts to keep prompt under ~45k input tokens
    max_transcript_chars = 180_000
    if len(transcript) > max_transcript_chars:
        transcript = transcript[:max_transcript_chars] + "\n\n[TRANSCRIPT TRUNCATED]"

    prompt = _PROMPT_BY_TYPE[meeting_type].format(
        city_name=city_config["name"],
        state=city_config["state"],
        meeting_purpose_blurb=purpose_blurb,
        council_members=council_members_text,
        transcript=transcript,
        rss_context=rss_context or "No RSS context available.",
        quote_provenance=_QUOTE_PROVENANCE_BLOCK,
    )

    # Business meetings produce the largest payloads (public hearings × 4 commentary
    # sources × multiple quotes); give them more headroom. Workshop and study sessions
    # comfortably fit in 8k.
    max_tokens = 16384 if meeting_type == "business" else 8192

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )

    raw = (response.choices[0].message.content or "").strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            raise ValueError(f"Could not parse model response as JSON:\n{raw[:500]}")

    if meeting_type == "business":
        return _build_business(data, purpose_blurb, raw, video_id)
    elif meeting_type == "workshop":
        return _build_workshop(data, purpose_blurb, raw, video_id)
    else:
        return _build_study(data, purpose_blurb, raw, video_id)


# ─────────────────────────────────────────────────────────────────────────────
# Builders — turn parsed JSON into typed dataclasses, enrich quotes with video URLs
# ─────────────────────────────────────────────────────────────────────────────


def _enrich_quote(q: Quote, video_id: str) -> Quote:
    if video_id and q.timestamp_seconds is not None and q.timestamp_seconds >= 0:
        q.video_url = f"https://www.youtube.com/watch?v={video_id}&t={int(q.timestamp_seconds)}s"
    return q


def _quotes(items: Any, video_id: str) -> list[Quote]:
    if not isinstance(items, list):
        return []
    return [_enrich_quote(Quote.from_dict(q), video_id) for q in items if isinstance(q, dict)]


def _resources(items: Any) -> list[ExternalResource]:
    if not isinstance(items, list):
        return []
    return [ExternalResource.from_dict(r) for r in items if isinstance(r, dict)]


def _build_briefing(d: dict, video_id: str) -> Briefing:
    dur = d.get("duration_minutes")
    if isinstance(dur, str):
        try:
            dur = int(dur)
        except ValueError:
            dur = None
    return Briefing(
        topic=d.get("topic", ""),
        presenter_name=d.get("presenter_name", ""),
        presenter_role=d.get("presenter_role", ""),
        duration_minutes=dur if isinstance(dur, int) else None,
        prose_paragraphs=[p for p in d.get("prose_paragraphs", []) if isinstance(p, str)],
        presenter_quotes=_quotes(d.get("presenter_quotes"), video_id),
        external_resources=_resources(d.get("external_resources")),
        video_deep_link=d.get("video_deep_link") or None,
    )


def _build_agenda_item(d: dict) -> AgendaItem:
    return AgendaItem(
        official_title=d.get("official_title", ""),
        plain_english_summary=d.get("plain_english_summary", ""),
        vote_tally=d.get("vote_tally", ""),
        dissent_excused=d.get("dissent_excused", ""),
        links=ItemLinks.from_dict(d.get("links")),
    )


def _build_ordinance(d: dict) -> OrdinanceItem:
    reading = d.get("reading_number", 1)
    if isinstance(reading, str):
        try:
            reading = int(reading)
        except ValueError:
            reading = 1
    return OrdinanceItem(
        official_title=d.get("official_title", ""),
        plain_english_summary=d.get("plain_english_summary", ""),
        vote_tally=d.get("vote_tally", ""),
        dissent_excused=d.get("dissent_excused", ""),
        reading_number=reading if isinstance(reading, int) else 1,
        coming_back_at=d.get("coming_back_at") or None,
        links=ItemLinks.from_dict(d.get("links")),
    )


def _build_hearing(d: dict, video_id: str) -> PublicHearingItem:
    vb = d.get("vote_breakdown") or {}
    whip_raw = d.get("whip_count") or []
    whip: list[MemberVote] = []
    if isinstance(whip_raw, list):
        for w in whip_raw:
            if isinstance(w, dict):
                whip.append(MemberVote(
                    name=w.get("name", ""),
                    vote=w.get("vote", ""),
                    rationale=w.get("rationale", ""),
                ))
    return PublicHearingItem(
        what_is_being_heard=d.get("what_is_being_heard", ""),
        city_staff_commentary=_quotes(d.get("city_staff_commentary"), video_id),
        outside_party_commentary=_quotes(d.get("outside_party_commentary"), video_id),
        councilmember_commentary=_quotes(d.get("councilmember_commentary"), video_id),
        public_commentary=_quotes(d.get("public_commentary"), video_id),
        vote_breakdown=VoteBreakdown(
            motion_text=vb.get("motion_text", "") if isinstance(vb, dict) else "",
            result=vb.get("result", "") if isinstance(vb, dict) else "",
            tally=vb.get("tally", "") if isinstance(vb, dict) else "",
        ),
        whip_count=whip,
        follow_up_direction=d.get("follow_up_direction") or None,
        links=ItemLinks.from_dict(d.get("links")),
    )


def _build_business(data: dict, purpose_blurb: str, raw: str, video_id: str) -> BusinessAnalysis:
    glance_raw = data.get("tonight_at_a_glance") or {}
    glance = GlanceBlock(
        synopsis=glance_raw.get("synopsis", "") if isinstance(glance_raw, dict) else "",
        highlights=[h for h in (glance_raw.get("highlights", []) if isinstance(glance_raw, dict) else []) if isinstance(h, str)],
    )

    return BusinessAnalysis(
        meeting_type="business",
        meeting_summary=data.get("meeting_summary", ""),
        lead_headline=data.get("lead_headline", ""),
        meeting_purpose_blurb=purpose_blurb,
        tonight_at_a_glance=glance,
        presentations=[_build_briefing(p, video_id) for p in data.get("presentations", []) if isinstance(p, dict)],
        non_scheduled_public_comment=_quotes(data.get("non_scheduled_public_comment"), video_id),
        consent_agenda=[_build_agenda_item(c) for c in data.get("consent_agenda", []) if isinstance(c, dict)],
        resolutions=[_build_agenda_item(r) for r in data.get("resolutions", []) if isinstance(r, dict)],
        ordinances=[_build_ordinance(o) for o in data.get("ordinances", []) if isinstance(o, dict)],
        public_hearings=[_build_hearing(h, video_id) for h in data.get("public_hearings", []) if isinstance(h, dict)],
        raw_response=raw,
    )


def _build_workshop(data: dict, purpose_blurb: str, raw: str, video_id: str) -> WorkshopAnalysis:
    topics_raw = data.get("workshop_topics", []) or []
    topics: list[WorkshopTopic] = []
    for t in topics_raw:
        if not isinstance(t, dict):
            continue
        options = []
        for o in t.get("options", []) or []:
            if not isinstance(o, dict):
                continue
            num = o.get("number", 0)
            if isinstance(num, str):
                try:
                    num = int(num)
                except ValueError:
                    num = 0
            options.append(WorkshopOption(
                number=num if isinstance(num, int) else 0,
                label=o.get("label", ""),
                cost=o.get("cost", ""),
                summary=o.get("summary", ""),
                endorsement=o.get("endorsement") or None,
            ))
        valid_option_numbers = {o.number for o in options if o.number}
        positions = []
        seen_names: set[str] = set()
        for p in t.get("member_positions", []) or []:
            if not isinstance(p, dict):
                continue
            name = (p.get("name") or "").strip()
            if not name:
                continue
            position = _build_member_position(
                p, name, valid_option_numbers, t.get("title", ""), video_id,
            )
            if position is None:
                continue
            # One position per member per topic — keep the first.
            name_key = name.lower()
            if name_key in seen_names:
                log.info(
                    "Dropping duplicate member_position for %r on topic %r",
                    name, t.get("title", ""),
                )
                continue
            seen_names.add(name_key)
            positions.append(position)
        topics.append(WorkshopTopic(
            title=t.get("title", ""),
            tagline=t.get("tagline", ""),
            lede=t.get("lede", ""),
            options=options,
            member_positions=positions,
            feeds_into=t.get("feeds_into", ""),
        ))

    members_present = [
        m.strip() for m in (data.get("members_present") or [])
        if isinstance(m, str) and m.strip()
    ]

    return WorkshopAnalysis(
        meeting_type="workshop",
        meeting_summary=data.get("meeting_summary", ""),
        lead_headline=data.get("lead_headline", ""),
        meeting_purpose_blurb=purpose_blurb,
        members_present=members_present,
        workshop_topics=topics,
        raw_response=raw,
    )


def _build_member_position(
    raw: dict, name: str, valid_option_numbers: set[int], topic_title: str, video_id: str,
) -> Optional[MemberPosition]:
    """Validate one LLM-emitted member_position by its `status`. Returns None when
    the entry is malformed enough that it should be dropped entirely.

    Tolerates legacy entries that lack a `status` field by inferring it: a valid
    Option-N option_preference → "aligned"; anything else with a quote → drop with
    a warning (since the constrained prompt should not produce these).
    """
    status_raw = (raw.get("status") or "").strip().lower()
    pref_raw = (raw.get("option_preference") or "").strip()
    summary_raw = (raw.get("off_menu_summary") or "").strip()
    q_raw = raw.get("quote") or {}
    quote = Quote.from_dict(q_raw) if isinstance(q_raw, dict) else Quote()
    _enrich_quote(quote, video_id)

    # Legacy / missing status — fall back to inferring from option_preference.
    if not status_raw:
        normalized = _normalize_option_preference(pref_raw, valid_option_numbers)
        if normalized is not None:
            return MemberPosition(
                name=name, status="aligned",
                option_preference=normalized, off_menu_summary="", quote=quote,
            )
        log.info(
            "Dropping member_position for %r on topic %r: no status and option_preference %r "
            "could not normalize", name, topic_title, pref_raw,
        )
        return None

    if status_raw == "aligned":
        normalized = _normalize_option_preference(pref_raw, valid_option_numbers)
        if normalized is None:
            log.info(
                "Dropping member_position for %r on topic %r: status=aligned but "
                "option_preference %r is not a valid Option N",
                name, topic_title, pref_raw,
            )
            return None
        if not (quote.text or "").strip():
            log.info(
                "Dropping member_position for %r on topic %r: status=aligned requires a quote",
                name, topic_title,
            )
            return None
        return MemberPosition(
            name=name, status="aligned",
            option_preference=normalized, off_menu_summary="", quote=quote,
        )

    if status_raw == "off_menu":
        # Truncate summary to a noun-phrase-sized blurb; drop if absent.
        summary = summary_raw[:80].rstrip(". ").strip()
        if not summary:
            log.info(
                "Dropping off_menu position for %r on topic %r: empty off_menu_summary",
                name, topic_title,
            )
            return None
        if not (quote.text or "").strip():
            log.info(
                "Dropping off_menu position for %r on topic %r: missing quote",
                name, topic_title,
            )
            return None
        return MemberPosition(
            name=name, status="off_menu",
            option_preference="", off_menu_summary=summary, quote=quote,
        )

    if status_raw == "no_preference":
        # Quote optional; clear option_preference and off_menu_summary defensively.
        return MemberPosition(
            name=name, status="no_preference",
            option_preference="", off_menu_summary="", quote=quote,
        )

    log.info(
        "Dropping member_position for %r on topic %r: unknown status %r",
        name, topic_title, status_raw,
    )
    return None


def _build_study(data: dict, purpose_blurb: str, raw: str, video_id: str) -> StudyAnalysis:
    return StudyAnalysis(
        meeting_type="study_session",
        meeting_summary=data.get("meeting_summary", ""),
        lead_headline=data.get("lead_headline", ""),
        meeting_purpose_blurb=purpose_blurb,
        briefings=[_build_briefing(b, video_id) for b in data.get("briefings", []) if isinstance(b, dict)],
        questions_raised=[q for q in data.get("questions_raised", []) if isinstance(q, str)],
        raw_response=raw,
    )
