<p align="center">
  <img src="assets/logo.png" alt="Jobs, Web3 &amp; Scholarships Live Board Logo" width="140" />
</p>

# Job, Web3 & Scholarship Alert Bot + Live Web Board

A **100% free, zero-server** automation platform that tracks recent remote software/tech jobs, **Web3 remote jobs**, and **fully funded scholarships & fellowships**, broadcasts curated alerts to **[t.me/latestjobsandscholarship](https://t.me/latestjobsandscholarship)** (`@latestjobsandscholarship`), replies **instantly 24/7** to interactive Telegram bot commands via Vercel serverless functions, and publishes an SEO- and AI-Search-ready **Live Web Board** at **[job-scholarship-alert-bot-chi.vercel.app](https://job-scholarship-alert-bot-chi.vercel.app/)**.

---

## Live Links & Endpoints

| Surface | URL | Purpose |
| :--- | :--- | :--- |
| **Live Web Board** | `https://job-scholarship-alert-bot-chi.vercel.app/` | Searchable, filterable dark-mode SSR board with Schema.org JSON-LD |
| **Public Telegram Channel** | `https://t.me/latestjobsandscholarship` | Automated alerts, inline Apply/Join buttons, and daily `06:00 UTC` digest |
| **JSON Feed API** | `https://job-scholarship-alert-bot-chi.vercel.app/api/opportunities` | Machine-readable JSON feed of up to 40 balanced recent opportunities |
| **Telegram Webhook** | `https://job-scholarship-alert-bot-chi.vercel.app/api/webhook` | `GET` healthcheck & `POST` instant 24/7 Telegram bot update handler |
| **AI Search Index** | `https://job-scholarship-alert-bot-chi.vercel.app/llms.txt` | Clean Markdown summary for AI search engines (`OAI-SearchBot`, `ClaudeBot`, `PerplexityBot`) |
| **Search Crawlers** | `/sitemap.xml`, `/robots.txt`, `/googlefee6033bceb7f78c.html` | Google Search Console verification, XML sitemap, and crawler directives |

---

## System Architecture

```text
  9 RSS / JSON / HTML Feeds
             │
             ▼  (Every 6 hours via GitHub Actions: scraper.py --digest-hour 6)
  ┌─────────────────────────────┐
  │  Recency + Keyword Filter   │  jobs/web3 <= 3 days | scholarships <= 7 days
  │  Smart Badges & Deadlines   │  🌍 Worldwide · 🛂 Visa · 💰 Fully Funded · 🟢 Entry
  │  Cross-Source Deduplication │  URL/item hash + normalized title hash ("t:...")
  └──────────────┬──────────────┘
                 │
        ┌────────┴──────────────────────┐
        ▼                               ▼
  Public Telegram Channel        Git Repo State Files (auto-committed)
  @latestjobsandscholarship       - data/seen_items.json (90-day retention)
  + Cycle Reminder every 6h       - data/latest_items.json (40 balanced items)
  + Subscriber Cycle DM Alerts    - data/bot_state.json
  + Daily Digest (06:00 UTC)            │
                                        ▼  (Auto-deployed on Vercel: api/webhook.py)
                     ┌──────────────────┴──────────────────┐
                     ▼                                     ▼
        Live Web Board & Feeds                 24/7 Instant Bot Webhook
        / · /api/opportunities                 POST /api/webhook
        /llms.txt · /sitemap.xml               16 slash commands + inline pagination
```

---

## Key Features

### 1. Opportunity Categories & Monitored Sources (9 Active Feeds)
Configured in `config.yaml`:

| Category | Label | Recency Window | Active Sources |
| :--- | :--- | :--- | :--- |
| **Remote Tech Jobs** (`jobs`) | `💼 Job Alert` | 3 days | Remotive Remote Jobs (RSS), We Work Remotely (RSS), Himalayas Remote Jobs (JSON API), Arbeitnow Remote & Visa (JSON API) |
| **Web3 Remote Jobs** (`web3_jobs`) | `⛓️ Web3 Remote Job` | 3 days | Cryptocurrency Jobs (RSS, with `require_keywords`: `remote`, `remotely`) |
| **Scholarships & Fellowships** (`scholarships`) | `🎓 Scholarship & Fellowship` | 7 days | Opportunity Desk (RSS), Opportunities For Africans (RSS), Scholars4Dev (RSS), AfterSchoolAfrica (RSS) |

*(An example disabled custom HTML career-page scraper entry is also included in `config.yaml` and can be enabled with CSS selectors.)*

### 2. Smart Enrichment & Deduplication
- **Smart Badges (`extract_badges`)**: Automatically tags opportunities with:
  - `🌍 Worldwide` (remote anywhere / global / EMEA / APAC / LATAM)
  - `🛂 Visa Sponsored` (visa sponsorship / relocation support)
  - `💰 Fully Funded` (full funding / full tuition / stipend)
  - `🟢 Entry / Intern` (junior / entry-level / intern / graduate)
- **Deadline Extraction (`extract_deadline`)**: Detects deadline phrases in titles and summaries (e.g. `Deadline: Dec 20, 2026`, `Apply by ...`, `Closes on ...`) and highlights them with `⏳`.
- **Cross-Source Deduplication (`normalize_title` & `make_title_id`)**: Tracks both item/URL hashes and normalized title IDs (`t:<sha256>`) in `data/seen_items.json` (pruned after 90 days) so identical reposts across multiple job boards or scholarship portals are never sent twice.
- **Balanced Category Caching (`save_latest_items`)**: Interleaves categories round-robin before slicing to `latest_cache_limit: 40`, preventing high-volume job feeds from crowding out Web3 roles or scholarships.

### 3. Interactive Telegram Bot Commands (16 Commands + Inline Pagination)
Handled instantly by `bot_commands.py` via `api/webhook.py` (with `409` polling conflict safety and read-only filesystem fallback on Vercel):

| Command | Description |
| :--- | :--- |
| `/start`, `/help` | Welcome guide, quick command overview, and link to `@latestjobsandscholarship` |
| `/latest` | 5 newest opportunities across all categories (with `◀ Prev 5` / `Next 5 ▶` inline buttons) |
| `/jobs [keyword]` | Recent remote software & tech jobs (e.g., `/jobs python`) |
| `/web3 [keyword]` | Recent Web3 & blockchain remote jobs (e.g., `/web3 solidity`) |
| `/scholarships [keyword]` | Recent funded scholarships & fellowships (e.g., `/scholarships africa`) |
| `/search <keyword>` | Multi-word search across every category at once |
| `/worldwide [keyword]` | Filter `🌍 Worldwide` remote opportunities |
| `/visa [keyword]` | Filter `🛂 Visa Sponsored` opportunities |
| `/digest` | On-demand summary digest of top cached roles & scholarships |
| `/stats` | Live breakdown of cached counts by category, smart badges, and tracked history |
| `/keywords` | View configured include, require, and exclude keywords |
| `/setkeywords <words>` | Save personal DM alert keywords & subscribe (e.g., `/setkeywords python, remote`) |
| `/subscribe` / `/unsubscribe` | Enable or pause personal DM keyword alerts |
| `/sources` | List all active feeds and recency windows |

### 4. Live Web Board, SEO & AI Search Optimization
Rendered by `web_board.py`:
- **Sticky Navigation & Interactive Hero**: Glassmorphic sticky top bar, pulsing live-sync indicator, gradient hero headline, Telegram CTAs, and clickable category KPI cards (`Total Cached`, `Remote Jobs`, `Web3 Remote`, `Scholarships`).
- **Instant Client-Side Filtering + SSR Cards**: Server-side renders `<article class="card">` elements for search crawlers while hydrating client-side search, category chips, and badge filters with zero external dependencies.
- **3-Column Footer**: Quick filter shortcuts, channel & feed links (`/api/opportunities`, `/llms.txt`, `/sitemap.xml`, `/robots.txt`), and smooth scroll-to-top.
- **Search & AI Indexing**:
  - OpenGraph, Twitter Card, canonical URL, and `X-Robots-Tag: index, follow` headers.
  - Schema.org JSON-LD graph (`WebSite` + `ItemList` with `JobPosting` / `CreativeWork` entries).
  - Dedicated `/robots.txt` explicitly allowing `Googlebot`, `Google-Extended`, `OAI-SearchBot`, `GPTBot`, `ChatGPT-User`, `PerplexityBot`, and `ClaudeBot` while disallowing `/api/webhook`.
  - Dynamic `/sitemap.xml` and `/llms.txt` Markdown index.

---

## Project Structure

```text
job-scholarship-alert-bot/
├── api/
│   ├── __init__.py
│   └── webhook.py                 # Vercel WSGI entrypoint (Web Board, SEO/AI routes, Webhook)
├── .github/workflows/
│   └── check_alerts.yml           # 6-hour cron + workflow_dispatch scraper & state committer
├── data/
│   ├── bot_state.json             # Tracks Telegram getUpdates offset
│   ├── latest_items.json          # 40 balanced recent opportunities for Web Board & bot commands
│   └── seen_items.json            # URL + normalized-title deduplication store (90-day TTL)
├── tests/
│   ├── test_bot_commands.py       # 9 unit tests (commands, pagination, WSGI routes, webhook)
│   └── test_scraper.py            # 15 unit tests (parsers, recency, badges, dedup, balancing)
├── bot_commands.py                # Command parser, callback pagination & webhook/polling runner
├── config.yaml                    # Channel settings, keywords, recency windows & 9 data sources
├── googlefee6033bceb7f78c.html    # Google Search Console verification file
├── MARKETING.md                   # Ready-to-use launch copy, channel templates & growth playbook
├── pyproject.toml                 # Python >=3.12 config & Vercel entrypoint declaration
├── README.md                      # Technical & operational reference
├── requirements.txt               # Runtime dependencies (requests, beautifulsoup4, PyYAML)
├── scraper.py                     # Multi-feed scraper, deduplicator, formatter & broadcaster
├── vercel.json                    # Minimal Vercel config
└── web_board.py                   # Self-contained SSR HTML, JSON-LD, robots, sitemap & llms.txt
```

---

## Configuration & Environment Variables

### GitHub Actions Secrets
Set under **GitHub → Settings → Secrets and variables → Actions**:
- `TELEGRAM_BOT_TOKEN` *(required)* — Bot token from `@BotFather`
- `TELEGRAM_CHANNEL_ID` *(optional override)* — Defaults to `@latestjobsandscholarship` in `config.yaml`
- `TELEGRAM_CHAT_ID` *(optional fallback)* — Fallback chat ID if no channel is configured
- `SUBSCRIBERS_GIST_ID` & `SUBSCRIBERS_GITHUB_TOKEN` *(optional)* — Private GitHub Gist ID + token so `/subscribe` DM cycle reminders sync 24/7 between Vercel and GitHub Actions

### Vercel Environment Variables
Set under **Vercel Project → Settings → Environment Variables** (Production):
- `TELEGRAM_BOT_TOKEN` *(required)* — Bot token from `@BotFather`
- `TELEGRAM_CHANNEL_ID` *(optional)* — `@latestjobsandscholarship`
- `TELEGRAM_WEBHOOK_SECRET` *(optional, recommended)* — Verified against `X-Telegram-Bot-Api-Secret-Token`
- `PUBLIC_SITE_URL` *(optional)* — Overrides auto-detected `https://<host>` for canonical/sitemap URLs
- `SUBSCRIBERS_GIST_ID` & `SUBSCRIBERS_GITHUB_TOKEN` *(optional)* — Enables 24/7 `/subscribe` and `/setkeywords` persistence on Vercel without exposing user chat IDs in your public repo

---

## Local Development & Testing

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1. Dry-run scraper + digest preview without posting to Telegram
python scraper.py --dry-run --digest

# 2. Run all 24 unit tests
python -m unittest discover -s tests -v

# 3. Run local WSGI dev server to preview Web Board & endpoints
python -c "
from wsgiref.simple_server import make_server
from api.webhook import app
print('Serving on http://127.0.0.1:8000')
make_server('127.0.0.1', 8000, app).serve_forever()
"

# 4. Register / update Telegram webhook URL
export TELEGRAM_BOT_TOKEN="your-bot-token"
python bot_commands.py --set-webhook https://job-scholarship-alert-bot-chi.vercel.app/api/webhook
```

> **Privacy note:** `data/subscribers.json` is listed in `.gitignore` so personal user IDs from `/subscribe` or `/setkeywords` are never committed to a public repository.
