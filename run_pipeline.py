#!/usr/bin/env python3
"""
Civic Transparency Tool — Newsletter Pipeline

Run after each city council meeting to generate a newsletter draft.

Usage:
    python run_pipeline.py <youtube_url_or_video_id> [--city arvada] [--date 2025-03-25]

Example:
    python run_pipeline.py https://www.youtube.com/watch?v=XXXXXXXXXXX --city arvada
    python run_pipeline.py XXXXXXXXXXX --city arvada --date 2025-03-25
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

load_dotenv()

console = Console()


@click.command()
@click.argument("video")
@click.option("--city", default="arvada", help="City config name (matches config/cities/<name>.json)")
@click.option("--date", default=None, help="Meeting date in YYYY-MM-DD format (defaults to today)")
@click.option("--output-dir", default="output", help="Directory to save the draft")
@click.option("--skip-rss", is_flag=True, help="Skip fetching RSS feeds")
def main(video: str, city: str, date, output_dir: str, skip_rss: bool):
    """Generate a newsletter draft from a city council meeting video."""

    # Load city config
    config_path = Path(f"config/cities/{city}.json")
    if not config_path.exists():
        console.print(f"[red]Error:[/red] City config not found: {config_path}")
        console.print("Available cities:")
        for p in Path("config/cities").glob("*.json"):
            console.print(f"  - {p.stem}")
        sys.exit(1)

    city_config = json.loads(config_path.read_text())
    meeting_date = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()

    console.rule(f"[bold blue]{city_config['name']} Council Watch Pipeline[/bold blue]")
    console.print(f"Video: [cyan]{video}[/cyan]")
    console.print(f"Date:  [cyan]{meeting_date.strftime('%B %d, %Y')}[/cyan]\n")

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:

        # Step 1: Fetch transcript
        task = progress.add_task("Fetching transcript from YouTube...", total=None)
        from pipeline.fetch_transcript import fetch_transcript
        try:
            segments, transcript = fetch_transcript(video)
            progress.update(task, description=f"[green]✓[/green] Transcript fetched ({len(segments)} segments, {len(transcript):,} chars)")
            progress.stop_task(task)
        except Exception as e:
            progress.update(task, description=f"[red]✗[/red] Transcript fetch failed: {e}")
            progress.stop_task(task)
            console.print(f"\n[red]Fatal:[/red] {e}")
            sys.exit(1)

        # Step 2: Fetch RSS feeds
        rss_context = ""
        if not skip_rss:
            task = progress.add_task("Fetching RSS feeds...", total=None)
            from pipeline.fetch_rss import fetch_all_feeds, format_for_prompt
            try:
                feeds = fetch_all_feeds(city_config)
                rss_context = format_for_prompt(feeds)
                total_items = sum(len(v) for v in feeds.values())
                progress.update(task, description=f"[green]✓[/green] RSS feeds fetched ({total_items} items)")
                progress.stop_task(task)
            except Exception as e:
                progress.update(task, description=f"[yellow]⚠[/yellow] RSS fetch failed (continuing): {e}")
                progress.stop_task(task)

        # Step 3: Analyze with Claude
        task = progress.add_task("Analyzing meeting with Claude...", total=None)
        from pipeline.analyze_meeting import analyze_meeting
        try:
            analysis = analyze_meeting(transcript, city_config, rss_context)
            n_decisions = len(analysis.key_decisions)
            n_quotes = len(analysis.notable_quotes)
            progress.update(task, description=f"[green]✓[/green] Analysis complete ({n_decisions} decisions, {n_quotes} quotes)")
            progress.stop_task(task)
        except Exception as e:
            progress.update(task, description=f"[red]✗[/red] Analysis failed: {e}")
            progress.stop_task(task)
            console.print(f"\n[red]Fatal:[/red] {e}")
            sys.exit(1)

        # Step 4: Generate draft
        task = progress.add_task("Generating newsletter draft...", total=None)
        from pipeline.generate_draft import generate_draft
        draft = generate_draft(analysis, city_config, meeting_date, Path(output_dir))
        progress.update(task, description="[green]✓[/green] Draft generated")
        progress.stop_task(task)

    console.print()
    console.rule("[bold green]Done[/bold green]")

    if analysis.editors_note_prompts:
        console.print("\n[bold yellow]Editor prompts to consider:[/bold yellow]")
        for prompt in analysis.editors_note_prompts:
            console.print(f"  • {prompt}")

    if analysis.consistency_flags:
        console.print("\n[bold yellow]Consistency flags:[/bold yellow]")
        for flag in analysis.consistency_flags:
            console.print(f"  • {flag['council_member']}: {flag['observation']}")

    console.print(f"\nDraft saved to: [cyan]{output_dir}/[/cyan]")
    console.print("Review the draft, add your commentary, then publish to Beehiiv. 🗳️")


if __name__ == "__main__":
    main()
