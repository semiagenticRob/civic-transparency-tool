# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo shape

Two coupled apps share one repo:

- **Python pipeline** (root + `pipeline/`) — fetches a YouTube council-meeting transcript, fetches city RSS feeds, sends both to Claude, and emits (a) a Markdown newsletter draft in `output/` and (b) a JSON payload the dashboard reads.
- **React dashboard** (`dashboard/`) — Vite + React 19 + Tailwind. Reads `dashboard/public/data/<city-slug>/latest.json` as a static file. No backend; the pipeline writes directly into `dashboard/public/data/`.

The pipeline is the single source of truth for dashboard content. There is no API — JSON files on disk are the contract.

## Common commands

Python pipeline (run from repo root, with `.venv` activated):

```bash
# Generate a draft + dashboard data for one meeting
python run_pipeline.py <youtube_url_or_video_id> --city arvada [--date YYYY-MM-DD]

# Skip RSS fetch (useful when feeds are flaky and you only want analysis)
python run_pipeline.py <video> --city arvada --skip-rss
```

Outputs: `output/<city>_<date>.md` (Markdown draft), `dashboard/public/data/<city-slug>/latest.json` (overwritten each run), `dashboard/public/data/<city-slug>/meetings/<date>.json` (archive).

Dashboard (run from `dashboard/`):

```bash
npm run dev      # Vite dev server
npm run build    # Production build to dashboard/dist
npm run lint     # ESLint
```

There is no test suite. There are no Python lint/format tools configured.

## Pipeline architecture

`run_pipeline.py` is a Click CLI that orchestrates five steps in order; each step is a separate module in `pipeline/`:

1. `fetch_transcript.py` — YouTube → segments + plain text. `format_with_timestamps()` injects `[MM:SS]` markers so Claude can attribute quotes to timestamps.
2. `fetch_rss.py` — Pulls all feeds listed in the city config in parallel; `format_for_prompt()` flattens them into a string for the LLM prompt.
3. `analyze_meeting.py` — One Claude call (`claude-sonnet-4-6`, 4096 max tokens). Returns a `MeetingAnalysis` dataclass parsed from a strict JSON schema. Transcripts > 180k chars are truncated. After parsing, each notable quote is enriched with a `video_url` deep link (`?t=<timestamp_seconds>s`).
4. `generate_draft.py` — Renders the Markdown newsletter draft.
5. `save_dashboard_data.py` — Serializes the analysis to `latest.json` + an archive copy. `enrich_with_rss()` then merges feed data (`recent_news`, `upcoming`, `alerts`) into the same payload.

Imports inside the steps are intentionally lazy (`from pipeline.X import Y` inside `main()`) so a failure in one module's dependencies doesn't break CLI startup.

## City config

Cities are JSON files in `config/cities/<slug>.json`. Adding a city = copy `arvada.json`, change `name`, `state`, `youtube_channel_handle`, `rss_feeds`, and `council_members` (each member has `name`, `title`, `district`, `profile_url`). The `name` is lowercased + spaces→hyphens to derive the dashboard `city_slug`. `--city` matches the filename stem.

`profile_url` propagates two ways: into `council_members[]` on the payload, and into each notable quote as `speaker_profile_url` when the speaker matches a configured member name.

## Dashboard architecture

Single-page React app. `App.jsx` hardcodes `CITY = "arvada"` and fetches `/data/${CITY}/latest.json` on mount. Components in `src/components/` each render one section of the payload (alerts, summary, votes, quotes, council grid, sidebar). Tailwind for styling.

When adding a field to the dashboard, the change spans both sides: extend the payload in `pipeline/save_dashboard_data.py` (and `analyze_meeting.py` if it's LLM-derived) and consume it in the relevant React component.

## Conventions

- Claude is asked to return raw JSON only; `analyze_meeting.py` has a regex fallback for when it returns a fenced block anyway. If you change the prompt schema in `ANALYSIS_PROMPT`, also update the `MeetingAnalysis` dataclass and the dashboard payload shape.
- Speaker attribution: the prompt instructs Claude to use `"Unidentified"` rather than guess. Preserve that — downstream UI relies on it.
- `output/` and `.env` are gitignored; `dashboard/public/data/` is committed (dashboard ships its data).
- Default model is pinned in `analyze_meeting.py` (`model: str = "claude-sonnet-4-6"`).
