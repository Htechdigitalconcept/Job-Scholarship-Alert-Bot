# Job & Scholarship Alert Bot (Public Telegram Channel + Commands)

A **100% free, zero-server** automation bot that scrapes recent job boards and scholarship portals, broadcasts matching alerts to a **public Telegram channel**, and answers interactive **user commands** (`/latest`, `/jobs`, `/scholarships`, `/keywords`, `/setkeywords`, `/sources`).

## Features
- **Public Telegram Channel Broadcast:** Posts fresh jobs & scholarships automatically to your `@your_channel` on a schedule.
- **Interactive User Commands:**
  - `/start`, `/help` — Welcome & channel invite link
  - `/latest` — 5 newest jobs & scholarships
  - `/jobs [keyword]` — Filter recent jobs (e.g. `/jobs python`)
  - `/scholarships [keyword]` — Filter recent scholarships (e.g. `/scholarships africa`)
  - `/keywords` — View tracked include/exclude keywords
  - `/setkeywords <words>` — Set personal DM keywords & subscribe
  - `/subscribe` / `/unsubscribe` — Toggle personal DM alerts
  - `/sources` — Monitored feeds & recency window
- **Recency Filtering & Newest-First Sorting:** Filters out old posts (`max_post_age_days` in `config.yaml`: 3 days for jobs, 7 days for scholarships) and prioritizes the freshest opportunities first.
- **Two Free Command Modes:**
  1. **Zero-server (GitHub Actions):** Runs `python bot_commands.py --once` alongside `scraper.py` every 6 hours (replies arrive on each run).
  2. **Instant Replies (Long Polling):** Run `python bot_commands.py` on any free Python host (or locally) for immediate <1s replies and persisted personal DM subscriptions.

---

## Project Structure

```text
job-scholarship-alert-bot/
├── .github/workflows/
│   └── check_alerts.yml       # Scheduled scraper + command polling
├── data/
│   ├── bot_state.json         # Tracks Telegram getUpdates offset
│   ├── latest_items.json      # Cached recent items for /latest, /jobs, /scholarships
│   └── seen_items.json        # Deduplication store
├── tests/
│   ├── test_bot_commands.py   # Command handler tests
│   └── test_scraper.py        # Scraper & recency tests
├── bot_commands.py            # Telegram slash-command handler
├── config.yaml                # Keywords, recency limits & RSS/HTML sources
├── requirements.txt           # Python dependencies
└── scraper.py                 # Main scraper & channel broadcaster
```

---

## Setup Guide (Public Channel + Commands)

### 1. Create Your Telegram Bot & Public Channel
1. Message **[@BotFather](https://t.me/BotFather)** → `/newbot` → copy your `TELEGRAM_BOT_TOKEN`.
2. Create a **Public Telegram Channel** (e.g. `@TechJobsAndScholarships`).
3. Open your channel's **Administrators → Add Admin**, search for your bot, and grant **Post Messages**.
4. Note your channel username (e.g. `@TechJobsAndScholarships`).

### 2. Configure GitHub Secrets
In your GitHub repo, go to **Settings → Secrets and variables → Actions → Repository secrets**:
- `TELEGRAM_BOT_TOKEN` = your BotFather token
- `TELEGRAM_CHANNEL_ID` = your public channel username (e.g. `@TechJobsAndScholarships`)
- `TELEGRAM_CHAT_ID` = *(optional fallback if you also keep your personal chat ID)*

> **Privacy note:** `data/subscribers.json` is listed in `.gitignore` so personal user IDs from `/subscribe` or `/setkeywords` are never committed to a public repository. If you want persisted personal DMs across runs, run `python bot_commands.py` on a private host or keep your repository **Private**.

### 3. Test Locally
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Test scraping + recency filtering without posting to Telegram
python scraper.py --dry-run

# Run all unit tests
python -m unittest discover -s tests -v

# Run instant interactive command polling locally (optional)
export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_CHANNEL_ID="@your_channel"
python bot_commands.py
```
