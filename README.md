# Job & Scholarship Alert Bot (Python + Telegram + GitHub Actions)

A **100% free, zero-server** automation bot that checks public job boards and scholarship portals on a schedule using GitHub Actions and sends matching opportunities straight to your **Telegram** chat.

## Features
- **Zero hosting cost:** Runs inside GitHub Actions' free tier (2,000+ free minutes/month on private repos, unlimited on public repos).
- **Jobs + Scholarships in one config:** Track remote/tech jobs alongside fully funded scholarships & fellowships in `config.yaml`.
- **Smart keyword filtering:** Supports `include_keywords` (whole-word matching so `intern` doesn't falsely match `international`) and `exclude_keywords`.
- **RSS + HTML support:** Works out-of-the-box with RSS/Atom feeds and lets you add custom HTML career/scholarship pages via CSS selectors.
- **Automatic deduplication:** Stores seen links in `data/seen_items.json` and auto-prunes old entries after 90 days.

---

## Project Structure

```text
job-scholarship-alert-bot/
├── .github/
│   └── workflows/
│       └── check_alerts.yml   # Runs every 6 hours & commits seen_items.json
├── data/
│   └── seen_items.json        # Tracks already-sent opportunities
├── tests/
│   └── test_scraper.py        # Unit tests
├── config.yaml                # Your keywords and RSS/HTML sources
├── requirements.txt           # Python dependencies
└── scraper.py                 # Main scraper & Telegram notifier
```

---

## 5-Minute Setup Guide

### 1. Create a Free Telegram Bot
1. Open Telegram and message **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot`, choose a name and username, and copy the **Bot Token** (`123456:ABC-DEF...`).
3. Start a chat with your new bot and send `/start` (or add the bot to a Telegram group/channel where you want alerts).
4. Get your **Chat ID**:
   - Open `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` in a browser (after sending a message to your bot), and look for `"chat":{"id": 123456789}`.
   - Or message `@userinfobot` on Telegram to get your personal user ID.

### 2. Push to GitHub
Create a new GitHub repository (private or public) and push this folder:

```bash
git init
git add .
git commit -m "Initial job & scholarship alert bot"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

### 3. Add GitHub Secrets
In your GitHub repository, go to:
**Settings → Secrets and variables → Actions → New repository secret**

Add these two secrets:
- `TELEGRAM_BOT_TOKEN` = your BotFather token
- `TELEGRAM_CHAT_ID` = your chat or channel ID

*(Note: `.github/workflows/check_alerts.yml` already includes `permissions: contents: write` so the bot can commit `data/seen_items.json` automatically.)*

### 4. Test Manually
Go to the **Actions** tab in GitHub → **Job & Scholarship Alert Scraper** → **Run workflow**.

---

## Local Testing (Dry Run)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Preview matching opportunities in your terminal without messaging Telegram
python scraper.py --dry-run
```

To run the unit tests:

```bash
python -m unittest discover -s tests -v
```

---

## Customizing Sources & Keywords

Open `config.yaml`:
- Add/remove terms under `include_keywords` and `exclude_keywords` for `jobs` or `scholarships`.
- Toggle feeds with `enabled: true` / `false`.
- Set `seed_only_on_first_run: true` if you want the first run to silently record existing posts and only alert you about brand-new postings going forward.
