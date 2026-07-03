from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.aiub.edu"
NOTICES_URL = f"{BASE_URL}/category/notices"

# Waits between attempts; total attempts = len(RETRY_DELAYS_S) + 1.
RETRY_DELAYS_S = (5, 15)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Notice:
    title: str
    date: str
    url: str


def _clean(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def parse_notices(html: str) -> list[Notice]:
    soup = BeautifulSoup(html, "html.parser")
    notices: list[Notice] = []
    seen_urls: set[str] = set()

    for node in soup.select("div.notification"):
        title_el = node.select_one("h2.title")
        if not title_el:
            continue
        title = _clean(title_el.get_text())
        if not title:
            continue

        date_el = node.select_one(".date-custom")
        date = _clean(date_el.get_text(" ")) if date_el else ""

        href = _find_href(node)
        if not href:
            continue
        url = urljoin(BASE_URL + "/", href)

        if url in seen_urls:
            continue
        seen_urls.add(url)

        notices.append(Notice(title=title, date=date, url=url))

    return notices


def _find_href(node):
    info = node.select_one("a.info-link[href]")
    if info and info.get("href"):
        return info["href"]
    parent_a = node.find_parent("a", href=True)
    if parent_a and parent_a.get("href"):
        return parent_a["href"]
    any_a = node.select_one("a[href]")
    return any_a["href"] if any_a else None


def _proxies() -> dict | None:
    # AIUB_PROXY routes ONLY the scrape through a proxy (e.g. a Bangladesh
    # exit, since aiub.edu drops most foreign traffic). Telegram and GitHub
    # Models calls stay direct — never send those tokens through a proxy.
    proxy = os.environ.get("AIUB_PROXY", "").strip()
    return {"http": proxy, "https": proxy} if proxy else None


def fetch_notices(timeout: int = 20) -> list[Notice]:
    attempts = len(RETRY_DELAYS_S) + 1
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(
                NOTICES_URL,
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
                proxies=_proxies(),
            )
            resp.raise_for_status()
            return parse_notices(resp.text)
        except requests.RequestException as exc:
            if attempt == attempts:
                raise
            wait = RETRY_DELAYS_S[attempt - 1]
            print(f"  [scraper] attempt {attempt}/{attempts} failed ({exc}); "
                  f"retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
            items = parse_notices(fh.read())
    else:
        items = fetch_notices()

    print(f"Parsed {len(items)} notices:\n")
    for n in items:
        print(f"  [{n.date or '??':>11}]  {n.title}")
        print(f"               {n.url}")
