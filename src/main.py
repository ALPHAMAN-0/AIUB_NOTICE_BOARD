from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import classifier
import notifier
from scraper import fetch_notices

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_DIR = REPO_ROOT / "state"
DEFAULT_FLOOD_THRESHOLD = 15

# aiub.edu regularly drops traffic from outside Bangladesh, so a failed
# fetch is expected operation, not a crash: the run skips cleanly, and the
# bot DMs you once the site has been dark this long (then at most daily).
OUTAGE_ALERT_AFTER_HOURS = 24
OUTAGE_REALERT_HOURS = 24


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def load_seen(seen_path: Path):
    if not seen_path.exists():
        return set(), True
    try:
        data = json.loads(seen_path.read_text(encoding="utf-8"))
        urls = set(data.get("seen_urls", []))
        return urls, len(urls) == 0
    except (json.JSONDecodeError, OSError):
        return set(), True


def save_seen(seen_path: Path, urls) -> None:
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"count": len(urls), "seen_urls": sorted(urls)}
    seen_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_heartbeat(heartbeat_path: Path) -> None:
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    heartbeat_path.write_text(today + "\n", encoding="utf-8")


def load_outage(outage_path: Path) -> dict:
    if not outage_path.exists():
        return {}
    try:
        data = json.loads(outage_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _parse_iso(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def handle_outage(exc: Exception, dry_run: bool, state_dir: Path,
                  tg_token, tg_chat) -> int:
    print(f"AIUB site unreachable after retries: {exc}", file=sys.stderr)
    print("This is a site/network problem, not a code bug — www.aiub.edu is "
          "likely down or blocking non-Bangladesh traffic. Skipping this run; "
          "seen-notices state is untouched and the next scheduled run will retry.")
    if dry_run:
        return 1

    outage_path = state_dir / "outage.json"
    now = datetime.now(timezone.utc)
    outage = load_outage(outage_path)
    since = _parse_iso(outage.get("since")) or now
    last_alert = _parse_iso(outage.get("last_alert"))
    # Compare round-tripped values so a corrupt "since" gets repaired on disk
    # instead of silently resetting the outage clock on every run.
    changed = outage.get("since") != since.isoformat()
    outage["since"] = since.isoformat()

    # Touch a day-granular field so the outage produces one state commit per
    # day even if Telegram alerts fail — that commit is what keeps GitHub's
    # 60-day schedule-disable clock at bay during long outages.
    today = now.strftime("%Y-%m-%d")
    if outage.get("last_attempt") != today:
        outage["last_attempt"] = today
        changed = True

    down_hours = (now - since).total_seconds() / 3600
    realert_ok = (last_alert is None or
                  (now - last_alert).total_seconds() / 3600 >= OUTAGE_REALERT_HOURS)
    if down_hours >= OUTAGE_ALERT_AFTER_HOURS and realert_ok:
        since_str = since.strftime("%d %b %Y %H:%M UTC")
        try:
            notifier.send_outage_alert(tg_token, tg_chat, since_str, str(exc))
            outage["last_alert"] = now.isoformat()
            changed = True
            print("Outage alert sent via Telegram.")
        except Exception as alert_exc:
            print(f"Outage alert failed too ({alert_exc}); will retry next run.",
                  file=sys.stderr)

    if changed:
        outage_path.parent.mkdir(parents=True, exist_ok=True)
        outage_path.write_text(json.dumps(outage, indent=2) + "\n",
                               encoding="utf-8")
        print(f"Outage tracked in state/{outage_path.name} "
              f"(down since {outage['since']}).")
    return 0


def handle_recovery(dry_run: bool, state_dir: Path, tg_token, tg_chat) -> None:
    outage_path = state_dir / "outage.json"
    if not outage_path.exists():
        return
    outage = load_outage(outage_path)
    if dry_run:
        print("[dry-run] Site reachable again; would clear outage state.")
        return
    if outage.get("last_alert"):
        try:
            notifier.send_recovery(tg_token, tg_chat)
            print("Recovery message sent via Telegram.")
        except Exception as exc:
            print(f"Recovery message failed ({exc}); clearing outage state anyway.",
                  file=sys.stderr)
    outage_path.unlink(missing_ok=True)
    print("Site reachable again; outage state cleared.")


def run(dry_run: bool, state_dir: Path, threshold: int) -> int:
    seen_path = state_dir / "seen.json"
    heartbeat_path = state_dir / "last_check.txt"

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
    gh_token = os.environ.get("GITHUB_TOKEN")

    if not dry_run and (not tg_token or not tg_chat):
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set "
              "(or use --dry-run).", file=sys.stderr)
        return 2

    try:
        notices = fetch_notices()
    except requests.RequestException as exc:
        return handle_outage(exc, dry_run, state_dir, tg_token, tg_chat)

    print(f"Scraped {len(notices)} notices from the listing.")
    if not notices:
        print("No notices parsed — page layout may have changed. Aborting safely.")
        return 1
    # Only past this point is the run a genuine success (page reachable AND
    # parseable) — declaring recovery any earlier would loop a bogus all-clear
    # if the site comes back as a redesigned/maintenance page.
    handle_recovery(dry_run, state_dir, tg_token, tg_chat)

    seen, first_run = load_seen(seen_path)
    new = [n for n in notices if n.url not in seen]
    print(f"{len(new)} unseen of {len(notices)} "
          f"(state: {'first run' if first_run else f'{len(seen)} known'}).")

    if first_run or len(new) > threshold:
        reason = "first run" if first_run else f"burst > {threshold}"
        all_urls = {n.url for n in notices}
        if dry_run:
            print(f"[dry-run] Would seed silently ({reason}); "
                  f"recording {len(all_urls)} URLs, sending nothing.")
            return 0
        save_seen(seen_path, seen | all_urls)
        write_heartbeat(heartbeat_path)
        print(f"Seeded silently ({reason}); recorded {len(all_urls)} URLs, sent nothing.")
        return 0

    if not new:
        print("Nothing new. Updating heartbeat.")
        if not dry_run:
            write_heartbeat(heartbeat_path)
        return 0

    handled = set()
    for n in new:
        category, summary = classifier.classify(n.title, gh_token)
        emoji = classifier.CATEGORY_EMOJI.get(category, "📢")
        print(f"  {emoji} [{category}] {n.title}")
        print(f"      summary: {summary}")
        if dry_run:
            print(f"      [dry-run] would send -> {n.url}")
            continue
        try:
            notifier.send_notice(tg_token, tg_chat, n, category, summary)
            handled.add(n.url)
            print("      sent ✓")
        except Exception as exc:
            print(f"      send FAILED ({exc}); will retry next run", file=sys.stderr)

    if dry_run:
        print(f"[dry-run] Would have sent {len(new)} message(s); no state written.")
        return 0

    if handled:
        save_seen(seen_path, seen | handled)
    write_heartbeat(heartbeat_path)
    print(f"Done: sent {len(handled)}/{len(new)} new notice(s).")
    return 0


def main(argv=None) -> int:
    load_env_file(REPO_ROOT / ".env")

    parser = argparse.ArgumentParser(description="AIUB notice -> Telegram bot")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--threshold", type=int, default=DEFAULT_FLOOD_THRESHOLD)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    args = parser.parse_args(argv)

    if args.test:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat = os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat:
            print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.",
                  file=sys.stderr)
            return 2
        notifier.send_test(token, chat)
        print("Test message sent ✓")
        return 0

    return run(args.dry_run, args.state_dir, args.threshold)


if __name__ == "__main__":
    raise SystemExit(main())
