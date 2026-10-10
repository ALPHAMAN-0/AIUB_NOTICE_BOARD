"""Telegram message formatting and delivery (HTTP mocked)."""
from __future__ import annotations

import traceback

import pytest
import requests

import notifier
from scraper import Notice

TOKEN = "1111:not-a-real-token"
CHAT = "424242"


def test_format_message_escapes_everything_scraped_or_generated():
    notice = Notice(
        title='<b>Free laptops</b> & "more"',
        date="<i>today</i>",
        url='https://www.aiub.edu/n?a=1&b="x"><script>',
    )

    text = notifier.format_message(
        notice, "Exam", "see <a href='https://evil.example'>here</a>"
    )

    assert "&lt;b&gt;Free laptops&lt;/b&gt; &amp;" in text
    assert "&lt;i&gt;today&lt;/i&gt;" in text
    assert "&lt;a href='https://evil.example'&gt;here&lt;/a&gt;" in text
    assert 'href="https://www.aiub.edu/n?a=1&amp;b=&quot;x&quot;&gt;&lt;script&gt;"' in text
    # the only markup left is the template's own
    assert text.count("<a ") == 1
    assert "<script" not in text
    assert "<i>" not in text


def test_send_message_posts_an_html_message(monkeypatch, response):
    sent = {}

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return response(200, {"ok": True, "result": {"message_id": 7}})

    monkeypatch.setattr(requests, "post", fake_post)

    data = notifier.send_message(TOKEN, CHAT, "<b>hi</b>")

    assert data["result"]["message_id"] == 7
    assert sent["url"] == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert sent["json"] == {
        "chat_id": CHAT,
        "text": "<b>hi</b>",
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    assert sent["timeout"] == 20


def test_send_message_raises_when_telegram_rejects_the_message(monkeypatch, response):
    rejection = response(400, {"ok": False, "description": "Bad Request: chat not found"})
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: rejection)

    # raising is what makes main.run() retry the notice on the next run
    with pytest.raises(RuntimeError, match=r"HTTP 400.*chat not found"):
        notifier.send_message(TOKEN, CHAT, "hi")


LEAKY_ERRORS = {
    # requests quotes the request path — which embeds the token — in its errors
    "url quoted by requests": (
        "HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries "
        f"exceeded with url: /bot{TOKEN}/sendMessage (Caused by "
        "ConnectTimeoutError('Connection to api.telegram.org timed out'))"
    ),
    "percent-encoded url": (
        f"Invalid URL 'https://api.telegram.org/bot{TOKEN.replace(':', '%3A')}/sendMessage'"
    ),
}


@pytest.mark.parametrize("message", LEAKY_ERRORS.values(), ids=LEAKY_ERRORS.keys())
def test_send_message_never_reveals_the_bot_token(monkeypatch, message):
    def fake_post(url, **kwargs):
        raise requests.ConnectionError(message)

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(RuntimeError) as excinfo:
        notifier.send_message(TOKEN, CHAT, "hi")

    # what main.py logs, and what an uncaught error (`--test` mode) prints
    shown = str(excinfo.value) + "".join(traceback.format_exception(excinfo.value))
    assert TOKEN not in shown
    assert TOKEN.split(":")[1] not in shown
    assert "api.telegram.org" in shown  # still says what failed


def test_send_message_scrubs_a_token_echoed_back_in_an_api_error(monkeypatch, response):
    echo = response(404, {"ok": False, "description": f"Not Found: /bot{TOKEN}/sendMessage"})
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: echo)

    with pytest.raises(RuntimeError, match="HTTP 404") as excinfo:
        notifier.send_message(TOKEN, CHAT, "hi")

    assert TOKEN not in str(excinfo.value)
