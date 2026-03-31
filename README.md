# Civic Transparency Tool

AI-powered local government accountability. Watches city council meetings so your community doesn't have to.

## What it does

1. Pulls the transcript from a city council meeting YouTube video
2. Fetches upcoming agenda items from the city's RSS feeds
3. Sends everything to Claude for analysis — key decisions, votes, notable quotes, speaker attribution, consistency flags
4. Generates a newsletter draft ready for your review and publication to Beehiiv

## Setup

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Add your Anthropic API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

## Run

After each city council meeting:

```bash
python run_pipeline.py <youtube_url_or_video_id> --city arvada
```

Example:
```bash
python run_pipeline.py "https://www.youtube.com/watch?v=XXXXXXXXXXX" --city arvada --date 2025-03-25
```

The draft will be saved to `output/arvada_YYYY-MM-DD.md`. Review it, add your commentary, delete the editor prompts, and paste into Beehiiv.

## Adding a new city

Copy `config/cities/arvada.json`, rename it to `<city>.json`, and fill in:
- `youtube_channel_handle` — the city's YouTube @handle
- `rss_feeds` — URLs from the city's RSS page
- `council_members` — names and titles

Then run with `--city <city>`.

## Project structure

```
pipeline/
  fetch_transcript.py   # YouTube → transcript text
  fetch_rss.py          # City RSS feeds → upcoming agenda items
  analyze_meeting.py    # Claude API → structured analysis
  generate_draft.py     # Analysis → newsletter draft Markdown

config/cities/
  arvada.json           # City-specific configuration

output/                 # Generated drafts (gitignored)
run_pipeline.py         # Main entry point
```
