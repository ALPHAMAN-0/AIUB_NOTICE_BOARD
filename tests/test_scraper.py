"""Parsing the notices listing, and what a failed fetch is allowed to reveal."""
from __future__ import annotations

import time
import traceback

import pytest
import requests

import scraper
from scraper import Notice, fetch_notices, parse_notices

LISTING = """
<html><body><section>
  <div class="notification">
    <div class="date-custom">16 <span>Jun</span> <span>2026</span></div>
    <div class="info">
      <h2 class="title">
        Seat Plan   for Final-Term
        Exams of Spring 2025-26
      </h2>
      <a class="info-link" href="/seat-plan-for-final-term-exams">Details</a>
    </div>
  </div>
  <div class="notification">
    <h2 class="title">25th Convocation Notice</h2>
    <a class="info-link" href="25th-convocation">Details</a>
  </div>
</section></body></html>
"""

# A proxy URL in the documented `http://user:pass@host:port` shape. It is
# assembled from parts so the assertions can name each one.
PROXY_USER, PROXY_PASSWORD, PROXY_HOST = "proxyuser", "Pr0xyPassw0rd", "bd-exit.proxy.example"
PROXY = f"http://{PROXY_USER}:{PROXY_PASSWORD}@{PROXY_HOST}:8080"


@pytest.fixture
def sleeps(monkeypatch):
    """Record the retry back-off instead of waiting for it."""
    calls = []
    monkeypatch.setattr(time, "sleep", calls.append)
    return calls


def test_parse_notices_extracts_title_date_and_absolute_url():
    assert parse_notices(LISTING) == [
        Notice(
            title="Seat Plan for Final-Term Exams of Spring 2025-26",
            date="16 Jun 2026",
            url="https://www.aiub.edu/seat-plan-for-final-term-exams",
        ),
        Notice(
            title="25th Convocation Notice",
            date="",
            url="https://www.aiub.edu/25th-convocation",
        ),
    ]


def test_parse_notices_finds_the_link_wherever_the_markup_puts_it():
    title = '<h2 class="title">T</h2>'
    cards = {
        # an explicit "info-link" wins over any other anchor in the card
        f'<div class="notification"><a href="/other">x</a>{title}'
        '<a class="info-link" href="/preferred">x</a></div>': "https://www.aiub.edu/preferred",
        # the whole card wrapped in an anchor
        f'<a href="/wrapped"><div class="notification">{title}</div></a>':
            "https://www.aiub.edu/wrapped",
        # otherwise the first anchor inside the card
        f'<div class="notification">{title}<a href="/first">x</a><a href="/second">y</a></div>':
            "https://www.aiub.edu/first",
        # absolute links are kept as they are
        f'<div class="notification">{title}<a href="https://forms.example/apply">x</a></div>':
            "https://forms.example/apply",
    }
    for card, url in cards.items():
        assert [n.url for n in parse_notices(card)] == [url], card


def test_parse_notices_skips_unusable_cards_and_duplicates():
    cards = (
        '<div class="notification"><a href="/no-title">x</a></div>'
        '<div class="notification"><h2 class="title">  </h2><a href="/blank">x</a></div>'
        '<div class="notification"><h2 class="title">No link</h2></div>'
        '<div class="notification"><h2 class="title">Kept</h2><a href="/kept">x</a></div>'
        '<div class="notification"><h2 class="title">Same link</h2><a href="/kept">x</a></div>'
    )
    assert [n.title for n in parse_notices(cards)] == ["Kept"]
    # main.run() reads an empty result as "the layout changed" and aborts safely
    assert parse_notices("<html><body><h1>Under maintenance</h1></body></html>") == []


def test_fetch_notices_retries_then_succeeds_without_a_proxy(monkeypatch, capsys, sleeps, response):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            raise requests.ConnectionError("connection reset")
        return response(200, text=LISTING)

    monkeypatch.setattr(requests, "get", fake_get)

    notices = fetch_notices()

    assert [n.title for n in notices][-1] == "25th Convocation Notice"
    assert sleeps == [scraper.RETRY_DELAYS_S[0]]
    assert "failed (connection reset); retrying" in capsys.readouterr().err
    url, kwargs = calls[-1]
    assert url == scraper.NOTICES_URL
    assert kwargs["proxies"] is None  # direct unless AIUB_PROXY is set
    assert kwargs["timeout"] == 20


# What requests raises when the proxy refuses the connection; `{host}` is where
# urllib3 names the proxy.
REFUSED = (
    "HTTPSConnectionPool(host='www.aiub.edu', port=443): Max retries exceeded "
    "with url: /category/notices (Caused by ProxyError('Unable to connect to "
    "proxy', NewConnectionError(\"HTTPSConnection(host='{host}', port=8080): "
    "Failed to establish a new connection: [Errno 111] Connection refused\")))"
)

# A proxy setting that urlsplit() rejects (unbalanced IPv6 bracket).
MALFORMED_PROXY = f"http://{PROXY_USER}:{PROXY_PASSWORD}@[{PROXY_HOST}"


@pytest.mark.parametrize(
    ("proxy", "raised", "shown"),
    [
        pytest.param(
            PROXY, REFUSED.format(host=PROXY_HOST), REFUSED.format(host="***"),
            id="connection refused",
        ),
        # an unparseable proxy URL is quoted whole, credentials included
        pytest.param(
            PROXY, f"Failed to parse: {PROXY}", "Failed to parse: ***",
            id="proxy url quoted in the error",
        ),
        pytest.param(
            MALFORMED_PROXY, f"Failed to parse: {MALFORMED_PROXY}", "Failed to parse: ***",
            id="proxy url the scrubber cannot parse either",
        ),
    ],
)
def test_fetch_notices_keeps_the_proxy_out_of_its_errors(
    monkeypatch, capsys, sleeps, proxy, raised, shown
):
    monkeypatch.setenv("AIUB_PROXY", proxy)
    proxies_used = []

    def fake_get(url, **kwargs):
        proxies_used.append(kwargs["proxies"])
        raise requests.exceptions.ProxyError(raised)

    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(requests.RequestException) as excinfo:  # still an "outage" to main.run()
        fetch_notices()

    assert proxies_used[0] == {"http": proxy, "https": proxy}
    assert str(excinfo.value) == shown
    # the retry lines on stderr, and the traceback an uncaught error would print
    printed = capsys.readouterr().err + "".join(traceback.format_exception(excinfo.value))
    assert "retrying" in printed
    for secret in (PROXY_HOST, PROXY_USER, PROXY_PASSWORD):
        assert secret not in printed


def test_fetch_notices_reraises_the_original_error_when_nothing_needs_hiding(monkeypatch, sleeps):
    original = requests.HTTPError(
        "503 Server Error: Service Unavailable for url: https://www.aiub.edu/category/notices"
    )

    def fake_get(url, **kwargs):
        raise original

    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(requests.HTTPError) as excinfo:
        fetch_notices()

    assert excinfo.value is original
    assert sleeps == list(scraper.RETRY_DELAYS_S)
