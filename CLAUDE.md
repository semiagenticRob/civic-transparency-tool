# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo shape

Three coupled apps share one repo:

- **Python pipeline** (root + `pipeline/`) — fetches a YouTube council-meeting transcript, fetches city RSS feeds, sends both to an LLM via OpenRouter, and emits (a) a Markdown draft in `output/`, (b) inline-styled HTML for Beehiiv via `render_newsletter.py`, and (c) a JSON payload the dashboard reads.
- **Automation layer** (`automation/`) — scheduled monitor that polls the city's CivicClerk calendar + YouTube playlist, runs the pipeline for new meeting videos, posts a draft to Beehiiv, emails the editor, and commits state. Driven by `.github/workflows/monitor.yml`.
- **React dashboard** (`dashboard/`) — Vite + React 19 + Tailwind. Reads `dashboard/public/data/<city-slug>/latest.json` as a static file. No backend; the pipeline writes directly into `dashboard/public/data/`.

The pipeline is the single source of truth for both dashboard data and newsletter content. There is no API — JSON files on disk are the contract.

## Common commands

Python pipeline (run from repo root, with `.venv` activated and `OPENROUTER_API_KEY` set):

```bash
# Manual one-off: generate a Markdown draft + dashboard data for one meeting
python run_pipeline.py <youtube_url_or_video_id> --city arvada [--date YYYY-MM-DD]

# Automation entry point: same pipeline + Beehiiv draft post + editor email
python -m automation.monitor                              # process new playlist videos
python -m automation.monitor --dry-run                    # render HTML to /tmp, no publish/email
python -m automation.monitor --video-id <id>              # force-process one video
```

Outputs: `output/<city>_<date>.md` (Markdown draft, manual flow), `dashboard/public/data/<city-slug>/latest.json` (overwritten each run), `dashboard/public/data/<city-slug>/meetings/<date>.json` (archive), Beehiiv draft post (automation flow).

Dashboard (run from `dashboard/`):

```bash
npm run dev      # Vite dev server
npm run build    # Production build to dashboard/dist
npm run lint     # ESLint
```

There is no test suite. There are no Python lint/format tools configured.

## Pipeline architecture

`run_pipeline.py` is the manual Click CLI; `automation.orchestrator.run_for_video()` is the headless equivalent used by the scheduled monitor. Both walk the same modules in `pipeline/`:

1. `fetch_transcript.py` — YouTube → segments + plain text. Picks **SocialKit** (hosted, residential egress) when `SOCIALKIT_API_KEY` is set, otherwise falls back to **yt-dlp** locally (`YT_COOKIES_FILE` optional). CI uses SocialKit because yt-dlp typically gets blocked from GitHub Actions' data-center IPs. `format_with_timestamps()` injects `[MM:SS]` markers so the LLM can attribute quotes to timestamps.
2. `meeting_type.py` — Classifies the meeting as **business / workshop / study_session** from the video title (longest-keyword-wins) before the LLM call. Drives which prompt + template + dataclass to use downstream.
3. `fetch_rss.py` — Pulls all feeds listed in the city config in parallel; `format_for_prompt()` flattens them into a string for the LLM prompt.
4. `analyze_meeting.py` — One **OpenRouter** call (model selectable via `city_config["llm"]["model"]`, default `anthropic/claude-sonnet-4.6`). Uses `openai` SDK pointed at `https://openrouter.ai/api/v1`. **Three prompts** — `ANALYSIS_PROMPT_BUSINESS`, `ANALYSIS_PROMPT_WORKSHOP`, `ANALYSIS_PROMPT_STUDY` — each returns its own dataclass (`BusinessAnalysis` / `WorkshopAnalysis` / `StudyAnalysis`). Every `Quote` carries provenance fields (verbatim text, speaker, timestamp_seconds, context_excerpt). The shared quote-provenance instruction block is embedded in every prompt.
5. `validate_quotes.py` — Runs after `analyze_meeting()`. Fuzzy-matches each quote against the transcript within ±2 min of its claimed timestamp; drops quotes that fail similarity ≥ 0.92. Returns a `ValidationReport` with kept/dropped counts. See `memory/quote_provenance.md`.
6. `render_newsletter.py` — Jinja2 + inline-CSS HTML. Dispatches by `analysis.meeting_type` to one of three templates: `newsletter_business.html.j2`, `newsletter_workshop.html.j2`, `newsletter_study.html.j2`. Shared partials in `_masthead.html.j2`, `_purpose_strip.html.j2`, `_footer.html.j2`, `_business_item.html.j2`. Canonical visual spec is in `docs/design/dashboard.pen` (one frame per meeting type).
7. `generate_draft.py` — Markdown summary, dispatches by meeting type. Used by the manual CLI as a skim-readable preview alongside the rendered HTML.
8. `save_dashboard_data.py` — Serializes to `latest.json` + an archive copy. Always emits `meeting_type`, `meeting_purpose_blurb`, `schedule_portal_url`, and a `type_specific` block with the full typed analysis. **Legacy-compat fields** (`key_decisions`, `notable_quotes`, `topics_discussed`) are derived so the existing dashboard UI keeps rendering. `enrich_with_rss()` merges feed data into the same payload.

Imports inside the manual orchestrator are intentionally lazy (`from pipeline.X import Y` inside `main()`) so a failure in one module's dependencies doesn't break CLI startup.

## Automation layer

`automation/` contains the unattended pipeline that runs on a schedule:

- `civicclerk.py` — public OData client for `https://{subdomain}.api.civicclerk.com/v1/Events` (no auth)
- `youtube_monitor.py` — parses `https://www.youtube.com/feeds/videos.xml?playlist_id=<id>` (no auth)
- `state.py` — loads/saves `state/processed.json` (committed back by CI to avoid re-processing videos)
- `orchestrator.py` — headless pipeline runner; same as `run_pipeline.py` but returns the `RunResult` instead of writing Markdown
- `beehiiv.py` — POST to `https://api.beehiiv.com/v2/publications/{id}/posts` with `status: "draft"`
- `notifier.py` — Resend API email to `NOTIFY_EMAIL` with the Beehiiv draft URL
- `monitor.py` — entry point (`python -m automation.monitor`)

Triggered by `.github/workflows/monitor.yml` every 6 hours. Required repo secrets: `OPENROUTER_API_KEY`, `BEEHIIV_API_KEY`, `BEEHIIV_PUBLICATION_ID`, `RESEND_API_KEY`, `NOTIFY_EMAIL`, plus `SOCIALKIT_API_KEY` (transcript backend on CI) and optional `YT_COOKIES` (yt-dlp fallback).

## City config

Cities are JSON files in `config/cities/<slug>.json`. Adding a city = copy `arvada.json`, change `name`, `state`, `youtube_channel_handle`, `youtube_playlist_id`, `civicclerk` block, `rss_feeds`, `newsletter` block, `council_members`, **`meeting_type_keywords`** (maps each meeting type to title-keyword patterns), **`meeting_purpose_blurbs`** (verbatim purpose text from the city's website, one per meeting type), and **`schedule_portal_url`** (the city's upcoming-meeting portal). The `name` is lowercased + spaces→hyphens to derive the dashboard `city_slug`. `--city` matches the filename stem.

Photos go in `docs/design/assets/council/<photo_filename>`; the renderer references them via `newsletter.photo_base_url` (default: GitHub raw URLs from this repo).

`profile_url` propagates two ways: into `council_members[]` on the payload, and into each notable quote as `speaker_profile_url` when the speaker matches a configured member name.

## Dashboard architecture

Single-page React app. `App.jsx` hardcodes `CITY = "arvada"` and fetches `/data/${CITY}/latest.json` on mount. Components in `src/components/` each render one section of the payload (alerts, summary, votes, quotes, council grid, sidebar). Tailwind for styling.

When adding a field to the dashboard, the change spans both sides: extend the payload in `pipeline/save_dashboard_data.py` (and `analyze_meeting.py` if it's LLM-derived) and consume it in the relevant React component.

## Conventions

- The LLM is asked to return raw JSON via `response_format={"type": "json_object"}`; `analyze_meeting.py` keeps a regex fallback for models that wrap output in fences anyway. If you change the schema in any `ANALYSIS_PROMPT_*`, also update the corresponding dataclass (`BusinessAnalysis` / `WorkshopAnalysis` / `StudyAnalysis`) and the matching Jinja template.
- Speaker attribution: every prompt instructs the LLM to use `"Unidentified"` rather than guess. Preserve that — downstream UI and the quote validator rely on it.
- **Quote provenance is non-negotiable**: every `Quote` object carries verbatim text + speaker + timestamp_seconds + context_excerpt; `validate_quotes.py` drops quotes that fail to fuzzy-match the transcript at ≥ 0.92 similarity. See `memory/quote_provenance.md`.
- **No agenda item numbers in reader-facing copy** — section kickers describe content ("PUBLIC HEARINGS", "NEW BUSINESS"), not agenda position. See `memory/business_meeting_agenda_structure.md`.
- `output/`, `.env`, and `__pycache__/` are gitignored; `dashboard/public/data/` is committed (dashboard ships its data); `state/processed.json` is committed (CI updates it).
- Model is config-driven via `city_config["llm"]["model"]` (default `anthropic/claude-sonnet-4.6`). Switching providers (Claude → GPT → Gemini) is a one-line config change because we use OpenRouter as a unified API.
- Newsletter HTML must use **inline styles only** — Beehiiv strips `<style>` and `<link>` tags during draft import.
