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
@click.option("--meeting-type", default=None, type=click.Choice(["business", "workshop", "study_session"]),
              help="Override meeting type (default: detect from --title; falls back to 'business')")
@click.option("--title", default="", help="Meeting title used for type detection when --meeting-type is omitted")
def main(video: str, city: str, date, output_dir: str, skip_rss: bool, meeting_type, title: str):
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

        # Step 1: Fetch transcript (with timestamps for Claude)
        task = progress.add_task("Fetching transcript from YouTube...", total=None)
        from pipeline.fetch_transcript import fetch_transcript, extract_video_id, format_with_timestamps
        try:
            video_id = extract_video_id(video)
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            segments, transcript = fetch_transcript(video)
            timestamped_transcript = format_with_timestamps(segments)
            progress.update(task, description=f"[green]✓[/green] Transcript fetched ({len(segments)} segments, {len(transcript):,} chars)")
            progress.stop_task(task)
        except Exception as e:
            progress.update(task, description=f"[red]✗[/red] Transcript fetch failed: {e}")
            progress.stop_task(task)
            console.print(f"\n[red]Fatal:[/red] {e}")
            sys.exit(1)

        # Step 2: Fetch RSS feeds
        rss_context = ""
        feeds = {}
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

        # Step 3: Detect meeting type
        from pipeline.meeting_type import detect_meeting_type
        resolved_type = meeting_type or detect_meeting_type(title, city_config)
        console.print(f"  meeting type: [bold cyan]{resolved_type}[/bold cyan]")

        # Step 4: Analyze with the type-specific prompt
        task = progress.add_task(f"Analyzing meeting ({resolved_type})...", total=None)
        from pipeline.analyze_meeting import analyze_meeting
        try:
            analysis = analyze_meeting(
                transcript=timestamped_transcript,
                city_config=city_config,
                meeting_type=resolved_type,
                rss_context=rss_context,
                video_id=video_id,
            )
            progress.update(task, description=f"[green]✓[/green] Analysis complete")
            progress.stop_task(task)
        except Exception as e:
            progress.update(task, description=f"[red]✗[/red] Analysis failed: {e}")
            progress.stop_task(task)
            console.print(f"\n[red]Fatal:[/red] {e}")
            sys.exit(1)

        # Step 5: Validate quotes against the transcript
        task = progress.add_task("Validating quotes against transcript...", total=None)
        from pipeline.validate_quotes import validate_quotes
        report = validate_quotes(analysis, timestamped_transcript)
        progress.update(task, description=f"[green]✓[/green] Quote validation: {report.kept} kept, {report.dropped} dropped")
        progress.stop_task(task)

        # Step 6: Generate Markdown summary draft
        task = progress.add_task("Generating Markdown draft...", total=None)
        from pipeline.generate_draft import generate_draft
        draft = generate_draft(analysis, city_config, meeting_date, Path(output_dir))
        progress.update(task, description="[green]✓[/green] Markdown draft generated")
        progress.stop_task(task)

        # Step 7: Render the HTML newsletter alongside the Markdown
        task = progress.add_task("Rendering HTML newsletter...", total=None)
        from pipeline.render_newsletter import render_newsletter
        rendered = render_newsletter(analysis, city_config, meeting_date)
        html_filename = f"{city_config['name'].lower().replace(' ', '-')}_{meeting_date.strftime('%Y-%m-%d')}.html"
        html_path = Path(output_dir) / html_filename
        html_path.write_text(rendered.body_html)
        progress.update(task, description=f"[green]✓[/green] HTML newsletter → {html_path}")
        progress.stop_task(task)

        # Step 8: Save dashboard data
        task = progress.add_task("Updating dashboard data...", total=None)
        from pipeline.save_dashboard_data import save_dashboard_data, enrich_with_rss
        latest_path = save_dashboard_data(analysis, city_config, meeting_date, video_url=video_url)
        if feeds:
            payload = json.loads(latest_path.read_text())
            payload = enrich_with_rss(payload, feeds)
            latest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        progress.update(task, description=f"[green]✓[/green] Dashboard data saved → {latest_path}")
        progress.stop_task(task)

    console.print()
    console.rule("[bold green]Done[/bold green]")

    if report.dropped:
        console.print(f"\n[bold yellow]⚠ Quote validation dropped {report.dropped} of {report.total} quotes[/bold yellow] — see logs for details.")

    console.print(f"\nDraft saved to: [cyan]{output_dir}/[/cyan]")
    console.print("Review the draft, add your commentary, then publish to Beehiiv. 🗳️")


if __name__ == "__main__":
    main()
