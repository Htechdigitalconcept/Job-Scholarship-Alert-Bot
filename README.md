# Job & Scholarship Alert Bot (Public Telegram Channel + Commands)

A **100% free, zero-server** automation bot that scrapes recent job boards and scholarship portals, broadcasts matching alerts to a **public Telegram channel**, and answers interactive **user commands** (`/latest`, `/jobs`, `/scholarships`, `/keywords`, `/setkeywords`, `/sources`).

## Features
- **Public Telegram Channel Broadcast:** Posts fresh jobs & scholarships automatically to your `@your_channel` on a schedule.
- **Interactive User Commands & Inline Buttons:**
  - `/start`, `/help` — Welcome & channel invite link
  - `/latest` — 5 newest jobs, Web3 remote jobs & scholarships (with `Next 5 ▶` / `◀ Prev 5` inline pagination)
  - `/jobs [keyword]` — Filter recent remote jobs (e.g. `/jobs python`)
  - `/web3 [keyword]` — Filter recent Web3 remote jobs (e.g. `/web3 solidity`)
  - `/scholarships [keyword]` — Filter recent scholarships (e.g. `/scholarships africa`)
  - `/search <keyword>` — Search across all categories at once
  - `/worldwide [keyword]` — Filter 🌍 Worldwide remote opportunities
  - `/visa [keyword]` — Filter 🛂 Visa-sponsored opportunities
  - `/digest` — On-demand top opportunities digest (also auto-posted daily at `06:00 UTC` in the channel)
  - Channel posts include direct **Apply Now 🔗** + **Join Channel 📢** inline buttons, smart badges (`🌍 Worldwide`, `🛂 Visa Sponsored`, `💰 Fully Funded`, `🟢 Entry / Intern`), and extracted scholarship deadlines (`⏳`).
  - `/keywords` — View tracked include/exclude keywords
  - `/setkeywords <words>` — Set personal DM keywords & subscribe
  - `/subscribe` / `/unsubscribe` — Toggle personal DM alerts
  - `/sources` — Monitored feeds & recency window
- **Recency Filtering & Newest-First Sorting:** Filters out old posts (`max_post_age_days` in `config.yaml`: 3 days for jobs, 7 days for scholarships) and prioritizes the freshest opportunities first.
- **Two Free Command Modes:**
  1. **Instant 24/7 Replies (Vercel Serverless Webhook — Recommended):** Deploy this repo to Vercel's free tier (`api/webhook.py`) so `/latest`, `/jobs`, `/web3`, `/scholarships`, `/keywords`, and `/sources` reply in **<1 second**, while GitHub Actions continues scraping every 6 hours and updating `data/latest_items.json`.
  2. **Zero-server Scheduled Polling (GitHub Actions):** Runs `python bot_commands.py --once` every 6 hours (replies arrive on each scheduled run).

---

## Project Structure

```text
job-scholarship-alert-bot/
├── api/
│   └── webhook.py             # Vercel serverless endpoint for instant 24/7 replies
├── .github/workflows/
│   └── check_alerts.yml       # Scheduled scraper + fallback command polling
├── data/
│   ├── bot_state.json         # Tracks Telegram getUpdates offset
│   ├── latest_items.json      # Cached recent items for /latest, /jobs, /web3, /scholarships
│   └── seen_items.json        # Deduplication store
├── tests/
│   ├── test_bot_commands.py   # Command & webhook tests
│   └── test_scraper.py        # Scraper & recency tests
├── bot_commands.py            # Telegram slash-command handler
├── config.yaml                # Keywords, recency limits & RSS/HTML sources
├── requirements.txt           # Python dependencies
├── scraper.py                 # Main scraper & channel broadcaster
└── vercel.json                # Vercel routing config
```

---

## Enable Instant 24/7 Replies (Free on Vercel — 2 Minutes)

1. Go to **[vercel.com](https://vercel.com)** → **Add New Project** → import your `Job-Scholarship-Alert-Bot` GitHub repository.
2. Under **Environment Variables**, add:
   - `TELEGRAM_BOT_TOKEN` = your BotFather token
   - `TELEGRAM_CHANNEL_ID` = `@latestjobsandscholarship`
   - `TELEGRAM_WEBHOOK_SECRET` = *(optional random secret string)*
3. Click **Deploy**, then copy your deployment URL (e.g. `https://job-scholarship-alert-bot.vercel.app`).
4. Register the webhook with Telegram by opening this URL once in your browser (replace `<BOT_TOKEN>` and `<YOUR_VERCEL_URL>`):
   ```text
   https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://<YOUR_VERCEL_URL>/api/webhook
   ```
   *(If you set `TELEGRAM_WEBHOOK_SECRET`, pass `&secret_token=<YOUR_SECRET>` or run `python bot_commands.py --set-webhook https://<YOUR_VERCEL_URL>/api/webhook` locally.)*

Once the webhook is registered:
- Commands like `/start`, `/latest`, `/jobs`, `/web3`, `/scholarships`, `/keywords`, and `/sources` reply **instantly 24/7**.
- GitHub Actions continues running every 6 hours to post new alerts to `@latestjobsandscholarship` and update `data/latest_items.json` (which automatically keeps Vercel's cache up to date!).

---

## Setup Guide (Public Channel + Commands)

### 1. Add Your Bot to `@latestjobsandscholarship`
1. Make sure your bot (from **@BotFather**) is added as an **Administrator** of **[t.me/latestjobsandscholarship](https://t.me/latestjobsandscholarship)** with **Post Messages** permission.
2. `config.yaml` is already configured with:
   - `channel_id: "@latestjobsandscholarship"`
   - `public_channel_url: "https://t.me/latestjobsandscholarship"`

### 2. GitHub Secrets
In your GitHub repo, go to **Settings → Secrets and variables → Actions → Repository secrets**:
- `TELEGRAM_BOT_TOKEN` = your BotFather token
- `TELEGRAM_CHANNEL_ID` = `@latestjobsandscholarship` *(optional override since it is already set in `config.yaml`)*
- `TELEGRAM_CHAT_ID` = *(optional fallback)*

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
