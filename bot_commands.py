#!/usr/bin/env python3
"""Interactive Telegram command handler for the Job & Scholarship Alert Bot.

Supports two execution modes:
  1. `python bot_commands.py --once`  -> Process pending updates and exit (GitHub Actions).
  2. `python bot_commands.py`         -> Long-polling loop for instant replies (always-on host).
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

import scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path("data/bot_state.json")

BOT_COMMANDS_MENU = [
    {"command": "start", "description": "Welcome & public channel link"},
    {"command": "latest", "description": "Latest jobs, Web3 & scholarships"},
    {"command": "jobs", "description": "Latest remote jobs (optional: /jobs python)"},
    {"command": "web3", "description": "Latest Web3 remote jobs (optional: /web3 solidity)"},
    {"command": "scholarships", "description": "Latest scholarships (optional: /scholarships africa)"},
    {"command": "keywords", "description": "View tracked keywords"},
    {"command": "setkeywords", "description": "Set personal DM keywords"},
    {"command": "subscribe", "description": "Enable personal DM alerts"},
    {"command": "unsubscribe", "description": "Pause personal DM alerts"},
    {"command": "sources", "description": "View monitored feeds & age limit"},
    {"command": "help", "description": "Show command guide"},
]


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"last_update_id": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read %s (%s); resetting state.", path, exc)
    return {"last_update_id": 0}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def save_subscribers(path: Path, subscribers: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(subscribers, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def register_bot_commands(bot_token: str) -> None:
    """Register the slash command menu in Telegram."""
    url = f"https://api.telegram.org/bot{bot_token}/setMyCommands"
    try:
        resp = requests.post(url, json={"commands": BOT_COMMANDS_MENU}, timeout=15)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not register Telegram command menu: %s", exc)


def get_updates(bot_token: str, offset: int, timeout: int = 0) -> list[dict[str, Any]]:
    """Fetch pending updates from Telegram Bot API."""
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params: dict[str, Any] = {
        "offset": offset,
        "timeout": timeout,
        "allowed_updates": json.dumps(["message"]),
    }
    resp = requests.get(url, params=params, timeout=timeout + 15)
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("ok"):
        return []
    return payload.get("result", [])


def get_channel_display(config: dict[str, Any] | None = None) -> str:
    """Return a user-friendly public channel handle or URL if configured."""
    url = os.environ.get("PUBLIC_CHANNEL_URL", "").strip()
    if url:
        return url
    handle = os.environ.get("PUBLIC_CHANNEL_HANDLE", "").strip()
    if handle:
        return handle
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
    if channel_id.startswith("@"):
        return f"https://t.me/{channel_id[1:]}"
    if config:
        settings = config.get("settings", {})
        cfg_url = str(settings.get("public_channel_url", "")).strip()
        if cfg_url:
            return cfg_url
        cfg_id = str(settings.get("channel_id", "")).strip()
        if cfg_id.startswith("@"):
            return f"https://t.me/{cfg_id[1:]}"
    return ""


def get_recent_opportunities(
    config: dict[str, Any],
    latest_path: Path,
) -> list[scraper.Opportunity]:
    """Read recent cached opportunities, or fall back to live scrape if cache is empty."""
    cached = scraper.load_latest_items(latest_path)
    if cached:
        return cached
    live = scraper.collect_opportunities(config)
    limit = int(config.get("settings", {}).get("latest_cache_limit", 40))
    return scraper.save_latest_items(latest_path, live, config, limit=limit)


def format_compact_list(
    heading: str,
    items: list[scraper.Opportunity],
    empty_hint: str,
) -> str:
    """Format a compact multi-item Telegram HTML message."""
    if not items:
        return f"<b>{html.escape(heading)}</b>\n\n{html.escape(empty_hint)}"

    lines = [f"<b>{html.escape(heading)}</b>"]
    for idx, item in enumerate(items, start=1):
        title = html.escape(item.title)
        link = html.escape(item.link, quote=True)
        source = html.escape(item.source_name)
        tags = html.escape(", ".join(item.matched_keywords))
        date_line = f" · 🗓 {html.escape(item.published)}" if item.published else ""
        lines.append(
            f"{idx}. <b><a href=\"{link}\">{title}</a></b>\n"
            f"   <i>{source}</i>{date_line}\n"
            f"   🏷 <code>{tags}</code>"
        )
    return "\n\n".join(lines)


def format_keywords_message(
    config: dict[str, Any],
    user_prefs: dict[str, Any] | None = None,
) -> str:
    """Format tracked keywords for /keywords."""
    lines = ["<b>🔎 Active Tracked Keywords</b>"]
    for cat_key, cat_cfg in config.get("categories", {}).items():
        label = html.escape(cat_cfg.get("label", cat_key.title()))
        inc = ", ".join(cat_cfg.get("include_keywords", [])) or "all"
        exc = ", ".join(cat_cfg.get("exclude_keywords", [])) or "none"
        max_age = cat_cfg.get(
            "max_post_age_days",
            config.get("settings", {}).get("max_post_age_days", "unlimited"),
        )
        lines.append(
            f"<b>{label}</b> (last {html.escape(str(max_age))} days)\n"
            f"✅ Include: <code>{html.escape(inc)}</code>\n"
            f"🚫 Exclude: <code>{html.escape(exc)}</code>"
        )

    if user_prefs and user_prefs.get("keywords"):
        personal = ", ".join(user_prefs["keywords"])
        status = "active" if user_prefs.get("subscribed") else "paused"
        lines.append(
            f"<b>👤 Your Personal DM Keywords</b> ({status})\n"
            f"<code>{html.escape(personal)}</code>"
        )
    else:
        lines.append(
            "💡 Want personal DM filtering? Send:\n"
            "<code>/setkeywords python, backend, fully funded</code>"
        )
    return "\n\n".join(lines)


def format_sources_message(config: dict[str, Any]) -> str:
    """Format monitored feeds for /sources."""
    lines = ["<b>📡 Monitored Sources</b>"]
    default_age = config.get("settings", {}).get("max_post_age_days", 3)
    for cat_key, cat_cfg in config.get("categories", {}).items():
        label = html.escape(cat_cfg.get("label", cat_key.title()))
        age = cat_cfg.get("max_post_age_days", default_age)
        enabled_sources = [
            s.get("name", s.get("url", "Unknown"))
            for s in cat_cfg.get("sources", [])
            if s.get("enabled", True)
        ]
        if enabled_sources:
            bullet_list = "\n".join(f"• {html.escape(name)}" for name in enabled_sources)
        else:
            bullet_list = "• None enabled"
        lines.append(f"<b>{label}</b> (recent ≤ {html.escape(str(age))} days)\n{bullet_list}")
    return "\n\n".join(lines)


def handle_command(
    chat_id: str,
    text: str,
    config: dict[str, Any],
    latest_path: Path,
    subscribers_path: Path,
) -> list[str]:
    """Parse a user command and return one or more HTML reply strings."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return []

    parts = stripped.split(maxsplit=1)
    raw_cmd = parts[0].lower()
    # Strip @BotUsername suffix in group chats
    cmd = raw_cmd.split("@", 1)[0]
    arg = parts[1].strip() if len(parts) > 1 else ""

    channel_link = get_channel_display(config)

    if cmd in {"/start", "/help"}:
        channel_line = (
            f"\n\n📢 <b>Public Alert Channel:</b> {html.escape(channel_link)}"
            if channel_link
            else ""
        )
        return [
            "<b>👋 Job & Scholarship Alert Bot</b>\n"
            "Get fresh remote jobs, fellowships, and funded scholarships."
            f"{channel_line}\n\n"
            "<b>Available Commands:</b>\n"
            "• /latest — 5 newest jobs, Web3 & scholarships\n"
            "• /jobs [keyword] — Latest remote jobs (e.g. <code>/jobs python</code>)\n"
            "• /web3 [keyword] — Latest Web3 remote jobs (e.g. <code>/web3 rust</code>)\n"
            "• /scholarships [keyword] — Latest scholarships\n"
            "• /keywords — View tracked keywords\n"
            "• /setkeywords &lt;words&gt; — Set personal DM alert keywords\n"
            "• /subscribe / /unsubscribe — Manage personal DM alerts\n"
            "• /sources — Monitored feeds & recency window"
        ]

    if cmd == "/keywords":
        subscribers = scraper.load_subscribers(subscribers_path)
        return [format_keywords_message(config, subscribers.get(chat_id))]

    if cmd == "/sources":
        return [format_sources_message(config)]

    if cmd == "/setkeywords":
        keywords = [kw.strip() for kw in arg.split(",") if kw.strip()]
        if not keywords:
            return [
                "Please provide comma-separated keywords, for example:\n"
                "<code>/setkeywords python, backend, fully funded</code>"
            ]
        subscribers = scraper.load_subscribers(subscribers_path)
        subscribers[chat_id] = {
            "subscribed": True,
            "keywords": keywords,
        }
        save_subscribers(subscribers_path, subscribers)
        return [
            "✅ <b>Personal keywords saved &amp; DM alerts enabled!</b>\n"
            f"🏷 <code>{html.escape(', '.join(keywords))}</code>\n\n"
            "Send /unsubscribe anytime to pause personal DMs."
        ]

    if cmd == "/subscribe":
        subscribers = scraper.load_subscribers(subscribers_path)
        existing = subscribers.get(chat_id, {})
        existing["subscribed"] = True
        existing.setdefault("keywords", [])
        subscribers[chat_id] = existing
        save_subscribers(subscribers_path, subscribers)
        kw_note = (
            f"Filtering by: <code>{html.escape(', '.join(existing['keywords']))}</code>"
            if existing["keywords"]
            else "Receiving all channel matches. Use /setkeywords to narrow down."
        )
        return [f"✅ <b>Subscribed to personal DM alerts!</b>\n{kw_note}"]

    if cmd == "/unsubscribe":
        subscribers = scraper.load_subscribers(subscribers_path)
        if chat_id in subscribers:
            subscribers[chat_id]["subscribed"] = False
            save_subscribers(subscribers_path, subscribers)
        return ["🔕 <b>Personal DM alerts paused.</b> Send /subscribe anytime to resume."]

    if cmd in {"/latest", "/jobs", "/web3", "/scholarships"}:
        items = get_recent_opportunities(config, latest_path)

        if cmd == "/latest":
            limit = 5
            if arg.isdigit():
                limit = max(1, min(10, int(arg)))
            ordered = scraper.interleave_by_category(items)[:limit]
            return [
                format_compact_list(
                    f"🆕 Latest {len(ordered)} Recent Opportunities",
                    ordered,
                    "No recent matching opportunities cached yet. Check back soon!",
                )
            ]

        if cmd == "/jobs":
            target_cats = {"jobs", "web3_jobs"}
            label_name = "jobs"
            base_heading = "💼 Latest Remote Jobs"
        elif cmd == "/web3":
            target_cats = {"web3_jobs"}
            label_name = "Web3 remote jobs"
            base_heading = "⛓️ Latest Web3 Remote Jobs"
        else:
            target_cats = {"scholarships"}
            label_name = "scholarships"
            base_heading = "🎓 Latest Scholarships"

        filtered = [i for i in items if i.category in target_cats]
        if arg:
            search_terms = [t.strip() for t in arg.split(",") if t.strip()]
            filtered = [
                i
                for i in filtered
                if scraper.match_keywords(f"{i.title} {i.summary}", search_terms, [])
            ]

        heading = f"{base_heading}{f' ({arg})' if arg else ''}"
        return [
            format_compact_list(
                heading,
                filtered[:5],
                f"No recent {label_name} matched{' for ' + arg if arg else ''} right now.",
            )
        ]

    return [
        "❓ Unknown command. Send /help to see all available commands."
    ]


def process_updates_once(
    bot_token: str,
    config_path: Path,
    latest_path: Path,
    state_path: Path,
    subscribers_path: Path,
    poll_timeout: int = 0,
) -> int:
    """Fetch and answer all pending Telegram updates once."""
    state = load_state(state_path)
    last_id = int(state.get("last_update_id", 0))
    updates = get_updates(bot_token, offset=last_id + 1, timeout=poll_timeout)

    if not updates:
        return 0

    config = scraper.load_config(config_path)
    handled = 0
    max_update_id = last_id

    for update in updates:
        update_id = int(update.get("update_id", 0))
        if update_id > max_update_id:
            max_update_id = update_id

        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", "")).strip()

        if not chat_id or not text.startswith("/"):
            continue

        replies = handle_command(chat_id, text, config, latest_path, subscribers_path)
        for reply in replies:
            try:
                scraper.send_telegram_message(bot_token, chat_id, reply)
                handled += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed sending reply to %s: %s", chat_id, exc)

    state["last_update_id"] = max_update_id
    save_state(state_path, state)
    return handled


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Handle Telegram user commands for Job & Scholarship Alert Bot."
    )
    parser.add_argument("--config", type=Path, default=scraper.DEFAULT_CONFIG_PATH)
    parser.add_argument("--latest", type=Path, default=scraper.DEFAULT_LATEST_PATH)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--subscribers", type=Path, default=scraper.DEFAULT_SUBSCRIBERS_PATH)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process pending updates once and exit (recommended for GitHub Actions).",
    )
    args = parser.parse_args()

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        logger.error("Missing TELEGRAM_BOT_TOKEN environment variable.")
        sys.exit(1)

    register_bot_commands(bot_token)

    if args.once:
        count = process_updates_once(
            bot_token=bot_token,
            config_path=args.config,
            latest_path=args.latest,
            state_path=args.state,
            subscribers_path=args.subscribers,
            poll_timeout=0,
        )
        logger.info("Processed %d command replies (--once).", count)
        return

    logger.info("Starting continuous Telegram command polling (Ctrl+C to stop)...")
    while True:
        try:
            process_updates_once(
                bot_token=bot_token,
                config_path=args.config,
                latest_path=args.latest,
                state_path=args.state,
                subscribers_path=args.subscribers,
                poll_timeout=30,
            )
        except KeyboardInterrupt:
            logger.info("Stopping bot command polling.")
            break
        except Exception as exc:  # noqa: BLE001
            logger.error("Polling error: %s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
