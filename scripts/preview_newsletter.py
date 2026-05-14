"""
Local newsletter preview — render a saved dashboard JSON to HTML in /tmp.

Lets us iterate on the Jinja templates against real LLM output without burning
API calls or CI runs. The committed `dashboard/public/data/<city>/meetings/<date>.json`
files contain the full type_specific analysis, so we can rehydrate the
WorkshopAnalysis / BusinessAnalysis / StudyAnalysis dataclasses and feed them
straight to render_newsletter().

Usage:
    python scripts/preview_newsletter.py                        # latest workshop
    python scripts/preview_newsletter.py --date 2026-05-12      # specific meeting
    python scripts/preview_newsletter.py --city arvada --date 2026-05-12 --open
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.analyze_meeting import (  # noqa: E402
    MemberPosition,
    Quote,
    WorkshopAnalysis,
    WorkshopOption,
    WorkshopTopic,
)
from pipeline.render_newsletter import render_newsletter  # noqa: E402


def _quote_from(d: dict | None) -> Quote:
    if not d:
        return Quote()
    return Quote(
        speaker=d.get("speaker") or "Unidentified",
        text=d.get("text", ""),
        timestamp_seconds=d.get("timestamp_seconds"),
        context_excerpt=d.get("context_excerpt", ""),
        video_url=d.get("video_url"),
    )


def _rehydrate_workshop(ts: dict) -> WorkshopAnalysis:
    topics = []
    for t in ts.get("workshop_topics", []) or []:
        positions = []
        for mp in (t.get("member_positions") or []):
            status = (mp.get("status") or "aligned").strip().lower()
            if status not in ("aligned", "off_menu", "no_preference"):
                status = "aligned"
            positions.append(MemberPosition(
                name=mp.get("name", ""),
                status=status,
                option_preference=mp.get("option_preference", ""),
                off_menu_summary=mp.get("off_menu_summary", ""),
                quote=_quote_from(mp.get("quote")),
            ))
        topics.append(WorkshopTopic(
            title=t.get("title", ""),
            tagline=t.get("tagline", ""),
            lede=t.get("lede", ""),
            feeds_into=t.get("feeds_into", ""),
            options=[
                WorkshopOption(
                    number=int(o.get("number") or 0),
                    label=o.get("label", ""),
                    summary=o.get("summary", ""),
                    cost=o.get("cost", ""),
                    endorsement=o.get("endorsement", ""),
                )
                for o in (t.get("options") or [])
            ],
            member_positions=positions,
        ))
    return WorkshopAnalysis(
        meeting_summary=ts.get("meeting_summary", ""),
        lead_headline=ts.get("lead_headline", ""),
        meeting_purpose_blurb=ts.get("meeting_purpose_blurb", ""),
        members_present=[m for m in (ts.get("members_present") or []) if isinstance(m, str)],
        workshop_topics=topics,
    )


_REHYDRATORS = {
    "workshop": _rehydrate_workshop,
    # business/study added on demand — workshop is the active investigation target
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="arvada")
    ap.add_argument("--date", help="Meeting date YYYY-MM-DD; defaults to latest meeting")
    ap.add_argument("--out", default="/tmp/newsletter_preview.html")
    ap.add_argument("--open", action="store_true", help="Open the rendered HTML in your default browser")
    args = ap.parse_args()

    city_config = json.loads((REPO_ROOT / "config" / "cities" / f"{args.city}.json").read_text())

    meetings_dir = REPO_ROOT / "dashboard" / "public" / "data" / args.city / "meetings"
    if args.date:
        src = meetings_dir / f"{args.date}.json"
    else:
        candidates = sorted(meetings_dir.glob("*.json"))
        if not candidates:
            print(f"No meetings in {meetings_dir}", file=sys.stderr)
            return 1
        src = candidates[-1]
    if not src.exists():
        print(f"Not found: {src}", file=sys.stderr)
        return 1

    payload = json.loads(src.read_text())
    meeting_type = payload.get("meeting_type") or (payload.get("type_specific") or {}).get("meeting_type")
    rehydrate = _REHYDRATORS.get(meeting_type)
    if rehydrate is None:
        print(f"No rehydrator for meeting_type={meeting_type!r} yet", file=sys.stderr)
        return 2

    analysis = rehydrate(payload["type_specific"])
    meeting_date = datetime.fromisoformat(payload["meeting_date"]).replace(tzinfo=timezone.utc)
    rendered = render_newsletter(analysis, city_config, meeting_date)

    # Wrap in a minimal HTML doc so file-served previews aren't mis-decoded
    # as Latin-1 (Beehiiv ships its own wrapper in production, so this is
    # only for local viewing).
    wrapped = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<title>{rendered.subject}</title></head><body>'
        f'{rendered.body_html}'
        '</body></html>'
    )
    out = Path(args.out)
    out.write_text(wrapped, encoding="utf-8")
    print(f"Source:   {src.relative_to(REPO_ROOT)}")
    print(f"Type:     {meeting_type}")
    print(f"Subject:  {rendered.subject}")
    print(f"Written:  {out}  ({len(rendered.body_html):,} bytes)")
    if args.open:
        webbrowser.open(f"file://{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
