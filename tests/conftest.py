"""Shared test setup: every test runs offline and without real credentials."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import requests

# The bot's modules import each other by bare name, exactly as they do when
# the workflow runs `python src/main.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

SECRET_ENV = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GITHUB_TOKEN", "AIUB_PROXY")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Fail loudly if a test would use a real secret or open a connection."""
    for name in SECRET_ENV:
        monkeypatch.delenv(name, raising=False)

    def blocked(*args, **kwargs):
        # pytest.fail() is not an Exception subclass, so the bot's own
        # "except Exception" fallbacks cannot swallow it.
        pytest.fail("tests must not open network connections")

    monkeypatch.setattr(requests.Session, "request", blocked)


class FakeResponse:
    """The few `requests.Response` members the bot reads."""

    def __init__(self, status_code: int = 200, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text if payload is None else json.dumps(payload)
        self.content = self.text.encode()

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self):
        if self._payload is None:
            raise requests.exceptions.JSONDecodeError("Expecting value", self.text, 0)
        return self._payload

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Error for url: (mocked)")


@pytest.fixture
def response():
    return FakeResponse
