<p align="center">
  <img src="assets/logo.png" alt="Jobs, Web3 &amp; Scholarships Live Board Logo" width="140" />
</p>

# Job, Web3 & Scholarship Alert Bot + Live Web Board & Mini App

A **100% free, zero-server** automation platform that tracks recent remote software/tech jobs, **Web3 remote jobs**, and **fully funded scholarships & fellowships**, broadcasts curated alerts to **[t.me/latestjobsandscholarship](https://t.me/latestjobsandscholarship)** (`@latestjobsandscholarship`), replies **instantly 24/7** via **[@Scholar_job_bot](https://t.me/Scholar_job_bot)** on Vercel serverless functions, launches natively as a **Telegram Mini App** (**[t.me/Scholar_job_bot/RJS](https://t.me/Scholar_job_bot/RJS)**), and publishes an SEO- and AI-Search-ready **Live Web Board** at **[job-scholarship-alert-bot-chi.vercel.app](https://job-scholarship-alert-bot-chi.vercel.app/)**.

---

## Live Links & Endpoints

| Surface | URL | Purpose |
| :--- | :--- | :--- |
| **Live Web Board** | `https://job-scholarship-alert-bot-chi.vercel.app/` | Mobile-first, paginated (24/page) SSR board with One-Tap `📝 Pitch` modal & Schema.org JSON-LD |
| **Telegram Mini App** | `https://t.me/Scholar_job_bot/RJS` | Native in-Telegram Mini App (`telegram-web-app.js` SDK, theme sync, BackButton, `Open Board` menu) |
| **Telegram Bot** | `https://t.me/Scholar_job_bot` | Instant 24/7 commands, inline search (`@Scholar_job_bot <query>`), `📝 Pitch #1–#5` & cycle DMs |
| **Public Telegram Channel** | `https://t.me/latestjobsandscholarship` | Automated alerts, `Filter in Bot 🤖` + `Share 📤` buttons, 6h cycle reminders & `06:00 UTC` digest |
| **JSON Feed API** | `https://job-scholarship-alert-bot-chi.vercel.app/api/opportunities` | Filterable JSON feed (`?q=`, `?cat=`, `?badge=`, `?limit=`, `?page=`) of up to 200 fresh items |
| **RSS 2.0 Feed** | `https://job-scholarship-alert-bot-chi.vercel.app/feed.xml` | Standard RSS feed for feed readers, syndication & search crawlers (`/rss.xml` alias) |
| **Telegram Webhook** | `https://job-scholarship-alert-bot-chi.vercel.app/api/webhook` | `GET` healthcheck & `POST` instant 24/7 Telegram bot update handler |
| **AI Search Index** | `https://job-scholarship-alert-bot-chi.vercel.app/llms.txt` | Clean Markdown summary for AI search engines (`OAI-SearchBot`, `ClaudeBot`, `PerplexityBot`) |
| **Search & Brand Assets** | `/sitemap.xml`, `/robots.txt`, `/logo.png`, `/favicon.png`, `/googlefee6033bceb7f78c.html` | Google Search Console verification, XML sitemap, crawler directives & brand icons |

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
  + Filter in Bot / Share btns    - data/latest_items.json (up to 200 balanced items)
  + Cycle Reminder every 6h       - data/bot_state.json
  + Subscriber Cycle DM Alerts          │
  + Daily Digest (06:00 UTC)            ▼  (Auto-deployed on Vercel: api/webhook.py)
                     ┌──────────────────┴──────────────────┐
                     ▼                                     ▼
        Live Web Board & Mini App              24/7 Instant Bot Webhook
        / · /feed.xml · /api/opportunities     POST /api/webhook (@Scholar_job_bot)
        /llms.txt · /sitemap.xml               19 commands, inline_query & 📝 Pitch #1–#5
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

### 2. Smart Enrichment, Quiet Alerts & Deduplication
- **Smart Badges (`extract_badges`)**: Automatically tags opportunities with:
  - `🌍 Worldwide` (remote anywhere / global / EMEA / APAC / LATAM)
  - `🛂 Visa Sponsored` (visa sponsorship / relocation support)
  - `💰 Fully Funded` (full funding / full tuition / stipend)
  - `🟢 Entry / Intern` (junior / entry-level / intern / graduate)
- **Deadline Extraction (`extract_deadline`)**: Detects deadline phrases in titles and summaries (e.g. `Deadline: Dec 20, 2026`, `Apply by ...`, `Closes on ...`) and highlights them with `⏳`.
- **Cross-Source Deduplication (`normalize_title` & `make_title_id`)**: Tracks both item/URL hashes and normalized title IDs (`t:<sha256>`) in `data/seen_items.json` (pruned after 90 days) so identical reposts across multiple job boards or scholarship portals are never sent twice.
- **Balanced 200-Item Caching (`save_latest_items`)**: Interleaves categories round-robin before slicing to `latest_cache_limit: 200`, preventing high-volume job feeds from crowding out Web3 roles or scholarships while keeping the board fast and fresh.
- **Per-Cycle Notification Reminder (`cycle_reminder` & `quiet_item_alerts`)**: Sends individual channel posts silently and emits a single 🔔 Cycle Update summary reminder (and optional subscriber DMs) at the end of every cycle with new posts.

### 3. Interactive Telegram Bot & Mini App (`@Scholar_job_bot`)
Handled instantly by `bot_commands.py` via `api/webhook.py` (with `ensure_webhook_callbacks`, `setChatMenuButton` auto-sync, `409` polling conflict safety, and read-only filesystem fallback on Vercel):

| Command | Access | Description |
| :--- | :--- | :--- |
| `/start`, `/help` | Free | Welcome guide, `📱 Open Mini App` button, channel link, and `🎁 Invite 3 Friends` share link |
| `/latest` | Free | 5 newest opportunities across all categories (with `◀ Prev 5` / `Next 5 ▶` & `📝 Pitch #1–#5`) |
| `/jobs [keyword]` | Free | Recent remote software & tech jobs (e.g., `/jobs python`) |
| `/web3 [keyword]` | Free | Recent Web3 & blockchain remote jobs (e.g., `/web3 solidity`) |
| `/scholarships [keyword]` | Free | Recent funded scholarships & fellowships (e.g., `/scholarships africa`) |
| `/search <keyword>` | Free | Multi-word search across every category at once |
| `/worldwide [keyword]` | Free | Filter `🌍 Worldwide` remote opportunities |
| `/visa [keyword]` | Free | Filter `🛂 Visa Sponsored` opportunities |
| `/expiring` | Free | Opportunities with closing-soon deadlines sorted first |
| `/digest` | Free | On-demand summary digest of top cached roles & scholarships |
| `/stats` | Free | Live breakdown of cached counts by category, smart badges, and tracked history |
| `/pitch [index\|word]` | 1 Free Preview + 3-Friend Unlock | Tailored application email / Scholarship SOP pitch, ATS checklist & clickable `/pitch_<n>` links |
| `/share` | Free | Personal referral invite link, `0/3` progress bar, Mini App link & inline share triggers |
| `/tools` | Free | Recommended global USD/EUR/GBP payout & career tools (`recommended_tools` in `config.yaml`) |
| `/keywords` | Free | View configured include, require, and exclude keywords |
| `/setkeywords <words>` | Free | Save personal DM alert keywords & subscribe (e.g., `/setkeywords python, remote`) |
| `/subscribe` / `/unsubscribe` | Free | Enable or pause cycle reminder DMs |
| `/sources` | Free | List all active feeds and recency windows |
| `@Scholar_job_bot <query>` | Free | Inline search mode for sharing any job or scholarship inside any Telegram chat |

> **Referral & Access Policy:** All feeds, `/expiring`, `/setkeywords`, and the Web Board remain **100% free**. Only unlimited `/pitch` (`📝 Pitch #1–#5`) in Telegram unlocks after **3 friend referrals** (following 1 free preview; the bot owner's `TELEGRAM_CHAT_ID` is automatically unlocked).

### 4. Live Web Board, Telegram Mini App, Pitch Modal & Partner Tools
Rendered by `web_board.py`:
- **Mobile-First Responsive UI (`320px+`)**: Sticky glassmorphic top bar, pulsing live-sync indicator, swipeable filter chips, `16px` zoom-safe search input, and `44px` tap targets.
- **24-Per-Page Pagination & Transparent Cap**: Server-side renders the first `24` cards for fast initial load and hydrates client-side `24`-per-page pagination (`#paginationBar`) across up to **200** recent deduplicated opportunities, explaining the freshness cap clearly to visitors.
- **One-Tap `📝 Pitch` Modal (`#pitchModal`)**: Every card includes a **`📝 Pitch`** button opening an editable outreach/SOP template, tailored ATS prep checklist, **Copy Pitch**, direct Apply link, and remote payout tip.
- **Telegram Mini App SDK (`telegram-web-app.js`)**: Automatically calls `ready()`, `expand()`, sets dark header/background colors, binds Telegram's native `BackButton` to close `#pitchModal`, and opens `t.me/...` links natively via `openTelegramLink`.
- **One-Tap Share Strip (`#shareBoardBtn` & `.share-strip`)**: Clear sharing prompt with direct Telegram, WhatsApp, X/Twitter, LinkedIn, and Copy Link buttons.
- **Config-Driven Recommended Tools (`#tools` / `settings.recommended_tools`)**: Showcases curated partner tools—starting with **Raenest** (`https://referral.raenest.com/WzbV/i?referral_code=adehab359122`) for global USD/EUR/GBP remote salaries & stipends—on the Web Board, inside `#pitchModal`, in `/tools`, and inside `/pitch` replies.
- **SEO & AI Search Indexing**:
  - OpenGraph, Twitter Card, canonical URL, `/feed.xml` RSS 2.0, and `X-Robots-Tag: index, follow`.
  - Schema.org JSON-LD graph (`WebSite` + `ItemList` with `JobPosting` / `CreativeWork` entries).
  - `/robots.txt` explicitly welcoming `Googlebot`, `Google-Extended`, `OAI-SearchBot`, `GPTBot`, `ChatGPT-User`, `PerplexityBot`, and `ClaudeBot` while disallowing `/api/webhook`.
  - Dynamic `/sitemap.xml` and `/llms.txt` Markdown index.

---

## Project Structure

```text
job-scholarship-alert-bot/
├── api/
│   ├── __init__.py
│   └── webhook.py                 # Vercel WSGI entrypoint (Web Board, Mini App, SEO/RSS/API, Webhook)
├── assets/
│   ├── logo.png                   # 512x512 brand mark (/logo.png)
│   ├── logo-icon.png              # 96x96 navbar/footer inline icon
│   └── favicon.png                # 64x64 favicon (/favicon.png)
├── .github/workflows/
│   └── check_alerts.yml           # 6-hour cron + workflow_dispatch scraper, profile sync & committer
├── data/
│   ├── bot_state.json             # Tracks Telegram getUpdates offset
│   ├── latest_items.json          # Up to 200 balanced recent opportunities for Web Board & bot
│   └── seen_items.json            # URL + normalized-title deduplication store (90-day TTL)
├── tests/
│   ├── test_bot_commands.py       # 12 unit tests (commands, referrals, Pitch, Mini App, tools, WSGI)
│   └── test_scraper.py            # 16 unit tests (parsers, recency, badges, dedup, reminders)
├── bot_commands.py                # Command parser, referral gate, Pitch, Mini App menu & webhook runner
├── config.yaml                    # Channel, Mini App, recommended_tools, keywords & 9 data sources
├── googlefee6033bceb7f78c.html    # Google Search Console verification file
├── MARKETING.md                   # Launch copy, channel templates, directories & monetization playbook
├── pyproject.toml                 # Python >=3.12 config & Vercel entrypoint declaration
├── README.md                      # Technical & operational reference
├── requirements.txt               # Runtime dependencies (requests, beautifulsoup4, PyYAML)
├── scraper.py                     # Multi-feed scraper, deduplicator, formatter & cycle broadcaster
├── vercel.json                    # Minimal Vercel config
└── web_board.py                   # Self-contained SSR HTML, Mini App SDK, Pitch modal, RSS & SEO
```

---

## Configuration & Environment Variables

### GitHub Actions Secrets
Set under **GitHub → Settings → Secrets and variables → Actions**:
- `TELEGRAM_BOT_TOKEN` *(required)* — Bot token from `@BotFather`
- `TELEGRAM_CHANNEL_ID` *(optional override)* — Defaults to `@latestjobsandscholarship` in `config.yaml`
- `TELEGRAM_CHAT_ID` *(optional fallback)* — Fallback owner chat ID (also auto-unlocked for `/pitch`)
- `SUBSCRIBERS_GIST_ID` & `SUBSCRIBERS_GITHUB_TOKEN` *(optional)* — Private GitHub Gist ID + token so `/subscribe`, `/setkeywords`, and referral progress sync 24/7 between Vercel and GitHub Actions

### Vercel Environment Variables
Set under **Vercel Project → Settings → Environment Variables** (Production):
- `TELEGRAM_BOT_TOKEN` *(required)* — Bot token from `@BotFather`
- `TELEGRAM_CHANNEL_ID` *(optional)* — `@latestjobsandscholarship`
- `TELEGRAM_CHAT_ID` *(optional)* — Owner chat ID for `/pitch` bypass
- `TELEGRAM_BOT_USERNAME` *(optional)* — Defaults to `Scholar_job_bot` in `config.yaml`
- `TELEGRAM_WEBHOOK_SECRET` *(optional, recommended)* — Verified against `X-Telegram-Bot-Api-Secret-Token`
- `PUBLIC_SITE_URL` *(optional)* — Overrides auto-detected `https://<host>` for canonical/sitemap/Mini App URLs
- `SUBSCRIBERS_GIST_ID` & `SUBSCRIBERS_GITHUB_TOKEN` *(optional)* — Enables 24/7 `/subscribe`, `/setkeywords`, and referral persistence on Vercel without committing user chat IDs to a public repo

---

## Local Development & Testing

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1. Dry-run scraper + digest preview without posting to Telegram
python scraper.py --dry-run --digest

# 2. Run all 28 unit tests
python -m unittest discover -s tests -v

# 3. Sync bot commands, bio & Mini App menu button ("Open Board")
export TELEGRAM_BOT_TOKEN="your-bot-token"
python bot_commands.py --sync-profile

# 4. Run local WSGI dev server to preview Web Board & endpoints
python -c "
from wsgiref.simple_server import make_server
from api.webhook import app
print('Serving on http://127.0.0.1:8000')
make_server('127.0.0.1', 8000, app).serve_forever()
"

# 5. Register / update Telegram webhook URL (includes callback_query & inline_query)
python bot_commands.py --set-webhook https://job-scholarship-alert-bot-chi.vercel.app/api/webhook
```

> **Privacy note:** `data/subscribers.json` is listed in `.gitignore` so personal user IDs from `/subscribe`, `/setkeywords`, or referrals are never committed to a public repository.
