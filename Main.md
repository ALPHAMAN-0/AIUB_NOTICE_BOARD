---
tags: [component, AIUB_NOTICE_BOARD]
---
- Path: `src/main.py`
- Role: orchestrator — env loading, dedup against state, outage handling, CLI (`--dry-run`/`--test`/`--threshold`/`--state-dir`), run flow.
- Talks to: [[Scraper]], [[Classifier]], [[Notifier]], [[State]]
- Back: [[ARCHITECTURE]]
