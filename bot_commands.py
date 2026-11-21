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
    {"command": "search", "description": "Search all categories (e.g. /search python)"},
    {"command": "worldwide", "description": "Filter 🌍 Worldwide opportunities"},
    {"command": "visa", "description": "Filter 🛂 Visa-sponsored opportunities"},
    {"command": "digest", "description": "Today's top opportunities summary"},
    {"command": "stats", "description": "Bot & opportunity counts"},
    {"command": "subscribe", "description": "Get cycle reminder DMs when new posts drop"},
    {"command": "unsubscribe", "description": "Pause cycle reminder DMs"},
    {"command": "keywords", "description": "View tracked keywords"},
    {"command": "sources", "description": "View monitored feeds & age limit"},
    {"command": "help", "description": "Show command guide"},
]

PAGE_SIZE = 5


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
    scraper.save_subscribers(path, subscribers)


def register_bot_commands(bot_token: str) -> None:
    """Register the slash command menu in Telegram."""
    url = f"https://api.telegram.org/bot{bot_token}/setMyCommands"
    try:
        resp = requests.post(url, json={"commands": BOT_COMMANDS_MENU}, timeout=15)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not register Telegram command menu: %s", exc)


def sync_telegram_profile(bot_token: str, config: dict[str, Any] | None = None) -> None:
    """Sync commands, search-optimized description, and short bio to Telegram Bot API."""
    register_bot_commands(bot_token)
    site_url = scraper.get_public_site_url(config)
    channel_id = str((config or {}).get("settings", {}).get("channel_id", "@latestjobsandscholarship")).strip()

    description = (
        "🚀 Real-time radar for Remote Tech Jobs, Web3 Remote Roles, Visa-Sponsored Openings "
        "& Fully Funded Scholarships!\n\n"
        "• Updated every 6 hours from 9 curated feeds\n"
        "• Zero duplicates · Fresh listings only\n"
        "• Smart tags: 🌍 Worldwide · 🛂 Visa Sponsored · 💰 Fully Funded · 🟢 Entry/Intern\n\n"
        f"📢 Channel: {channel_id}\n"
        f"🌐 Live Web Board: {site_url}"
    )
    short_description = (
        f"Remote Tech Jobs, Web3 Roles, Visa-Sponsored & Funded Scholarships | "
        f"{channel_id} | {site_url}"
    )[:120]

    for endpoint, payload in [
        ("setMyDescription", {"description": description[:512]}),
        ("setMyShortDescription", {"short_description": short_description}),
    ]:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{bot_token}/{endpoint}",
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not sync Telegram %s: %s", endpoint, exc)


def get_updates(bot_token: str, offset: int, timeout: int = 0) -> list[dict[str, Any]]:
    """Fetch pending updates from Telegram Bot API."""
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params: dict[str, Any] = {
        "offset": offset,
        "timeout": timeout,
        "allowed_updates": json.dumps(["message", "callback_query", "inline_query"]),
    }
    resp = requests.get(url, params=params, timeout=timeout + 15)
    if resp.status_code == 409:
        logger.info("Telegram webhook is active; skipping getUpdates polling.")
        return []
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("ok"):
        return []
    return payload.get("result", [])


def set_webhook(bot_token: str, webhook_url: str, secret_token: str = "") -> dict[str, Any]:
    """Configure Telegram webhook URL and sync bot search profile + commands."""
    sync_telegram_profile(bot_token)
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    payload: dict[str, Any] = {
        "url": webhook_url,
        "allowed_updates": ["message", "callback_query", "inline_query"],
    }
    if secret_token:
        payload["secret_token"] = secret_token
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


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


_LIVE_CACHE: dict[str, Any] = {"ts": 0.0, "items": []}
LIVE_CACHE_TTL_SECONDS = 300


def get_recent_opportunities(
    config: dict[str, Any],
    latest_path: Path,
    required_categories: set[str] | None = None,
) -> list[scraper.Opportunity]:
    """Read recent cached opportunities, refreshing live if empty or missing a category."""
    cached = scraper.load_latest_items(latest_path)
    if cached:
        if not required_categories or any(i.category in required_categories for i in cached):
            return cached

    now = time.time()
    if _LIVE_CACHE["items"] and (now - float(_LIVE_CACHE["ts"])) < LIVE_CACHE_TTL_SECONDS:
        live = list(_LIVE_CACHE["items"])
    else:
        live = scraper.collect_opportunities(config)
        _LIVE_CACHE["ts"] = now
        _LIVE_CACHE["items"] = live

    limit = int(config.get("settings", {}).get("latest_cache_limit", 40))
    try:
        return scraper.save_latest_items(latest_path, live, config, limit=limit)
    except OSError:
        return scraper.interleave_by_category(live)[:limit]


def format_compact_list(
    heading: str,
    items: list[scraper.Opportunity],
    empty_hint: str,
    start_index: int = 1,
) -> str:
    """Format a compact multi-item Telegram HTML message."""
    if not items:
        return f"<b>{html.escape(heading)}</b>\n\n{html.escape(empty_hint)}"

    lines = [f"<b>{html.escape(heading)}</b>"]
    for idx, item in enumerate(items, start=start_index):
        title = html.escape(item.title)
        link = html.escape(item.link, quote=True)
        source = html.escape(item.source_name)
        tags = html.escape(", ".join(item.matched_keywords))
        date_line = f" · 🗓 {html.escape(item.published)}" if item.published else ""
        meta_parts: list[str] = []
        if item.badges:
            meta_parts.append(html.escape(" · ".join(item.badges)))
        if item.deadline:
            meta_parts.append(f"⏳ {html.escape(item.deadline)}")
        meta_line = f"\n   {' · '.join(meta_parts)}" if meta_parts else ""
        lines.append(
            f"{idx}. <b><a href=\"{link}\">{title}</a></b>\n"
            f"   <i>{source}</i>{date_line}{meta_line}\n"
            f"   🏷 <code>{tags}</code>"
        )
    return "\n\n".join(lines)


def encode_callback_data(cmd_name: str, page: int, query: str = "") -> str:
    """Encode pagination state within Telegram's 64-byte callback_data limit."""
    prefix = f"pg:{cmd_name}:{page}:"
    budget = 64 - len(prefix.encode("utf-8"))
    q_bytes = query.strip().encode("utf-8")[: max(0, budget)]
    safe_query = q_bytes.decode("utf-8", errors="ignore")
    return f"{prefix}{safe_query}"


def build_list_markup(
    cmd_name: str,
    page: int,
    total_items: int,
    page_size: int = PAGE_SIZE,
    query: str = "",
    channel_url: str = "",
) -> dict[str, Any] | None:
    """Build inline Prev/Next pagination + Join Channel buttons."""
    rows: list[list[dict[str, str]]] = []
    nav_row: list[dict[str, str]] = []
    if page > 0:
        nav_row.append({
            "text": "◀ Prev 5",
            "callback_data": encode_callback_data(cmd_name, page - 1, query),
        })
    if (page + 1) * page_size < total_items:
        nav_row.append({
            "text": "Next 5 ▶",
            "callback_data": encode_callback_data(cmd_name, page + 1, query),
        })
    if nav_row:
        rows.append(nav_row)
    if channel_url:
        rows.append([{"text": "Join Channel 📢", "url": channel_url}])
    return {"inline_keyboard": rows} if rows else None


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


def format_stats_message(
    config: dict[str, Any],
    items: list[scraper.Opportunity],
    seen_path: Path = scraper.DEFAULT_SEEN_PATH,
) -> str:
    """Format /stats summary showing counts by category, badges, and tracked history."""
    cat_counts: dict[str, int] = {}
    badge_counts: dict[str, int] = {}
    for item in items:
        cat_counts[item.category] = cat_counts.get(item.category, 0) + 1
        for b in item.badges:
            badge_counts[b] = badge_counts.get(b, 0) + 1

    seen_map, _ = scraper.load_seen_items(seen_path)
    total_tracked = sum(1 for k in seen_map if not k.startswith("t:"))
    enabled_sources = sum(
        1
        for cat_cfg in config.get("categories", {}).values()
        for src in cat_cfg.get("sources", [])
        if src.get("enabled", True)
    )

    lines = [
        "<b>📊 Job &amp; Scholarship Alert Bot Stats</b>",
        f"• <b>Recent cached opportunities:</b> {len(items)}\n"
        f"• <b>Active monitored feeds:</b> {enabled_sources}\n"
        f"• <b>Total alerts tracked:</b> {total_tracked}",
    ]

    cat_lines: list[str] = []
    for cat_key, cat_cfg in config.get("categories", {}).items():
        label = html.escape(cat_cfg.get("label", cat_key.title()))
        cat_lines.append(f"• {label}: <b>{cat_counts.get(cat_key, 0)}</b>")
    if cat_lines:
        lines.append("<b>By Category:</b>\n" + "\n".join(cat_lines))

    if badge_counts:
        badge_lines = [
            f"• {html.escape(badge)}: <b>{count}</b>"
            for badge, count in sorted(badge_counts.items())
        ]
        lines.append("<b>Highlights:</b>\n" + "\n".join(badge_lines))

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


def _filter_opportunities_for_command(
    cmd: str,
    arg: str,
    config: dict[str, Any],
    latest_path: Path,
) -> tuple[str, list[scraper.Opportunity], str]:
    """Return (heading, matching_items, empty_hint) for list/search commands."""
    if cmd == "/latest":
        items = scraper.interleave_by_category(get_recent_opportunities(config, latest_path))
        return "🆕 Latest Recent Opportunities", items, "No recent opportunities cached yet. Check back soon!"

    if cmd == "/search":
        if not arg:
            return (
                "🔎 Search All Opportunities",
                [],
                "Provide a search keyword, e.g. /search python or /search africa.",
            )
        items = scraper.interleave_by_category(get_recent_opportunities(config, latest_path))
        search_terms = [t.strip() for t in arg.replace(",", " ").split() if t.strip()]
        filtered = [
            i
            for i in items
            if scraper.match_keywords(
                f"{i.title} {i.summary} {' '.join(i.matched_keywords)} {' '.join(i.badges)}",
                search_terms,
                [],
            )
        ]
        return (
            f"🔎 Search Results ({arg})",
            filtered,
            f"No recent opportunities matched '{arg}'.",
        )

    if cmd in {"/worldwide", "/visa"}:
        items = scraper.interleave_by_category(get_recent_opportunities(config, latest_path))
        target_badge = "🌍 Worldwide" if cmd == "/worldwide" else "🛂 Visa Sponsored"
        filtered = [
            i
            for i in items
            if target_badge in i.badges
            or (cmd == "/worldwide" and "worldwide" in f"{i.title} {i.summary}".lower())
            or (cmd == "/visa" and "visa" in f"{i.title} {i.summary}".lower())
        ]
        if arg:
            search_terms = [t.strip() for t in arg.replace(",", " ").split() if t.strip()]
            filtered = [
                i
                for i in filtered
                if scraper.match_keywords(f"{i.title} {i.summary}", search_terms, [])
            ]
        heading = (
            f"🌍 Worldwide Remote Opportunities{f' ({arg})' if arg else ''}"
            if cmd == "/worldwide"
            else f"🛂 Visa-Sponsored Opportunities{f' ({arg})' if arg else ''}"
        )
        return heading, filtered, f"No recent {target_badge} opportunities matched right now."

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

    items = get_recent_opportunities(config, latest_path, required_categories=target_cats)
    filtered = [i for i in items if i.category in target_cats]
    if arg:
        search_terms = [t.strip() for t in arg.split(",") if t.strip()]
        filtered = [
            i
            for i in filtered
            if scraper.match_keywords(f"{i.title} {i.summary}", search_terms, [])
        ]

    heading = f"{base_heading}{f' ({arg})' if arg else ''}"
    return (
        heading,
        filtered,
        f"No recent {label_name} matched{' for ' + arg if arg else ''} right now.",
    )


def build_command_responses(
    chat_id: str,
    text: str,
    config: dict[str, Any],
    latest_path: Path,
    subscribers_path: Path,
    page: int = 0,
) -> list[tuple[str, dict[str, Any] | None]]:
    """Parse a command and return [(html_text, optional_reply_markup), ...]."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return []

    parts = stripped.split(maxsplit=1)
    raw_cmd = parts[0].lower()
    cmd = raw_cmd.split("@", 1)[0]
    arg = parts[1].strip() if len(parts) > 1 else ""

    channel_link = get_channel_display(config)
    channel_markup = (
        {"inline_keyboard": [[{"text": "Join Channel 📢", "url": channel_link}]]}
        if channel_link
        else None
    )

    if cmd in {"/start", "/help"}:
        channel_line = (
            f"\n\n📢 <b>Public Alert Channel:</b> {html.escape(channel_link)}"
            if channel_link
            else ""
        )
        msg = (
            "<b>👋 Job & Scholarship Alert Bot</b>\n"
            "Get fresh remote jobs, Web3 roles, fellowships, and funded scholarships."
            f"{channel_line}\n\n"
            "<b>Available Commands:</b>\n"
            "• /latest — Newest jobs, Web3 & scholarships\n"
            "• /jobs [keyword] — Latest remote jobs (e.g. <code>/jobs python</code>)\n"
            "• /web3 [keyword] — Latest Web3 remote jobs (e.g. <code>/web3 rust</code>)\n"
            "• /scholarships [keyword] — Latest scholarships\n"
            "• /search &lt;word&gt; — Search across all categories\n"
            "• /worldwide [word] — 🌍 Work-from-anywhere roles\n"
            "• /visa [word] — 🛂 Visa-sponsored roles\n"
            "• /digest — ☀️ Top opportunities summary\n"
            "• /stats — 📊 Counts by category & highlights\n"
            "• /subscribe — 🔔 Get cycle reminder DMs on new posts\n"
            "• /unsubscribe — 🔕 Pause cycle reminder DMs\n"
            "• /keywords — View tracked keywords\n"
            "• /sources — Monitored feeds & recency window"
        )
        site_url = scraper.get_public_site_url(config)
        start_rows: list[list[dict[str, str]]] = []
        top_row: list[dict[str, str]] = []
        if channel_link:
            top_row.append({"text": "Join Channel 📢", "url": channel_link})
        if site_url:
            top_row.append({"text": "🌐 Live Web Board", "url": site_url})
        if top_row:
            start_rows.append(top_row)
        start_rows.append([
            {"text": "🔔 Get Cycle Reminders", "callback_data": "sub:on"},
            {"text": "🔎 Share in Chat", "switch_inline_query": ""},
        ])
        return [(msg, {"inline_keyboard": start_rows})]

    if cmd == "/digest":
        items = get_recent_opportunities(config, latest_path)
        channel_id = str(config.get("settings", {}).get("channel_id", "")).strip()
        return [(scraper.format_daily_digest(items, channel_tag=channel_id), channel_markup)]

    if cmd == "/stats":
        items = get_recent_opportunities(config, latest_path)
        seen_path = latest_path.parent / "seen_items.json"
        return [(format_stats_message(config, items, seen_path=seen_path), channel_markup)]

    if cmd == "/keywords":
        subscribers = scraper.load_subscribers(subscribers_path)
        return [(format_keywords_message(config, subscribers.get(chat_id)), None)]

    if cmd == "/sources":
        return [(format_sources_message(config), None)]

    if cmd == "/setkeywords":
        keywords = [kw.strip() for kw in arg.split(",") if kw.strip()]
        if not keywords:
            return [(
                "Please provide comma-separated keywords, for example:\n"
                "<code>/setkeywords python, backend, fully funded</code>",
                None,
            )]
        subscribers = scraper.load_subscribers(subscribers_path)
        subscribers[chat_id] = {
            "subscribed": True,
            "keywords": keywords,
        }
        try:
            save_subscribers(subscribers_path, subscribers)
        except Exception:  # noqa: BLE001
            return [(
                "ℹ️ Personal DM subscriptions require <code>SUBSCRIBERS_GIST_ID</code> on Vercel.\n"
                "Use <code>/search &lt;keyword&gt;</code>, <code>/jobs &lt;keyword&gt;</code>, "
                "<code>/web3 &lt;keyword&gt;</code>, or <code>/scholarships &lt;keyword&gt;</code> anytime!",
                channel_markup,
            )]
        return [(
            "✅ <b>Personal keywords saved &amp; DM alerts enabled!</b>\n"
            f"🏷 <code>{html.escape(', '.join(keywords))}</code>\n\n"
            "Send /unsubscribe anytime to pause personal DMs.",
            None,
        )]

    if cmd == "/subscribe":
        subscribers = scraper.load_subscribers(subscribers_path)
        existing = subscribers.get(chat_id, {})
        existing["subscribed"] = True
        existing.setdefault("keywords", [])
        subscribers[chat_id] = existing
        try:
            save_subscribers(subscribers_path, subscribers)
        except Exception:  # noqa: BLE001
            return [(
                "ℹ️ Personal DM reminders require <code>SUBSCRIBERS_GIST_ID</code> on Vercel.\n"
                "Meanwhile, join the public channel — it posts a 🔔 Cycle Update reminder every 6 hours whenever new jobs or scholarships drop!",
                channel_markup,
            )]
        kw_note = (
            f"Filtering cycle reminders by: <code>{html.escape(', '.join(existing['keywords']))}</code>"
            if existing["keywords"]
            else "You'll receive a 🔔 Cycle Reminder DM whenever new posts drop in the channel. Use /setkeywords to narrow down."
        )
        return [(f"✅ <b>Subscribed to cycle reminder DMs!</b>\n{kw_note}", channel_markup)]

    if cmd == "/unsubscribe":
        subscribers = scraper.load_subscribers(subscribers_path)
        if chat_id in subscribers:
            subscribers[chat_id]["subscribed"] = False
            try:
                save_subscribers(subscribers_path, subscribers)
            except Exception:  # noqa: BLE001
                pass
        return [("🔕 <b>Cycle reminder DMs paused.</b> Send /subscribe anytime to resume.", None)]

    if cmd in {"/latest", "/jobs", "/web3", "/scholarships", "/search", "/worldwide", "/visa"}:
        page_size = PAGE_SIZE
        if cmd == "/latest" and arg.isdigit():
            page_size = max(1, min(10, int(arg)))
            query = ""
        else:
            query = arg

        heading, all_items, empty_hint = _filter_opportunities_for_command(
            cmd, query, config, latest_path
        )
        total = len(all_items)
        safe_page = max(0, page)
        if safe_page * page_size >= total and total > 0:
            safe_page = 0

        start = safe_page * page_size
        page_items = all_items[start : start + page_size]
        page_suffix = f" (Page {safe_page + 1})" if total > page_size else ""
        msg = format_compact_list(
            f"{heading}{page_suffix}",
            page_items,
            empty_hint,
            start_index=start + 1,
        )
        cmd_name = cmd.lstrip("/")
        markup = (
            build_list_markup(
                cmd_name=cmd_name,
                page=safe_page,
                total_items=total,
                page_size=page_size,
                query=query,
                channel_url=channel_link,
            )
            if total > 0
            else channel_markup
        )
        return [(msg, markup)]

    return [("❓ Unknown command. Send /help to see all available commands.", None)]


def handle_command(
    chat_id: str,
    text: str,
    config: dict[str, Any],
    latest_path: Path,
    subscribers_path: Path,
) -> list[str]:
    """Parse a user command and return plain HTML reply strings."""
    return [
        reply_text
        for reply_text, _markup in build_command_responses(
            chat_id, text, config, latest_path, subscribers_path
        )
    ]


def _handle_callback_query(
    callback_query: dict[str, Any],
    bot_token: str,
    config: dict[str, Any],
    latest_path: Path,
    subscribers_path: Path,
) -> int:
    """Handle inline pagination and subscription button presses."""
    cq_id = str(callback_query.get("id", "")).strip()
    data = str(callback_query.get("data", "")).strip()
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id", "")).strip()
    message_id = message.get("message_id")

    if not cq_id or not chat_id:
        if cq_id:
            scraper.answer_callback_query(bot_token, cq_id)
        return 0

    if data in {"sub:on", "sub:off"}:
        cmd_text = "/subscribe" if data == "sub:on" else "/unsubscribe"
        responses = build_command_responses(
            chat_id, cmd_text, config, latest_path, subscribers_path
        )
        if responses:
            reply_text, markup = responses[0]
            scraper.send_telegram_message(
                bot_token,
                chat_id,
                reply_text,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        ack_msg = "🔔 Cycle reminders enabled!" if data == "sub:on" else "🔕 Cycle reminders paused."
        scraper.answer_callback_query(bot_token, cq_id, text=ack_msg)
        return 1

    if not data.startswith("pg:") or not message_id:
        scraper.answer_callback_query(bot_token, cq_id)
        return 0

    parts = data.split(":", 3)
    if len(parts) < 3:
        scraper.answer_callback_query(bot_token, cq_id)
        return 0

    cmd_name = parts[1]
    try:
        page = int(parts[2])
    except ValueError:
        page = 0
    query = parts[3] if len(parts) > 3 else ""

    cmd_text = f"/{cmd_name}" + (f" {query}" if query else "")
    responses = build_command_responses(
        chat_id, cmd_text, config, latest_path, subscribers_path, page=page
    )
    if responses:
        reply_text, markup = responses[0]
        scraper.edit_telegram_message(
            bot_token, chat_id, int(message_id), reply_text, reply_markup=markup
        )
    scraper.answer_callback_query(bot_token, cq_id)
    return 1


def build_inline_results(
    query: str,
    config: dict[str, Any],
    latest_path: Path,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Build Telegram InlineQueryResultArticle objects for viral in-chat sharing."""
    items = scraper.interleave_by_category(get_recent_opportunities(config, latest_path))
    q = query.strip()
    if q:
        terms = [t.strip() for t in q.replace(",", " ").split() if t.strip()]
        items = [
            i
            for i in items
            if scraper.match_keywords(
                f"{i.title} {i.summary} {i.source_name} {' '.join(i.matched_keywords)} {' '.join(i.badges)}",
                terms,
                [],
            )
        ]

    channel_link = get_channel_display(config)
    channel_tag = str(config.get("settings", {}).get("channel_id", "")).strip()
    site_url = scraper.get_public_site_url(config)

    results: list[dict[str, Any]] = []
    for item in items[:limit]:
        badges_str = f" · {' '.join(item.badges)}" if item.badges else ""
        desc_parts = [f"{item.category_label} · {item.source_name}"]
        if item.badges:
            desc_parts.append(" ".join(item.badges))
        if item.deadline:
            desc_parts.append(f"⏳ {item.deadline}")

        row1: list[dict[str, str]] = [{"text": "Apply Now 🔗", "url": item.link}]
        if channel_link:
            row1.append({"text": "Join Channel 📢", "url": channel_link})
        row2: list[dict[str, str]] = []
        if site_url:
            row2.append({"text": "🌐 Live Web Board", "url": site_url})
        keyboard = [row1] + ([row2] if row2 else [])

        results.append({
            "type": "article",
            "id": item.item_id[:60],
            "title": f"{item.title}{badges_str}"[:120],
            "description": " | ".join(desc_parts)[:180],
            "url": item.link,
            "input_message_content": {
                "message_text": scraper.format_telegram_message(item, channel_tag=channel_tag),
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            "reply_markup": {"inline_keyboard": keyboard},
        })
    return results


def _handle_inline_query(
    inline_query: dict[str, Any],
    bot_token: str,
    config: dict[str, Any],
    latest_path: Path,
) -> int:
    """Answer an inline query (@bot <search>) so users can share jobs/scholarships in any chat."""
    iq_id = str(inline_query.get("id", "")).strip()
    query = str(inline_query.get("query", "")).strip()
    if not iq_id:
        return 0
    results = build_inline_results(query, config, latest_path)
    payload = {
        "inline_query_id": iq_id,
        "results": results,
        "cache_time": 120,
        "is_personal": False,
    }
    resp = requests.post(
        f"https://api.telegram.org/bot{bot_token}/answerInlineQuery",
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    return 1


def process_webhook_update(
    update: dict[str, Any],
    bot_token: str,
    config_path: Path,
    latest_path: Path,
    subscribers_path: Path,
) -> int:
    """Process a single Telegram webhook update dict and send replies immediately."""
    if "inline_query" in update and isinstance(update["inline_query"], dict):
        config = scraper.load_config(config_path)
        return _handle_inline_query(update["inline_query"], bot_token, config, latest_path)

    if "callback_query" in update and isinstance(update["callback_query"], dict):
        config = scraper.load_config(config_path)
        return _handle_callback_query(
            update["callback_query"], bot_token, config, latest_path, subscribers_path
        )

    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id", "")).strip()

    if not chat_id or not text.startswith("/"):
        return 0

    config = scraper.load_config(config_path)
    responses = build_command_responses(chat_id, text, config, latest_path, subscribers_path)
    handled = 0
    for reply_text, markup in responses:
        scraper.send_telegram_message(
            bot_token,
            chat_id,
            reply_text,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
        handled += 1
    return handled


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

        if "inline_query" in update and isinstance(update["inline_query"], dict):
            try:
                handled += _handle_inline_query(
                    update["inline_query"], bot_token, config, latest_path
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed handling inline query: %s", exc)
            continue

        if "callback_query" in update and isinstance(update["callback_query"], dict):
            try:
                handled += _handle_callback_query(
                    update["callback_query"], bot_token, config, latest_path, subscribers_path
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed handling callback query: %s", exc)
            continue

        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", "")).strip()

        if not chat_id or not text.startswith("/"):
            continue

        responses = build_command_responses(chat_id, text, config, latest_path, subscribers_path)
        for reply_text, markup in responses:
            try:
                scraper.send_telegram_message(
                    bot_token,
                    chat_id,
                    reply_text,
                    reply_markup=markup,
                    disable_web_page_preview=True,
                )
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
    parser.add_argument(
        "--set-webhook",
        type=str,
        default="",
        help="Register a Telegram webhook URL (e.g. https://your-app.vercel.app/api/webhook) and exit.",
    )
    parser.add_argument(
        "--sync-profile",
        action="store_true",
        help="Sync search-optimized bot description, short bio, and commands to Telegram and exit.",
    )
    args = parser.parse_args()

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        logger.error("Missing TELEGRAM_BOT_TOKEN environment variable.")
        sys.exit(1)

    config = scraper.load_config(args.config) if args.config.exists() else {}

    if args.sync_profile:
        sync_telegram_profile(bot_token, config)
        logger.info("Telegram bot profile and commands synced.")
        return

    if args.set_webhook:
        secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
        result = set_webhook(bot_token, args.set_webhook.strip(), secret_token=secret)
        logger.info("Webhook set: %s", result)
        return

    sync_telegram_profile(bot_token, config)

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
