from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

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


def _scrub_proxy(text: str) -> str:
    # Connection errors name the proxy's host, and an unparseable proxy URL
    # is quoted whole (credentials included). These errors go to the (public)
    # Actions log and into the Telegram outage alert, and Actions only masks
    # the secret where it appears verbatim — so strip every part of it here.
    proxy = os.environ.get("AIUB_PROXY", "").strip()
    if not proxy:
        return text
    parts = {proxy}
    try:
        url = urlsplit(proxy if "://" in proxy else f"//{proxy}")
        parts.update(p for p in (url.netloc, url.username, url.password,
                                 url.hostname) if p)
    except ValueError:
        pass
    for part in sorted(parts, key=len, reverse=True):
        text = re.sub(re.escape(part), "***", text, flags=re.IGNORECASE)
    return text


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
            reason = _scrub_proxy(str(exc))
            if attempt == attempts:
                if reason == str(exc):
                    raise
                # Raise a clean copy instead: the original would carry the
                # proxy details into the caller's log line and alert.
                raise requests.RequestException(reason) from None
            wait = RETRY_DELAYS_S[attempt - 1]
            print(f"  [scraper] attempt {attempt}/{attempts} failed ({reason}); "
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
