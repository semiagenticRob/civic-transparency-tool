# Civic Transparency Tool

AI-assisted local government accountability. Watches city council meetings so your community doesn't have to.

## What it does

End-to-end, unattended:

1. **Monitors** the city's CivicClerk meeting calendar and YouTube playlist.
2. When a new council meeting video appears, **fetches the transcript and RSS context**.
3. **Analyzes** the meeting with an LLM (via OpenRouter — Claude / GPT / Gemini, configurable) to extract decisions, votes, notable quotes, workshop topics with per-member positions, consistency flags, and upcoming items.
4. **Renders** the analysis into an *Eyes on Arvada*–style HTML newsletter (inline-styled, Beehiiv-compatible).
5. **Posts a draft** to Beehiiv via the API.
6. **Emails the editor** with the draft URL via Resend.
7. The editor reviews, edits the "From the Editor" section, and hits send.

A React dashboard reads the same analysis JSON and displays the latest meeting publicly.

## Setup

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

For automation (recommended), add the following secrets to GitHub repo settings → Secrets and variables → Actions:

| Secret | Where to get it |
|---|---|
| `OPENROUTER_API_KEY` | https://openrouter.ai/keys |
| `BEEHIIV_API_KEY` | Beehiiv → Settings → Integrations |
| `BEEHIIV_PUBLICATION_ID` | Beehiiv → Publication settings (UUID) |
| `RESEND_API_KEY` | https://resend.com (free tier: 3,000 emails/mo) |
| `NOTIFY_EMAIL` | Where you want draft-ready emails sent |

For local manual runs, drop the same vars into a `.env` file at the repo root.

## Run

**Automated** (after secrets are configured):

The GitHub Actions workflow at `.github/workflows/monitor.yml` runs every 30 minutes. It picks up new playlist videos, drafts them in Beehiiv, and emails you. You can also trigger it manually from the Actions tab.

**Manual one-off** (legacy CLI, generates Markdown only):

```bash
python run_pipeline.py "https://www.youtube.com/watch?v=XXXXXXXXXXX" --city arvada
```

The Markdown draft saves to `output/arvada_YYYY-MM-DD.md`.

**Local dry-run of the automation** (renders HTML to `/tmp` without publishing):

```bash
python -m automation.monitor --dry-run --video-id XXXXXXXXXXX
```

## Adding a new city

Copy `config/cities/arvada.json`, rename to `<city>.json`, and fill in:

- `name`, `state`, `timezone`
- `youtube_channel_handle`, `youtube_playlist_id`
- `civicclerk.subdomain`, `civicclerk.category_id` (the city council category in their CivicClerk portal)
- `rss_feeds` (URLs from the city's RSS page)
- `newsletter` block (name, tagline, photo_base_url)
- `council_members` (name, title, district, profile_url, phone, photo_filename)

Drop council photos into `docs/design/assets/council/<photo_filename>`.

## Project structure

```
pipeline/
  fetch_transcript.py       # YouTube → timestamped transcript
  fetch_rss.py              # City RSS feeds → context for the LLM
  analyze_meeting.py        # OpenRouter → structured MeetingAnalysis
  render_newsletter.py      # MeetingAnalysis → inline-CSS HTML
  templates/newsletter.html.j2
  generate_draft.py         # Markdown fallback (manual flow)
  save_dashboard_data.py    # MeetingAnalysis → dashboard JSON

automation/
  monitor.py                # scheduled entry point
  civicclerk.py             # CivicClerk OData client
  youtube_monitor.py        # YouTube playlist RSS
  orchestrator.py           # headless pipeline run
  beehiiv.py                # Beehiiv draft post
  notifier.py               # Resend email

dashboard/                  # Vite + React 19 + Tailwind
config/cities/arvada.json   # City-specific configuration
docs/design/                # Pencil design source + assets
state/processed.json        # tracks processed video IDs (CI updates)
.github/workflows/monitor.yml
```

## Editorial workflow

Once a draft lands in Beehiiv, you'll get an email with the link. Open Beehiiv, review the draft, **rewrite the "From the Editor" section** (the auto-stub is just bullet prompts to get you started), and hit Send.

The newsletter template is a faithful port of the *Eyes on Arvada* design in `docs/design/dashboard.pen` (see the "Newsletter — April 28" frame). Iterate on `pipeline/templates/newsletter.html.j2` to evolve it.
