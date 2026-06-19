from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import classifier
import notifier
from scraper import fetch_notices

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_DIR = REPO_ROOT / "state"
DEFAULT_FLOOD_THRESHOLD = 15


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

    notices = fetch_notices()
    print(f"Scraped {len(notices)} notices from the listing.")
    if not notices:
        print("No notices parsed — page layout may have changed. Aborting safely.")
        return 1

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
