"""
Sends a meeting transcript to an LLM via OpenRouter and returns a structured analysis.

The analysis includes:
  - Meeting summary
  - Key decisions / votes (formal motions with roll-call)
  - Notable quotes with speaker attribution
  - Workshop topics with per-member positions (no formal vote, but options were debated)
  - Consistency flags
  - On-the-horizon and editor's note prompts

OpenRouter (https://openrouter.ai) gives us model flexibility — set city_config['llm']['model']
to anything OpenRouter exposes (anthropic/claude-sonnet-4.6, openai/gpt-4o, google/gemini-2.5-pro, etc).
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from openai import OpenAI


SYSTEM_PROMPT = """You are an expert civic journalist specializing in local government accountability.
Your job is to analyze city council meeting transcripts and produce clear, factual, non-partisan summaries
for a general public audience. You care about accuracy, attribution, and transparency.

When analyzing transcripts:
- Be precise about who said what. If speaker attribution is unclear from context, say so.
- Distinguish between motions that passed, failed, or were tabled.
- Note when a council member's stated position seems to diverge from their vote or prior statements.
- Distinguish between formal votes (motion + roll-call) and workshop discussions (no vote, but stances expressed).
- Use plain language. Avoid jargon. A resident with no government background should understand everything.
- Never editorialize or take political positions. Present facts and let readers draw conclusions.
"""

ANALYSIS_PROMPT = """Analyze the following city council meeting transcript for {city_name}, {state}.

COUNCIL MEMBERS:
{council_members}

TRANSCRIPT:
{transcript}

UPCOMING AGENDA / RSS CONTEXT:
{rss_context}

Please respond with a JSON object containing exactly these fields:

{{
  "meeting_summary": "2-3 paragraph plain-English summary of the meeting. What were the most important things that happened?",
  "lead_headline": "A single newspaper-style headline (under 80 chars) for the most consequential thing that happened. No clickbait.",
  "key_decisions": [
    {{
      "motion": "What was voted on",
      "result": "Passed / Failed / Tabled / No vote",
      "vote_breakdown": "e.g. 5-2, or 'unanimous', or 'voice vote'",
      "votes": {{
        "council_member_name": "Yes / No / Abstain / Absent / Excused"
      }},
      "significance": "1-2 sentences on why this matters"
    }}
  ],
  "notable_quotes": [
    {{
      "speaker": "Name or 'Unidentified council member'",
      "quote": "Exact or near-exact quote",
      "context": "Brief context for why this quote is notable",
      "timestamp_seconds": 3642
    }}
  ],
  "workshop_topics": [
    {{
      "title": "Short topic title (e.g., 'Composting program')",
      "tagline": "1-line subhed describing what was decided/landed on",
      "options": [
        {{
          "number": 1,
          "label": "Short name of the option",
          "cost": "$X/mo or 'Cost TBD' or 'Saves $X/mo'",
          "summary": "1-2 sentences explaining the option in plain language",
          "endorsement": "Who picked this — null, or a string like 'Moorman's pick' or 'Council pick'"
        }}
      ],
      "member_positions": [
        {{
          "name": "Council member's full name",
          "position": "1-line summary of their stance"
        }}
      ]
    }}
  ],
  "topics_discussed": ["list", "of", "policy", "topics"],
  "consistency_flags": [
    {{
      "council_member": "Name",
      "observation": "Description of potential inconsistency between what they said/voted vs prior statements"
    }}
  ],
  "on_the_horizon": "2-3 sentences on upcoming items from the RSS/agenda feeds worth watching",
  "editors_note_prompts": ["Suggested angles or follow-up questions for the editor to consider adding"]
}}

GUIDANCE:
- Include `workshop_topics` only when the meeting included substantive workshop/discussion items where multiple options were debated AND individual council members expressed positions, even if no formal vote was taken. If the meeting was all formal votes with no workshop, return an empty array.
- For each workshop_topic, capture every option that was on the table (numbered as council numbered them if possible — Option 1, Option 2, etc) AND every council member who spoke meaningfully on that topic.
- The transcript includes periodic timestamps in [MM:SS] or [HH:MM:SS] format. Use these to estimate `timestamp_seconds` for notable quotes (convert to total seconds). If a quote appears near [01:02:30], timestamp_seconds would be 3750. If you cannot estimate, use null.
- If you cannot confidently attribute a statement or vote to a specific person, use "Unidentified" rather than guessing.
- Return only valid JSON. Do not include markdown code fences or commentary."""


@dataclass
class MeetingAnalysis:
    meeting_summary: str = ""
    lead_headline: str = ""
    key_decisions: list[dict] = field(default_factory=list)
    notable_quotes: list[dict] = field(default_factory=list)
    workshop_topics: list[dict] = field(default_factory=list)
    topics_discussed: list[str] = field(default_factory=list)
    consistency_flags: list[dict] = field(default_factory=list)
    on_the_horizon: str = ""
    editors_note_prompts: list[str] = field(default_factory=list)
    raw_response: str = ""


def analyze_meeting(
    transcript: str,
    city_config: dict,
    rss_context: str = "",
    model: Optional[str] = None,
    video_id: str = "",
) -> MeetingAnalysis:
    """
    Send the transcript through OpenRouter and return a structured MeetingAnalysis.

    `model` defaults to city_config['llm']['model'], or 'anthropic/claude-sonnet-4.6'
    if not configured.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set. Get a key at https://openrouter.ai/keys")

    if model is None:
        model = city_config.get("llm", {}).get("model", "anthropic/claude-sonnet-4.6")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        default_headers={
            # OpenRouter rankings; harmless if omitted, helpful for tracking
            "HTTP-Referer": "https://github.com/semiagenticRob/civic-transparency-tool",
            "X-Title": "Civic Transparency Tool",
        },
    )

    council_members_text = "\n".join(
        f"- {m['name']} ({m['title']})"
        for m in city_config.get("council_members", [])
    ) or "Council members not configured — infer names from transcript."

    # Truncate very long transcripts to keep prompt under ~45k input tokens
    max_transcript_chars = 180_000
    if len(transcript) > max_transcript_chars:
        transcript = transcript[:max_transcript_chars] + "\n\n[TRANSCRIPT TRUNCATED]"

    prompt = ANALYSIS_PROMPT.format(
        city_name=city_config["name"],
        state=city_config["state"],
        council_members=council_members_text,
        transcript=transcript,
        rss_context=rss_context or "No RSS context available.",
    )

    response = client.chat.completions.create(
        model=model,
        max_tokens=4096,
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
        # Some models still wrap JSON in fences despite response_format
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            raise ValueError(f"Could not parse model response as JSON:\n{raw[:500]}")

    # Enrich quotes with YouTube deep-link URLs using timestamp_seconds
    quotes = data.get("notable_quotes", [])
    if video_id:
        for q in quotes:
            ts = q.get("timestamp_seconds")
            if isinstance(ts, (int, float)) and ts >= 0:
                q["video_url"] = f"https://www.youtube.com/watch?v={video_id}&t={int(ts)}s"

    return MeetingAnalysis(
        meeting_summary=data.get("meeting_summary", ""),
        lead_headline=data.get("lead_headline", ""),
        key_decisions=data.get("key_decisions", []),
        notable_quotes=quotes,
        workshop_topics=data.get("workshop_topics", []),
        topics_discussed=data.get("topics_discussed", []),
        consistency_flags=data.get("consistency_flags", []),
        on_the_horizon=data.get("on_the_horizon", ""),
        editors_note_prompts=data.get("editors_note_prompts", []),
        raw_response=raw,
    )
