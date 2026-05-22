"""
Pydantic schemas for LLM responses.

These models act as a **validation gate** at the LLM boundary: the parsed JSON
must satisfy the schema before we build typed dataclasses. Schema drift (a
renamed key, a wrong type, a missing required field) fails loudly with a
clear `ValidationError` instead of silently producing partially-populated
dataclasses downstream.

Models are deliberately forgiving (`extra="allow"`) so the LLM can return
additional keys without breaking the pipeline. Field aliases on Quote
canonicalize the two shapes the LLM has been known to emit: `text`/`quote`
and `context_excerpt`/`context`.

After validation, callers `.model_dump(by_alias=False)` to get a canonical
dict (aliased keys remapped to the field name) and pass that into the
existing `_build_*` helpers in `analyze_meeting`.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class _LooseBase(BaseModel):
    """Common base: allow unknown keys (LLM may emit extras)."""
    model_config = ConfigDict(extra="allow")


# ─────────────────────────────────────────────────────────────────────────────
# Shared sub-schemas
# ─────────────────────────────────────────────────────────────────────────────


class _QuoteSchema(_LooseBase):
    """A single attributed quote.

    The LLM has been observed to emit either `text` or `quote` for the
    verbatim text, and either `context_excerpt` or `context` for the
    surrounding passage. Aliases canonicalize both shapes into `text` /
    `context_excerpt` after validation.
    """
    speaker: str = "Unidentified"
    text: str = Field(
        default="",
        validation_alias=AliasChoices("text", "quote"),
    )
    timestamp_seconds: Optional[int] = None
    context_excerpt: str = Field(
        default="",
        validation_alias=AliasChoices("context_excerpt", "context"),
    )


class _ExternalResourceSchema(_LooseBase):
    title: str = ""
    url: str = ""
    kind: str = "external_page"


class _ItemLinksSchema(_LooseBase):
    agenda_packet_url: Optional[str] = None
    text_url: Optional[str] = None
    video_deep_link: Optional[str] = None
    calendar_url: Optional[str] = None


class _MemberVoteSchema(_LooseBase):
    name: str = ""
    vote: str = ""
    rationale: str = ""


class _VoteBreakdownSchema(_LooseBase):
    motion_text: str = ""
    result: str = ""
    tally: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Business meeting
# ─────────────────────────────────────────────────────────────────────────────


class _GlanceSchema(_LooseBase):
    synopsis: str = ""
    highlights: list[str] = []


class _AgendaItemSchema(_LooseBase):
    official_title: str = ""
    plain_english_summary: str = ""
    vote_tally: str = ""
    dissent_excused: str = ""
    links: _ItemLinksSchema = _ItemLinksSchema()


class _OrdinanceSchema(_AgendaItemSchema):
    reading_number: int = 1
    coming_back_at: Optional[str] = None


class _PublicHearingSchema(_LooseBase):
    what_is_being_heard: str = ""
    city_staff_commentary: list[_QuoteSchema] = []
    outside_party_commentary: list[_QuoteSchema] = []
    councilmember_commentary: list[_QuoteSchema] = []
    public_commentary: list[_QuoteSchema] = []
    vote_breakdown: _VoteBreakdownSchema = _VoteBreakdownSchema()
    whip_count: list[_MemberVoteSchema] = []
    follow_up_direction: Optional[str] = None
    links: _ItemLinksSchema = _ItemLinksSchema()


class _BriefingSchema(_LooseBase):
    topic: str = ""
    presenter_name: str = ""
    presenter_role: str = ""
    duration_minutes: Optional[int] = None
    prose_paragraphs: list[str] = []
    presenter_quotes: list[_QuoteSchema] = []
    external_resources: list[_ExternalResourceSchema] = []
    video_deep_link: Optional[str] = None


class BusinessSchema(_LooseBase):
    """Top-level schema for a business-meeting LLM response."""
    meeting_summary: str
    lead_headline: str
    tonight_at_a_glance: _GlanceSchema = _GlanceSchema()
    presentations: list[_BriefingSchema] = []
    non_scheduled_public_comment: list[_QuoteSchema] = []
    consent_agenda: list[_AgendaItemSchema] = []
    resolutions: list[_AgendaItemSchema] = []
    ordinances: list[_OrdinanceSchema] = []
    public_hearings: list[_PublicHearingSchema] = []


# ─────────────────────────────────────────────────────────────────────────────
# Workshop
# ─────────────────────────────────────────────────────────────────────────────


class _WorkshopOptionSchema(_LooseBase):
    number: int = 0
    label: str = ""
    cost: str = ""
    summary: str = ""
    endorsement: Optional[str] = None


class _MemberPositionSchema(_LooseBase):
    name: str = ""
    status: str = "aligned"
    option_preference: str = ""
    off_menu_summary: str = ""
    quote: _QuoteSchema = _QuoteSchema()


class _WorkshopTopicSchema(_LooseBase):
    title: str = ""
    tagline: str = ""
    lede: str = ""
    options: list[_WorkshopOptionSchema] = []
    member_positions: list[_MemberPositionSchema] = []
    feeds_into: str = ""


class WorkshopSchema(_LooseBase):
    meeting_summary: str
    lead_headline: str
    members_present: list[str] = []
    workshop_topics: list[_WorkshopTopicSchema]


# ─────────────────────────────────────────────────────────────────────────────
# Study session
# ─────────────────────────────────────────────────────────────────────────────


class StudySchema(_LooseBase):
    meeting_summary: str
    lead_headline: str
    briefings: list[_BriefingSchema]
    questions_raised: list[str] = []


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────────────────────────────────────


_SCHEMA_BY_TYPE: dict[str, type[_LooseBase]] = {
    "business": BusinessSchema,
    "workshop": WorkshopSchema,
    "study_session": StudySchema,
}


def validate_and_normalize(meeting_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Validate `data` against the schema for `meeting_type`.

    Returns a canonicalized dict (aliased Quote keys remapped to `text` and
    `context_excerpt`) ready to feed into the existing `_build_*` helpers.
    Raises `pydantic.ValidationError` on schema drift — caller decides how
    to surface that to the user.
    """
    schema = _SCHEMA_BY_TYPE.get(meeting_type)
    if schema is None:
        raise ValueError(
            f"Unknown meeting_type {meeting_type!r}; expected one of {list(_SCHEMA_BY_TYPE)}"
        )
    model = schema.model_validate(data)
    return model.model_dump(by_alias=False)
