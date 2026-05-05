"""
Beehiiv API client — create draft posts.

Docs: https://developers.beehiiv.com
Endpoint: POST https://api.beehiiv.com/v2/publications/{publication_id}/posts
Auth: Authorization: Bearer {api_key}

Beehiiv strips <style> and <link> tags from body_content; render with inline
styles only. Images can be passed via <img src="..."> with external URLs;
Beehiiv caches them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass
class DraftResponse:
    draft_id: str
    draft_url: str  # Beehiiv dashboard URL the editor should open


class BeehiivError(RuntimeError):
    pass


def create_draft(
    publication_id: str,
    subject: str,
    subtitle: str,
    body_html: str,
    api_key: Optional[str] = None,
) -> DraftResponse:
    """Create a draft post in Beehiiv. Returns draft id + dashboard URL."""
    if api_key is None:
        api_key = os.environ.get("BEEHIIV_API_KEY")
    if not api_key:
        raise BeehiivError("BEEHIIV_API_KEY not set")

    # Beehiiv expects publication IDs in the form `pub_<uuid>`. Accept either
    # form so the caller can paste the raw UUID from their dashboard URL.
    if not publication_id.startswith("pub_"):
        publication_id = f"pub_{publication_id}"

    url = f"https://api.beehiiv.com/v2/publications/{publication_id}/posts"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "title": subject,
        "subtitle": subtitle,
        "status": "draft",
        "body_content": body_html,
    }

    resp = requests.post(url, json=body, headers=headers, timeout=30)
    if resp.status_code >= 400:
        raise BeehiivError(f"Beehiiv API error {resp.status_code}: {resp.text[:500]}")

    data = resp.json().get("data", {})
    draft_id = data.get("id", "")
    if not draft_id:
        raise BeehiivError(f"Beehiiv response missing draft id: {resp.text[:500]}")

    return DraftResponse(
        draft_id=draft_id,
        draft_url=f"https://app.beehiiv.com/posts/{draft_id}",
    )
