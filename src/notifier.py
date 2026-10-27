from __future__ import annotations

import html
import re

import requests

from classifier import CATEGORY_EMOJI
from scraper import Notice

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# The API URL embeds the bot token, and `requests` quotes that URL in its
# error text. Callers print these errors to the (public) Actions log, so the
# token is scrubbed from everything send_message() raises.
_BOT_PATH = re.compile(r"/bot[^/\s]+")


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def _scrub(text: str, token: str) -> str:
    if token:
        text = text.replace(token, "***")
    return _BOT_PATH.sub("/bot***", text)


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
    try:
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
    except requests.RequestException as exc:
        # "from None": the original error (token in its URL) must not be
        # chained into a traceback either, e.g. when --test fails uncaught.
        raise RuntimeError(
            f"Telegram request failed: {_scrub(str(exc), token)}"
        ) from None
    data = resp.json() if resp.content else {}
    if not resp.ok or not data.get("ok", False):
        detail = str(data.get("description") or resp.text[:300])
        raise RuntimeError(
            f"Telegram sendMessage failed (HTTP {resp.status_code}): "
            f"{_scrub(detail, token)}"
        )
    return data


def send_notice(token: str, chat_id: str, notice: Notice,
                category: str, summary: str) -> None:
    send_message(token, chat_id, format_message(notice, category, summary))


def send_outage_alert(token: str, chat_id: str,
                      since_str: str, error: str) -> None:
    text = "\n".join([
        "⚠️ <b>AIUB Notice Bot — site unreachable</b>",
        f"🌐 www.aiub.edu has been unreachable since {_esc(since_str)}.",
        f"🧰 Last error: {_esc(error[:200])}",
        "ℹ️ The site is likely down or blocking traffic from outside "
        "Bangladesh. The bot keeps checking 4×/day and will message you "
        "when it recovers.",
    ])
    send_message(token, chat_id, text)


def send_recovery(token: str, chat_id: str) -> None:
    text = "\n".join([
        "✅ <b>AIUB Notice Bot — site reachable again</b>",
        "🌐 www.aiub.edu is back. Normal notice checks have resumed. "
        "New notices will follow in separate messages (a very large "
        "backlog is re-seeded silently instead, to avoid flooding you).",
    ])
    send_message(token, chat_id, text)


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
