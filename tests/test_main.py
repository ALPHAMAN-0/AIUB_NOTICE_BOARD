"""The run loop: dedup state, silent seeding, flood guard and outage tracking."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

import main
import notifier
from scraper import Notice

TOKEN = "1111:not-a-real-token"
CHAT = "424242"

OLD = Notice("Old notice", "1 Jan 2026", "https://www.aiub.edu/old")
EXAM = Notice("Midterm exam schedule", "2 Jan 2026", "https://www.aiub.edu/midterm")
EVENT = Notice("Robotics workshop", "3 Jan 2026", "https://www.aiub.edu/workshop")

PROXY_USER, PROXY_PASSWORD, PROXY_HOST = "proxyuser", "Pr0xyPassw0rd", "bd-exit.proxy.example"
PROXY = f"http://{PROXY_USER}:{PROXY_PASSWORD}@{PROXY_HOST}:8080"


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)


@pytest.fixture
def telegram(monkeypatch, credentials):
    """Credentials are set; messages are recorded instead of delivered."""
    sent = []
    monkeypatch.setattr(
        notifier, "send_message", lambda token, chat_id, text, **kwargs: sent.append(text)
    )
    return sent


def listing(monkeypatch, *notices):
    """Make the scrape return exactly these notices."""
    monkeypatch.setattr(main, "fetch_notices", lambda: list(notices))


def unreachable(monkeypatch, message="connection timed out"):
    """Make the scrape fail the way a blocked or down site does."""

    def fail():
        raise requests.ConnectionError(message)

    monkeypatch.setattr(main, "fetch_notices", fail)


def seen_urls(state_dir):
    return json.loads((state_dir / "seen.json").read_text(encoding="utf-8"))["seen_urls"]


def outage_since(state_dir, hours_ago, **extra):
    since = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    (state_dir / "outage.json").write_text(json.dumps({"since": since.isoformat(), **extra}))


def test_env_file_fills_gaps_but_never_overrides_the_real_environment(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# a comment, then a blank line\n"
        "\n"
        "TELEGRAM_CHAT_ID = '111'\n"
        'TELEGRAM_BOT_TOKEN="from-file"\n'
        "not an assignment\n"
    )
    environ = {"TELEGRAM_BOT_TOKEN": "from-environment"}
    monkeypatch.setattr(os, "environ", environ)

    main.load_env_file(env_file)
    main.load_env_file(tmp_path / "missing.env")  # an absent file is fine

    assert environ == {"TELEGRAM_BOT_TOKEN": "from-environment", "TELEGRAM_CHAT_ID": "111"}


@pytest.mark.parametrize("existing", [None, "{not json"], ids=["no state yet", "corrupt state"])
def test_first_run_records_everything_and_sends_nothing(monkeypatch, tmp_path, telegram, existing):
    if existing is not None:
        (tmp_path / "seen.json").write_text(existing)
    listing(monkeypatch, OLD, EXAM)

    assert main.run(False, tmp_path, threshold=15) == 0

    assert telegram == []
    assert seen_urls(tmp_path) == sorted([OLD.url, EXAM.url])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}\n", (tmp_path / "last_check.txt").read_text())


def test_only_unseen_notices_are_sent_and_then_remembered(monkeypatch, tmp_path, telegram):
    main.save_seen(tmp_path / "seen.json", {OLD.url})
    listing(monkeypatch, OLD, EXAM)

    assert main.run(False, tmp_path, threshold=15) == 0
    assert main.run(False, tmp_path, threshold=15) == 0  # second run: nothing new

    assert len(telegram) == 1
    assert "Midterm exam schedule" in telegram[0]
    assert EXAM.url in telegram[0]
    assert "Exam" in telegram[0]  # keyword category: no GITHUB_TOKEN in tests
    assert seen_urls(tmp_path) == sorted([OLD.url, EXAM.url])
    assert (tmp_path / "last_check.txt").exists()


def test_a_failed_send_is_retried_next_run_and_its_log_hides_the_token(
    monkeypatch, tmp_path, capsys, credentials, response
):
    main.save_seen(tmp_path / "seen.json", {OLD.url})
    listing(monkeypatch, OLD, EXAM, EVENT)
    delivered = []

    def fake_post(url, **kwargs):
        text = kwargs["json"]["text"]
        if "Midterm" in text:
            raise requests.ConnectionError(
                "HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries "
                f"exceeded with url: {url.removeprefix('https://api.telegram.org')}"
            )
        delivered.append(text)
        return response(200, {"ok": True})

    monkeypatch.setattr(requests, "post", fake_post)

    assert main.run(False, tmp_path, threshold=15) == 0

    assert len(delivered) == 1
    assert "Robotics workshop" in delivered[0]
    assert seen_urls(tmp_path) == sorted([OLD.url, EVENT.url])  # EXAM stays unseen => retried
    logged = capsys.readouterr().err
    assert "send FAILED" in logged
    assert TOKEN not in logged
    assert TOKEN.split(":")[1] not in logged


def test_a_burst_above_the_threshold_is_recorded_silently(monkeypatch, tmp_path, telegram):
    main.save_seen(tmp_path / "seen.json", {OLD.url})
    listing(monkeypatch, OLD, EXAM, EVENT)

    assert main.run(False, tmp_path, threshold=1) == 0

    assert telegram == []
    assert seen_urls(tmp_path) == sorted([OLD.url, EXAM.url, EVENT.url])


def test_an_empty_listing_aborts_without_touching_state(monkeypatch, tmp_path, telegram):
    main.save_seen(tmp_path / "seen.json", {OLD.url})
    before = (tmp_path / "seen.json").read_text()
    listing(monkeypatch)

    # non-zero exit => the workflow skips its "commit state" step
    assert main.run(False, tmp_path, threshold=15) == 1

    assert telegram == []
    assert (tmp_path / "seen.json").read_text() == before
    assert not (tmp_path / "last_check.txt").exists()


def test_credentials_are_required_for_real_runs_but_not_for_a_dry_run(
    monkeypatch, tmp_path, capsys
):
    main.save_seen(tmp_path / "seen.json", {OLD.url})
    before = (tmp_path / "seen.json").read_text()
    listing(monkeypatch, OLD, EXAM)

    assert main.run(False, tmp_path, threshold=15) == 2
    assert "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set" in capsys.readouterr().err

    # a dry run sends nothing (`offline` would fail the test) and writes nothing...
    assert main.run(True, tmp_path, threshold=15) == 0
    assert [path.name for path in tmp_path.iterdir()] == ["seen.json"]
    assert (tmp_path / "seen.json").read_text() == before
    # ...not even on a first run, which would otherwise seed the state
    fresh = tmp_path / "fresh"
    assert main.run(True, fresh, threshold=15) == 0
    assert not fresh.exists()


def test_an_unreachable_site_is_tracked_without_failing_the_run(monkeypatch, tmp_path, telegram):
    main.save_seen(tmp_path / "seen.json", {OLD.url})
    unreachable(monkeypatch)

    assert main.run(False, tmp_path, threshold=15) == 0  # the workflow stays green

    outage = json.loads((tmp_path / "outage.json").read_text())
    assert set(outage) == {"since", "last_attempt"}
    assert telegram == []  # no alert during the first 24 h
    assert seen_urls(tmp_path) == [OLD.url]
    assert not (tmp_path / "last_check.txt").exists()


def test_a_long_outage_alerts_at_most_once_a_day(monkeypatch, tmp_path, telegram):
    outage_since(tmp_path, hours_ago=25)
    unreachable(monkeypatch, "503 Server Error <b>")

    assert main.run(False, tmp_path, threshold=15) == 0
    assert main.run(False, tmp_path, threshold=15) == 0

    assert len(telegram) == 1
    assert "site unreachable" in telegram[0]
    assert "503 Server Error &lt;b&gt;" in telegram[0]  # error text is escaped
    assert "last_alert" in json.loads((tmp_path / "outage.json").read_text())


def test_recovery_is_announced_once_and_clears_the_outage(monkeypatch, tmp_path, telegram):
    main.save_seen(tmp_path / "seen.json", {OLD.url})
    outage_since(tmp_path, hours_ago=30, last_alert=datetime.now(timezone.utc).isoformat())
    listing(monkeypatch, OLD)

    assert main.run(False, tmp_path, threshold=15) == 0
    assert main.run(False, tmp_path, threshold=15) == 0

    assert len(telegram) == 1
    assert "reachable again" in telegram[0]
    assert not (tmp_path / "outage.json").exists()


def test_outage_log_and_alert_do_not_reveal_the_proxy(monkeypatch, tmp_path, capsys, telegram):
    monkeypatch.setenv("AIUB_PROXY", PROXY)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    outage_since(tmp_path, hours_ago=25)

    def fake_get(url, **kwargs):
        raise requests.exceptions.ProxyError(
            "ProxyError('Unable to connect to proxy', NewConnectionError("
            f"\"HTTPSConnection(host='{PROXY_HOST}', port=8080): Connection refused\"))"
        )

    monkeypatch.setattr(requests, "get", fake_get)  # the real fetch_notices() runs

    assert main.run(False, tmp_path, threshold=15) == 0

    logged = capsys.readouterr().err
    assert "unreachable after retries" in logged
    assert len(telegram) == 1
    assert "Unable to connect to proxy" in telegram[0]  # still says what failed
    for secret in (PROXY_HOST, PROXY_USER, PROXY_PASSWORD):
        assert secret not in logged
        assert secret not in telegram[0]
