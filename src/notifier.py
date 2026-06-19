from __future__ import annotations

import html

import requests

from classifier import CATEGORY_EMOJI
from scraper import Notice

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def format_message(notice: Notice, category: str, summary: str) -> str:
    emoji = CATEGORY_EMOJI.get(category, "📢")
    date = notice.date or "—"
    lines = [
        "🔔 <b>New AIUB Notice</b>",
        f"{emoji} {_esc(category)}",
        f"📌 <b>{_esc(notice.title)}</b>",
        f"📅 {_esc(date)}",
        f"📝 {_esc(summary)}",
        f'🔗 <a href="{html.escape(notice.url, quote=True)}">Open notice</a>',
    ]
    return "\n".join(lines)


def send_message(token: str, chat_id: str, text: str, timeout: int = 20) -> dict:
    resp = requests.post(
        TELEGRAM_API.format(token=token),
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        },
        timeout=timeout,
    )
    data = resp.json() if resp.content else {}
    if not resp.ok or not data.get("ok", False):
        raise RuntimeError(
            f"Telegram sendMessage failed (HTTP {resp.status_code}): "
            f"{data.get('description') or resp.text[:300]}"
        )
    return data


def send_notice(token: str, chat_id: str, notice: Notice,
                category: str, summary: str) -> None:
    send_message(token, chat_id, format_message(notice, category, summary))


def send_test(token: str, chat_id: str) -> None:
    sample = Notice(
        title="Test notice — pipeline check",
        date="19 Jun 2026",
        url="https://www.aiub.edu/category/notices",
    )
    text = format_message(
        sample, "General",
        "This is a test message from your AIUB notice bot. "
        "If you can read this, Telegram delivery works.",
    )
    send_message(token, chat_id, text)
