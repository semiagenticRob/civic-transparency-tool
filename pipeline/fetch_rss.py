"""
Fetches upcoming agenda items and recent news from a city's RSS feeds.

Usage:
    python -m pipeline.fetch_rss <city_config_path>
"""

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import feedparser


@dataclass
class FeedItem:
    title: str
    summary: str
    link: str
    published: str


def fetch_feed(url: str, limit: int = 10) -> list[FeedItem]:
    """Fetch and parse a single RSS feed, returning the most recent items."""
    feed = feedparser.parse(url)
    items = []
    for entry in feed.entries[:limit]:
        items.append(FeedItem(
            title=entry.get("title", "").strip(),
            summary=entry.get("summary", entry.get("description", "")).strip(),
            link=entry.get("link", ""),
            published=entry.get("published", entry.get("updated", "")),
        ))
    return items


def fetch_all_feeds(city_config: dict) -> dict[str, list[FeedItem]]:
    """Fetch all RSS feeds defined in a city config."""
    results = {}
    for feed_name, url in city_config.get("rss_feeds", {}).items():
        try:
            results[feed_name] = fetch_feed(url)
        except Exception as e:
            print(f"Warning: could not fetch {feed_name} feed ({url}): {e}")
            results[feed_name] = []
    return results


def format_for_prompt(feeds: dict[str, list[FeedItem]]) -> str:
    """Format feed items as a concise text block suitable for inclusion in a Claude prompt."""
    lines = []
    for feed_name, items in feeds.items():
        if not items:
            continue
        lines.append(f"\n## {feed_name.upper()} FEED")
        for item in items:
            lines.append(f"- {item.title}")
            if item.summary:
                # Truncate long summaries
                summary = item.summary[:200] + "..." if len(item.summary) > 200 else item.summary
                lines.append(f"  {summary}")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m pipeline.fetch_rss <city_config_path>")
        sys.exit(1)

    config_path = Path(sys.argv[1])
    config = json.loads(config_path.read_text())
    feeds = fetch_all_feeds(config)
    print(format_for_prompt(feeds))
