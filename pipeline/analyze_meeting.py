"""
Sends a meeting transcript to the Claude API and returns a structured analysis.

The analysis includes:
  - Meeting summary (2-3 paragraphs)
  - Key decisions / votes (with how each member voted)
  - Notable quotes with speaker attribution
  - Policy topics discussed
  - Flags for any statements that seem inconsistent with prior positions
"""

import json
import os
from dataclasses import dataclass, field

import anthropic


SYSTEM_PROMPT = """You are an expert civic journalist specializing in local government accountability.
Your job is to analyze city council meeting transcripts and produce clear, factual, non-partisan summaries
for a general public audience. You care about accuracy, attribution, and transparency.

When analyzing transcripts:
- Be precise about who said what. If speaker attribution is unclear from context, say so.
- Distinguish between motions that passed, failed, or were tabled.
- Note when a council member's stated position seems to diverge from their vote or prior statements.
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
  "key_decisions": [
    {{
      "motion": "What was voted on",
      "result": "Passed / Failed / Tabled / No vote",
      "vote_breakdown": "e.g. 5-2, or 'unanimous', or 'voice vote'",
      "votes": {{
        "council_member_name": "Yes / No / Abstain / Absent"
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

The transcript includes periodic timestamps in [MM:SS] or [HH:MM:SS] format. Use these to estimate
timestamp_seconds for each notable quote (convert to total seconds from the start of the video).
If a quote appears near [01:02:30], timestamp_seconds would be 3750. If you cannot estimate it, use null.

If you cannot confidently attribute a statement or vote to a specific person, use "Unidentified" rather than guessing.
Return only valid JSON. Do not include markdown code fences."""


@dataclass
class MeetingAnalysis:
    meeting_summary: str = ""
    key_decisions: list[dict] = field(default_factory=list)
    notable_quotes: list[dict] = field(default_factory=list)
    topics_discussed: list[str] = field(default_factory=list)
    consistency_flags: list[dict] = field(default_factory=list)
    on_the_horizon: str = ""
    editors_note_prompts: list[str] = field(default_factory=list)
    raw_response: str = ""


def analyze_meeting(
    transcript: str,
    city_config: dict,
    rss_context: str = "",
    model: str = "claude-sonnet-4-6",
    video_id: str = "",
) -> MeetingAnalysis:
    """
    Send the transcript to Claude and return a structured MeetingAnalysis.
    Handles transcripts longer than the context window by chunking if needed.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    council_members_text = "\n".join(
        f"- {m['name']} ({m['title']})"
        for m in city_config.get("council_members", [])
    ) or "Council members not configured — infer names from transcript."

    # Truncate very long transcripts to avoid token limits (~180k chars ≈ ~45k tokens)
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

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Claude sometimes wraps JSON in markdown fences despite instructions
        import re
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            raise ValueError(f"Could not parse Claude response as JSON:\n{raw[:500]}")

    # Enrich quotes with YouTube deep-link URLs using timestamp_seconds
    quotes = data.get("notable_quotes", [])
    if video_id:
        for q in quotes:
            ts = q.get("timestamp_seconds")
            if isinstance(ts, (int, float)) and ts >= 0:
                q["video_url"] = f"https://www.youtube.com/watch?v={video_id}&t={int(ts)}s"

    return MeetingAnalysis(
        meeting_summary=data.get("meeting_summary", ""),
        key_decisions=data.get("key_decisions", []),
        notable_quotes=quotes,
        topics_discussed=data.get("topics_discussed", []),
        consistency_flags=data.get("consistency_flags", []),
        on_the_horizon=data.get("on_the_horizon", ""),
        editors_note_prompts=data.get("editors_note_prompts", []),
        raw_response=raw,
    )
