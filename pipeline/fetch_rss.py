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
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class _TransientFeedError(RuntimeError):
    """Raised for feed fetches that look transient (network failure, bozo URLError).

    A retry-eligible failure class so tenacity only burns wait time on errors
    that have a reasonable chance of succeeding on retry — not on permanent
    parse errors or 404s.
    """


@dataclass
class FeedItem:
    title: str
    summary: str
    link: str
    published: str


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=2, max=30),
    retry=retry_if_exception_type(_TransientFeedError),
    reraise=True,
)
def fetch_feed(url: str, limit: int = 10) -> list[FeedItem]:
    """Fetch and parse a single RSS feed, returning the most recent items.

    Retries up to 3× with exponential backoff on transient failures only
    (network errors). Permanent parse failures fail fast — `fetch_all_feeds`
    catches the underlying exception per feed and substitutes an empty list.
    """
    feed = feedparser.parse(url)
    if feed.bozo and not feed.entries:
        exc = feed.bozo_exception
        # feedparser uses urllib under the hood; URLError/socket errors indicate
        # transient network issues. Everything else (SAXParseException,
        # CharacterEncodingOverride, etc.) is a permanent parse problem.
        import urllib.error
        if isinstance(exc, (urllib.error.URLError, OSError)):
            raise _TransientFeedError(f"RSS fetch failed for {url}: {exc!r}")
        raise RuntimeError(f"RSS parse failed for {url}: {exc!r}")
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
