# AIUB Notice → Telegram Bot

Watches the [AIUB notices page](https://www.aiub.edu/category/notices) and sends
you a **Telegram message for every new notice** — classified by type and
summarized in one line by AI. Runs **4× a day** on **GitHub Actions** for free.
No server, no paid API keys.

> 📦 **Repo:** https://github.com/ALPHAMAN-0/AIUB_NOTICE_BOARD
> **Want your own?** Fork it and deploy in ~5 minutes — see [Setup](#setup-5-minutes) below.

> 9am · 1pm · 5pm · 9pm (Asia/Dhaka). Each new notice arrives as its own message:
>
> ```
> 🔔 New AIUB Notice
> 📝 Exam
> 📌 Seat Plan for Final-Term Exams of Spring 2025-26
> 📅 16 Jun 2026
> 📝 This notice provides the seat plan for final-term exams for LLB and BPharm students.
> 🔗 Open notice
> ```

## The simple version 🤖

Think of your university's notice board by the front gate, where teachers pin up exam dates, holidays, and results. Checking it yourself every few hours is a chore — so this project is a **tiny robot that does it for you**:

1. **It wakes up by itself, 4 times a day** (morning, noon, afternoon, night). You never press anything.
2. **It looks at the AIUB notices page** and reads everything posted.
3. **It keeps a notebook** (`state/seen.json`) of every notice it has already seen, and asks: *is there anything here I haven't seen before?*
4. **If nothing is new → it stays quiet** and goes back to sleep. (No spam — silence just means "nothing new".)
5. **If something is new → it reads the notice, an AI picks the category and writes a one-line summary, and it sends a Telegram message to your phone.** Then it notes the notice in its notebook so you're never told twice.
6. **It goes back to sleep and repeats** — forever.

Two things make it handy: it runs on **GitHub's computers (the cloud)**, so it keeps watching even while your laptop is off and you're asleep — and it **only messages you when there's genuinely something new**.

```mermaid
flowchart TD
    A([Wakes up<br/>4 times a day]) --> B[Checks the board<br/>the AIUB website]
    B --> C{Anything new?<br/>compares to its notebook}
    C -->|no| D[Nothing new<br/>stays quiet]
    C -->|yes| E[Found something new<br/>sorts and summarizes it]
    E --> F[Messages your phone<br/>on Telegram]
    D -.->|then again, next time| A
    F -.->|then again, next time| A
```

## How it works

1. **Scrape** — `src/scraper.py` reads the notices listing (static HTML: title, date, detail-page URL).
2. **Dedup** — compares against `state/seen.json`; alerts on **any notice it hasn't seen before** (so nothing is missed even if a run is skipped).
3. **Classify + summarize** — `src/classifier.py` asks **GitHub Models** (free, via the workflow's `GITHUB_TOKEN`) for a category + one-line summary, working from the title. If the model is unavailable, a keyword fallback still picks a sensible category.
4. **Notify** — `src/notifier.py` sends one Telegram message per new notice.
5. **Persist** — updates `state/seen.json` (committed back to the repo) and a daily heartbeat (`state/last_check.txt`) that keeps the public-repo schedule alive.

**Categories:** Exam 📝 · Registration/Add-Drop 🗓️ · Admission 🎓 · Result 📊 · Fee/Scholarship 💳 · Holiday 🏖️ · Event 🎉 · General 📢

**First run is silent:** it records the ~20 notices currently on the page and sends nothing. From then on you only get genuinely new ones. (A flood guard also re-seeds silently if an abnormal burst appears, e.g. after long downtime.)

## Automation (GitHub Actions)

The bot runs itself from [`.github/workflows/check-notices.yml`](.github/workflows/check-notices.yml) — no server required.

**Triggers**
- **Schedule** — four `cron:` lines run it 4×/day. GitHub cron is UTC-only, so each Dhaka time is written as `Dhaka − 6h` (Bangladesh has no DST, so this stays correct year-round):

  | Asia/Dhaka | UTC cron |
  |---|---|
  | 09:00 | `0 3 * * *` |
  | 13:00 | `0 7 * * *` |
  | 17:00 | `0 11 * * *` |
  | 21:00 | `0 15 * * *` |

- **Manual** — `workflow_dispatch` with a `mode` dropdown:
  - `run` (default) — full scrape → notify → commit state (same as a scheduled run)
  - `test` — sends one test Telegram message; writes no state, makes no commit

**Permissions** (declared at the top of the file):
- `contents: write` — lets the run commit the updated `state/` back to the repo
- `models: read` — lets the built-in `GITHUB_TOKEN` call the GitHub Models API for classification (no extra PAT needed)

**What a scheduled / `run` execution does**
1. `actions/checkout@v5` + `actions/setup-python@v6` (Python 3.12, pip cache)
2. `pip install -r requirements.txt`
3. `python src/main.py` — scrape, dedup, classify, notify
4. Commit `state/` back **only if it changed** (`git diff --cached --quiet` guard), authored as `github-actions[bot]`

**Safety & reliability**
- **No run loop:** a push made with `GITHUB_TOKEN` doesn't trigger new workflow runs, and `schedule` / `workflow_dispatch` never fire on pushes.
- **Schedule stays alive:** GitHub disables scheduled workflows on public repos after **60 days of inactivity**; the daily `state/last_check.txt` heartbeat commit keeps resetting that clock.
- **Fail-safe commit:** if scraping returns 0 notices, `main.py` exits non-zero, which (via the step's implicit `success()` guard) skips the commit — so a site redesign never overwrites good state.
- **Site outages are handled, not fatal:** the scraper retries 3× with backoff; if the site is still unreachable (it often **blocks traffic from outside Bangladesh**, which includes GitHub's runners), the run logs it and exits 0 — no red ✗, no failure email. Seen-notices state and the heartbeat are left untouched; the outage itself is tracked (and committed) in `state/outage.json`, whose daily update also keeps the schedule-alive clock ticking while the site is dark. Once it has been dark for **24 h** the bot DMs you a ⚠️ Telegram alert (repeated at most daily), and sends a ✅ once the site is back **and** parsing normally.
- **One run at a time:** a `concurrency` group queues overlapping runs instead of racing them.

## Setup (~5 minutes)

### 1. Create your Telegram bot
1. In Telegram, open [@BotFather](https://t.me/BotFather) → send `/newbot` → follow the prompts.
2. Copy the **bot token** it gives you (looks like `123456:ABC-DEF...`).
3. **Open your new bot and press _Start_** (send it any message). A bot can't message you until you message it first.

### 2. Get your chat ID
1. With the bot started, visit (replace `<TOKEN>`):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
2. Find `"chat":{"id":123456789,...}` in the JSON — that number is your **chat ID**.
   (Or message [@userinfobot](https://t.me/userinfobot), which replies with your ID.)

### 3. Fork this repo and add your secrets
1. **Fork** this repository to your own account — the **Fork** button at the top-right of
   [the repo page](https://github.com/ALPHAMAN-0/AIUB_NOTICE_BOARD). Keep your fork **public**
   so Actions minutes stay free. *(Or push your own copy anywhere — it just needs to be public.)*
2. In **your** fork: **Settings → Secrets and variables → Actions → New repository secret**, add:
   - `TELEGRAM_BOT_TOKEN` — the bot token from step 1
   - `TELEGRAM_CHAT_ID` — the chat ID from step 2

   *(`GITHUB_TOKEN` is provided automatically — do not add it.)*

### 4. Enable & verify
1. Open the **Actions** tab and enable workflows if prompted.
2. **AIUB Notice Check → Run workflow → mode: `test`** — you should get a test message in Telegram within a few seconds. ✅
3. Run it once more with **mode: `run`** to seed silently. After that, the 4×/day schedule takes over and you'll be messaged on new notices.

## Run locally

```bash
git clone https://github.com/ALPHAMAN-0/AIUB_NOTICE_BOARD.git
cd AIUB_NOTICE_BOARD

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN=...   # your bot token
export TELEGRAM_CHAT_ID=...     # your chat id
export GITHUB_TOKEN=$(gh auth token)   # optional: enables AI classification locally

python src/main.py --test       # send one synthetic Telegram message
python src/main.py --dry-run     # parse + classify + print; sends nothing, writes nothing
python src/main.py               # real run (sends + writes state)
```

## Customize

| Want to change… | Where |
|---|---|
| Check times | the four `cron:` lines in `.github/workflows/check-notices.yml` (UTC; Dhaka = UTC+6) |
| Categories / keywords | `CATEGORIES`, `CATEGORY_EMOJI`, `_KEYWORDS` in `src/classifier.py` |
| AI model | `DEFAULT_MODEL` in `src/classifier.py` (e.g. `openai/gpt-4.1-mini`) |
| Flood-guard threshold | `--threshold` flag / `DEFAULT_FLOOD_THRESHOLD` in `src/main.py` |
| Message layout | `format_message()` in `src/notifier.py` |

## When the AIUB site is unreachable

aiub.edu periodically **firewalls traffic from outside Bangladesh** (in June 2026 it went dark to every foreign network — GitHub's runners, archive.org's crawlers, everything — while staying up locally). No code change can get a blocked runner through a firewall, so the bot is built to ride it out:

1. **Each run retries 3×**, then skips cleanly (exit 0 — the workflow stays green, since a blocked site isn't a pipeline bug).
2. **After 24 h of continuous outage the bot DMs you** on Telegram, then at most once a day while it lasts (`state/outage.json` tracks this), and confirms with a ✅ message on recovery.
3. **Catch-up after recovery is best-effort:** dedup is by URL, so notices still on the listing page after an outage are delivered on the first successful run. But the page only shows ~20 items — anything that scrolled off during a long outage is missed — and a backlog above the flood threshold (15) is re-seeded silently instead of spamming you. For long outages, skim the notice page once after recovery.

If the block persists and you want live checks anyway, two options:
- **`AIUB_PROXY` secret** — set it to a proxy URL with a **Bangladesh exit** (`http://user:pass@host:port`). Only the scrape is routed through it; Telegram and GitHub Models calls stay direct, so your tokens never transit the proxy.
- **Self-hosted runner** — run the job from a machine inside Bangladesh (change `runs-on` accordingly).

## Notes
- **Cost:** free. Public-repo Actions minutes are unlimited; GitHub Models free tier (150 calls/day) dwarfs our ~20/day.
- **Reliability:** GitHub may delay scheduled runs under load — harmless here, since "any unseen notice" catches up on the next run.
- **If scraping ever returns 0 notices** (site redesign), the run aborts without touching state, so you won't get false "first run" floods. Update the selectors in `src/scraper.py` if the layout changes.
