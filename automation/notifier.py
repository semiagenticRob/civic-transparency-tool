"""
Email delivery for newsletter drafts (Resend API).

Two modes, both via the same call:
  * `deliver_draft()` — sends the full rendered newsletter HTML inline as
    the email body, with the HTML source attached so the editor can paste
    it directly into Beehiiv's HTML embed block.

When Beehiiv's posts API ever works (currently enterprise-gated), we
include the dashboard link in the header so the editor can edit there
instead of pasting.

Docs: https://resend.com/docs/api-reference/emails/send-email
"""

from __future__ import annotations

import base64
import os
from typing import Optional

import requests


class NotifierError(RuntimeError):
    pass


_PASTE_INSTRUCTIONS = (
    "<p style='margin: 0 0 8px 0; font-family: -apple-system, BlinkMacSystemFont, "
    "Segoe UI, sans-serif; font-size: 14px; color: #111;'><strong>To publish:</strong> "
    "open Beehiiv → New Post → add an <em>HTML embed</em> block → paste the contents "
    "of the attached <code>newsletter.html</code> file → review the rendered preview → send.</p>"
)


def _wrap_with_header(
    body_html: str,
    draft_url: Optional[str],
    publish_error: Optional[str],
) -> str:
    """Wrap the rendered newsletter in a small editor-facing header banner."""
    lines = [
        "<div style='font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; "
        "background: #fef3c7; border-bottom: 1px solid #fde68a; padding: 16px 24px; max-width: 680px; margin: 0 auto;'>",
        "<p style='margin: 0 0 8px 0; font-size: 11px; font-weight: 700; letter-spacing: 2px; color: #92400e;'>"
        "EYES ON ARVADA — DRAFT READY FOR REVIEW</p>",
        _PASTE_INSTRUCTIONS,
    ]
    if draft_url:
        lines.append(
            f"<p style='margin: 8px 0 0 0; font-size: 13px; color: #111;'>"
            f"Beehiiv draft: <a href='{draft_url}' style='color: #3b5bdb;'>{draft_url}</a></p>"
        )
    elif publish_error:
        lines.append(
            f"<p style='margin: 8px 0 0 0; font-size: 12px; color: #92400e;'>"
            f"(Beehiiv API publish skipped — {publish_error[:120]})</p>"
        )
    lines.append("</div>")
    return "\n".join(lines) + body_html


def deliver_draft(
    to_email: str,
    subject_line: str,
    body_html: str,
    draft_url: Optional[str] = None,
    publish_error: Optional[str] = None,
    from_email: str = "Eyes on Arvada <onboarding@resend.dev>",
    api_key: Optional[str] = None,
) -> None:
    """Send the rendered newsletter HTML inline + attached for paste-in."""
    if api_key is None:
        api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise NotifierError("RESEND_API_KEY not set")

    full_html = _wrap_with_header(body_html, draft_url, publish_error)
    plain_text = (
        "Your Eyes on Arvada draft is ready for review.\n\n"
        "To publish: open Beehiiv → New Post → HTML embed block → paste the "
        "attached newsletter.html file → review preview → send.\n\n"
        f"Subject: {subject_line}\n"
    )
    if draft_url:
        plain_text += f"\nBeehiiv draft: {draft_url}\n"

    payload = {
        "from": from_email,
        "to": [to_email],
        "subject": f"DRAFT — {subject_line}",
        "text": plain_text,
        "html": full_html,
        "attachments": [
            {
                "filename": "newsletter.html",
                "content": base64.b64encode(body_html.encode("utf-8")).decode("ascii"),
            }
        ],
    }

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise NotifierError(f"Resend API error {resp.status_code}: {resp.text[:500]}")
