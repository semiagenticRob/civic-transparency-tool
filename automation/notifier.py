"""
Email notifier — Resend API.

Docs: https://resend.com/docs/api-reference/emails/send-email
Free tier: 3,000 emails/month, plenty for one editor.

Requires RESEND_API_KEY and a verified `from` address. For dev we use the
default `onboarding@resend.dev` sender (no domain setup required); switch to
a verified custom domain when you have one.
"""

from __future__ import annotations

import os
from typing import Optional

import requests


class NotifierError(RuntimeError):
    pass


def notify_draft_ready(
    to_email: str,
    draft_url: str,
    subject_line: str,
    lede_excerpt: str,
    from_email: str = "Eyes on Arvada <onboarding@resend.dev>",
    api_key: Optional[str] = None,
) -> None:
    """Send an email letting the editor know a Beehiiv draft is ready."""
    if api_key is None:
        api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise NotifierError("RESEND_API_KEY not set")

    body_text = (
        f"A new newsletter draft is ready for your review:\n\n"
        f"  {draft_url}\n\n"
        f"Lede:\n  {lede_excerpt}\n\n"
        f"Open Beehiiv to review the draft, edit the 'From the Editor' section, and send when ready."
    )
    body_html = f"""<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 15px; line-height: 1.6; color: #111827;">
<p>A new newsletter draft is ready for your review:</p>
<p><a href="{draft_url}" style="color: #3b5bdb; font-weight: 600;">{draft_url}</a></p>
<p style="font-style: italic; color: #6b7280;">{lede_excerpt}</p>
<p>Open Beehiiv to review the draft, edit the &ldquo;From the Editor&rdquo; section, and send when ready.</p>
</div>"""

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": from_email,
            "to": [to_email],
            "subject": f"New draft — {subject_line}",
            "text": body_text,
            "html": body_html,
        },
        timeout=15,
    )
    if resp.status_code >= 400:
        raise NotifierError(f"Resend API error {resp.status_code}: {resp.text[:500]}")
