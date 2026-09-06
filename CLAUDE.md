# CLAUDE.md

## Run
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python src/main.py --test       # send one synthetic Telegram message
python src/main.py --dry-run    # parse + classify + print; sends/writes nothing
python src/main.py              # real run (sends + writes state)
```
(README.md "Run locally" — no build/test/lint scripts found; no package.json/pyproject.toml present.)

## Rules observed
- `state/seen.json` is dedup source of truth (by URL) — don't hand-edit without understanding `load_seen`/`save_seen` in `src/main.py`.
- If scraping returns 0 notices, `main.py` exits non-zero on purpose so the workflow skips committing state (README, `src/main.py` `run()`).
- Sibling `src/` modules are imported by bare name (`import classifier`, `import notifier`, `from scraper import fetch_notices`) — keep that pattern (`src/main.py`).

## Read first
1. `README.md`
2. `src/main.py`
3. `ARCHITECTURE.md`

Architecture: see ARCHITECTURE.md — read before structural changes
