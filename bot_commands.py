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
import re
import sys
import time
from datetime import datetime, timezone
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
    {"command": "share", "description": "Invite 3 friends for unlimited /pitch"},
    {"command": "expiring", "description": "Deadlines closing soon (Free)"},
    {"command": "pitch", "description": "One-tap application pitch & checklist"},
    {"command": "subscribe", "description": "Get cycle reminder DMs when new posts drop"},
    {"command": "unsubscribe", "description": "Pause cycle reminder DMs"},
    {"command": "keywords", "description": "View tracked keywords"},
    {"command": "sources", "description": "View monitored feeds & age limit"},
    {"command": "help", "description": "Show command guide"},
]

PAGE_SIZE = 5
REFERRAL_GOAL = 3


def get_referral_goal(config: dict[str, Any] | None = None) -> int:
    if config:
        try:
            val = int(config.get("settings", {}).get("referral_goal", REFERRAL_GOAL))
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
    return REFERRAL_GOAL


def get_referral_progress(
    subscribers: dict[str, Any],
    chat_id: str,
    config: dict[str, Any] | None = None,
) -> tuple[int, int, bool]:
    """Return (referrals_count, goal, vip_unlocked) for a user."""
    goal = get_referral_goal(config)
    prefs = subscribers.get(chat_id) or {}
    referred_list = prefs.get("referred_users")
    if isinstance(referred_list, list):
        count = max(int(prefs.get("referrals", 0) or 0), len(referred_list))
    else:
        count = int(prefs.get("referrals", 0) or 0)
    unlocked = bool(prefs.get("vip_unlocked")) or count >= goal
    return count, goal, unlocked


def build_referral_progress_bar(count: int, goal: int = REFERRAL_GOAL) -> str:
    filled = min(max(0, count), goal)
    empty = max(0, goal - filled)
    return f"[{'█' * filled}{'░' * empty}] {min(count, goal)}/{goal}"


def build_referral_link(
    chat_id: str,
    bot_url: str = "",
    site_url: str = "",
    channel_url: str = "",
) -> str:
    if bot_url:
        return f"{bot_url}?start=ref_{chat_id}"
    return site_url or channel_url


def register_referral(
    subscribers: dict[str, Any],
    new_chat_id: str,
    referrer_id: str,
    goal: int = REFERRAL_GOAL,
) -> tuple[bool, bool, int]:
    """Record a unique referral if valid. Returns (counted, just_unlocked, new_count)."""
    clean_new = str(new_chat_id).strip()
    clean_ref = str(referrer_id).strip()
    if not clean_new or not clean_ref or clean_new == clean_ref:
        return False, False, 0
    if not re.fullmatch(r"-?\d+", clean_ref):
        return False, False, 0

    new_prefs = subscribers.get(clean_new)
    if not isinstance(new_prefs, dict):
        new_prefs = {"subscribed": False, "keywords": []}
    if new_prefs.get("referred_by"):
        return False, False, 0

    ref_prefs = subscribers.get(clean_ref)
    if not isinstance(ref_prefs, dict):
        ref_prefs = {"subscribed": False, "keywords": []}

    referred_users = list(ref_prefs.get("referred_users") or [])
    if clean_new in referred_users:
        return False, False, len(referred_users)

    was_unlocked = bool(ref_prefs.get("vip_unlocked")) or len(referred_users) >= goal
    referred_users.append(clean_new)
    new_count = len(referred_users)
    just_unlocked = (not was_unlocked) and new_count >= goal

    ref_prefs["referred_users"] = referred_users
    ref_prefs["referrals"] = new_count
    if new_count >= goal:
        ref_prefs["vip_unlocked"] = True

    new_prefs["referred_by"] = clean_ref
    subscribers[clean_new] = new_prefs
    subscribers[clean_ref] = ref_prefs
    return True, just_unlocked, new_count


def format_vip_lock_message(
    feature_name: str,
    chat_id: str,
    subscribers: dict[str, Any],
    config: dict[str, Any],
    bot_url: str = "",
    site_url: str = "",
    channel_link: str = "",
) -> tuple[str, dict[str, Any] | None]:
    """Build a friendly 3-friend referral unlock card + one-tap share button."""
    count, goal, _ = get_referral_progress(subscribers, chat_id, config)
    remaining = max(0, goal - count)
    bar = build_referral_progress_bar(count, goal)
    ref_link = build_referral_link(chat_id, bot_url=bot_url, site_url=site_url, channel_url=channel_link)

    lines = [
        f"🔒 <b>{html.escape(feature_name)} — Unlock Unlimited Access ({goal} Friends)</b>",
        f"📊 <b>Your Progress:</b> <code>{html.escape(bar)}</code> ({remaining} more needed)",
        "Everything else (/latest, /jobs, /web3, /scholarships, /expiring, /setkeywords) is <b>100% free</b>!\n"
        f"Invite <b>{goal} friends</b> to unlock <b>unlimited One-Tap Application Pitches &amp; ATS Checklists</b> (<code>/pitch</code> &amp; <b>📝 Pitch #1–#5</b>).",
    ]
    if ref_link:
        lines.append(f"🔗 <b>Your Personal Invite Link:</b>\n<code>{html.escape(ref_link)}</code>")

    rows: list[list[dict[str, str]]] = []
    if ref_link:
        rows.append([{
            "text": f"🎁 Invite Friends ({count}/{goal})",
            "url": scraper.build_telegram_share_url(
                ref_link,
                "🚀 Join this free 24/7 Bot for Remote Tech Jobs, Web3 Roles & Fully Funded Scholarships!",
            ),
        }])
    if channel_link:
        rows.append([{"text": "Join Channel 📢", "url": channel_link}])
    return "\n\n".join(lines), ({"inline_keyboard": rows} if rows else None)


def check_and_consume_pitch_access(
    subscribers: dict[str, Any],
    subscribers_path: Path,
    chat_id: str,
    config: dict[str, Any],
) -> tuple[bool, bool]:
    """Return (allowed, used_free_trial). Grants 1 free pitch trial before 3-friend unlock."""
    _, _, unlocked = get_referral_progress(subscribers, chat_id, config)
    if unlocked:
        return True, False
    prefs = subscribers.get(chat_id)
    if not isinstance(prefs, dict):
        prefs = {"subscribed": False, "keywords": []}
    if not prefs.get("free_pitch_used"):
        prefs["free_pitch_used"] = True
        subscribers[chat_id] = prefs
        try:
            save_subscribers(subscribers_path, subscribers)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not persist free_pitch_used: %s", exc)
        return True, True
    return False, False


def _deadline_sort_key(item: scraper.Opportunity) -> tuple[int, float, float]:
    """Sort items with explicit near-term deadlines first, then newest published."""
    dl = (item.deadline or "").strip()
    pub_ts = -(item.published_dt.timestamp() if item.published_dt else 0.0)
    if dl:
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(dl, fmt).replace(tzinfo=timezone.utc)
                return (0, dt.timestamp(), pub_ts)
            except ValueError:
                continue
        return (1, 0.0, pub_ts)
    return (2, 0.0, pub_ts)


def build_application_pitch(item: scraper.Opportunity) -> str:
    """Generate a tailored copy-paste outreach/SOP pitch + ATS checklist for an opportunity."""
    title = html.escape(item.title)
    source = html.escape(item.source_name)
    link = html.escape(item.link, quote=True)
    kws = item.matched_keywords or ["relevant experience"]
    kw_text = ", ".join(kws[:5])
    safe_kws = html.escape(kw_text)
    badges_text = " · ".join(item.badges) if item.badges else "Recent Opportunity"
    deadline_line = f"\n⏳ <b>Deadline:</b> {html.escape(item.deadline)}" if item.deadline else ""

    if item.category == "scholarships":
        pitch_body = (
            f"Dear {source} Selection Committee,\n\n"
            f"I am writing to express my strong interest in the {item.title}. "
            f"With a background aligned with {kw_text}, my academic and community work focuses on [Your Field / Research Focus], "
            f"including [Key Project, Publication, or Measurable Impact].\n\n"
            f"Receiving this opportunity would enable me to [Specific Goal / Contribution], and I have prepared my academic transcripts, "
            f"CV, and references for your review.\n\n"
            f"Best regards,\n[Your Full Name] | [LinkedIn / Portfolio Link]"
        )
        checklist = (
            "• ✅ Tailor your Statement of Purpose around: <code>" + safe_kws + "</code>\n"
            "• ✅ Prepare official transcripts, updated CV &amp; 2 referee contacts\n"
            "• ✅ Confirm eligibility &amp; deadline before submitting"
        )
        header = "🎓 <b>One-Tap Scholarship Pitch &amp; Checklist</b>"
    else:
        pitch_body = (
            f"Subject: Application for {item.title} — [Your Name]\n\n"
            f"Hi Hiring Team at {source},\n\n"
            f"I saw your opening for {item.title} and wanted to reach out directly. "
            f"I bring [X] years of hands-on experience with {kw_text}, most recently [1-line achievement with metric or shipped project].\n\n"
            f"Portfolio / GitHub: [Your Link]\n"
            f"Would love to connect if my background fits what you're looking for.\n\n"
            f"Best,\n[Your Name]"
        )
        checklist = (
            "• ✅ Mirror these ATS keywords in your CV summary: <code>" + safe_kws + "</code>\n"
            "• ✅ Attach 1–2 live links (GitHub, portfolio, or shipped product)\n"
            "• ✅ Send the short DM above to the hiring manager on LinkedIn/X after applying"
        )
        header = "📝 <b>One-Tap Job Pitch &amp; ATS Checklist</b>"

    return (
        f"{header}\n\n"
        f"<b><a href=\"{link}\">{title}</a></b>\n"
        f"<i>{source}</i> · {html.escape(badges_text)}{deadline_line}\n\n"
        f"<b>📋 Copy &amp; Customize Pitch:</b>\n"
        f"<pre>{html.escape(pitch_body)}</pre>\n\n"
        f"<b>🎯 Prep Checklist:</b>\n{checklist}"
    )


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
    lines.append(
        "💡 <i>Tap <b>📝 Pitch #1–#5</b> below to generate a tailored application email &amp; ATS checklist.</i>"
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
    bot_url: str = "",
    site_url: str = "",
    page_items: list[scraper.Opportunity] | None = None,
    start_index: int = 1,
    ref_link: str = "",
) -> dict[str, Any] | None:
    """Build inline Prev/Next pagination + Pitch #1..5 + Join Channel + Share buttons."""
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

    if page_items:
        pitch_buttons = [
            {
                "text": f"📝 Pitch #{idx}",
                "callback_data": f"pitch:{item.item_id[:56]}",
            }
            for idx, item in enumerate(page_items[:5], start=start_index)
        ]
        if pitch_buttons:
            rows.append(pitch_buttons[:3])
        if len(pitch_buttons) > 3:
            rows.append(pitch_buttons[3:])

    action_row: list[dict[str, str]] = []
    if channel_url:
        action_row.append({"text": "Join Channel 📢", "url": channel_url})
    share_target = ref_link or bot_url or site_url or channel_url
    if share_target:
        action_row.append({
            "text": "🎁 Share & Unlock Pitch",
            "url": scraper.build_telegram_share_url(
                share_target,
                "🚀 Free 24/7 bot for Remote Tech Jobs, Web3 Roles & Fully Funded Scholarships!",
            ),
        })
    if action_row:
        rows.append(action_row)
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

    if cmd == "/expiring":
        items = get_recent_opportunities(config, latest_path)
        expiring = [
            i
            for i in items
            if i.deadline
            or any(
                kw in f"{i.title} {i.summary}".lower()
                for kw in ("deadline", "apply by", "closing soon", "closes ", "expires")
            )
        ]
        if arg:
            search_terms = [t.strip() for t in arg.replace(",", " ").split() if t.strip()]
            expiring = [
                i
                for i in expiring
                if scraper.match_keywords(
                    f"{i.title} {i.summary} {' '.join(i.matched_keywords)}",
                    search_terms,
                    [],
                )
            ]
        expiring.sort(key=_deadline_sort_key)
        return (
            f"⏳ Closing-Soon Deadlines{f' ({arg})' if arg else ''}",
            expiring,
            "No extracted deadlines matched right now. Check /latest or /scholarships.",
        )

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
    bot_token: str = "",
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
    site_url = scraper.get_public_site_url(config)
    bot_url = scraper.get_bot_url(bot_token, config)
    channel_markup = (
        {"inline_keyboard": [[{"text": "Join Channel 📢", "url": channel_link}]]}
        if channel_link
        else None
    )

    if cmd in {"/start", "/help"}:
        if cmd == "/start" and arg.lower() == "latest":
            return build_command_responses(
                chat_id, "/latest", config, latest_path, subscribers_path, page=page, bot_token=bot_token
            )

        referral_note = ""
        if cmd == "/start" and arg.lower().startswith("ref_"):
            referrer_id = arg[4:].strip()
            subscribers = scraper.load_subscribers(subscribers_path)
            goal = get_referral_goal(config)
            counted, just_unlocked, new_count = register_referral(
                subscribers, chat_id, referrer_id, goal=goal
            )
            if counted:
                try:
                    save_subscribers(subscribers_path, subscribers)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not persist referral update: %s", exc)
                referral_note = "\n🎁 <i>Invited by a friend — welcome aboard!</i>"
                if bot_token:
                    try:
                        if just_unlocked:
                            notify_text = (
                                f"🎉 <b>Unlimited Pitch Unlocked! ({new_count}/{goal} Friends Joined)</b>\n\n"
                                "You now have unlimited access to:\n"
                                "• 📝 <b>/pitch</b> &amp; <b>📝 Pitch #1–#5</b> buttons — tailored application emails &amp; ATS checklists!"
                            )
                        else:
                            left = max(0, goal - new_count)
                            notify_text = (
                                f"🎁 <b>+1 Friend Joined via Your Link!</b>\n"
                                f"📊 Progress: <code>{html.escape(build_referral_progress_bar(new_count, goal))}</code>\n"
                                f"Invite <b>{left}</b> more friend(s) with /share to unlock unlimited /pitch!"
                            )
                        scraper.send_telegram_message(
                            bot_token,
                            referrer_id,
                            notify_text,
                            disable_web_page_preview=True,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed notifying referrer %s: %s", referrer_id, exc)

        channel_line = (
            f"\n\n📢 <b>Public Alert Channel:</b> {html.escape(channel_link)}"
            if channel_link
            else ""
        )
        msg = (
            "<b>👋 Job & Scholarship Alert Bot</b>\n"
            "Get fresh remote jobs, Web3 roles, fellowships, and funded scholarships."
            f"{referral_note}{channel_line}\n\n"
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
            "• /share — 🎁 Invite 3 friends for unlimited /pitch\n"
            "• /expiring — ⏳ Closing-soon deadlines\n"
            "• /pitch [word] — 📝 One-tap application pitch &amp; checklist\n"
            "• /setkeywords — 🎯 Custom keyword DM alerts\n"
            "• /subscribe — 🔔 Get cycle reminder DMs on new posts\n"
            "• /unsubscribe — 🔕 Pause cycle reminder DMs\n"
            "• /keywords — View tracked keywords\n"
            "• /sources — Monitored feeds & recency window"
        )
        start_rows: list[list[dict[str, str]]] = []
        top_row: list[dict[str, str]] = []
        if channel_link:
            top_row.append({"text": "Join Channel 📢", "url": channel_link})
        if site_url:
            top_row.append({"text": "🌐 Live Web Board", "url": site_url})
        if top_row:
            start_rows.append(top_row)
        ref_link = build_referral_link(chat_id, bot_url=bot_url, site_url=site_url, channel_url=channel_link)
        row2: list[dict[str, str]] = [{"text": "🔔 Get Cycle Reminders", "callback_data": "sub:on"}]
        if ref_link:
            row2.append({
                "text": "🎁 Invite 3 Friends",
                "url": scraper.build_telegram_share_url(
                    ref_link,
                    "🚀 Check out this free 24/7 Bot for Remote Tech Jobs, Web3 Roles & Fully Funded Scholarships!",
                ),
            })
        start_rows.append(row2)
        start_rows.append([{"text": "🔎 Share a Job / Scholarship in Chat", "switch_inline_query": ""}])
        return [(msg, {"inline_keyboard": start_rows})]

    if cmd == "/share":
        subscribers = scraper.load_subscribers(subscribers_path)
        count, goal, unlocked = get_referral_progress(subscribers, chat_id, config)
        bar = build_referral_progress_bar(count, goal)
        ref_link = build_referral_link(chat_id, bot_url=bot_url, site_url=site_url, channel_url=channel_link)
        status_line = (
            "✅ <b>Unlimited One-Tap Pitch: UNLOCKED!</b> (Use /pitch or tap 📝 Pitch #1–#5 anytime)"
            if unlocked
            else f"🔒 <b>Progress:</b> <code>{html.escape(bar)}</code> — invite <b>{max(0, goal - count)}</b> more friend(s) to unlock:\n"
            "• 📝 <b>Unlimited /pitch &amp; 📝 Pitch #1–#5</b> (Tailored application emails, scholarship SOP openers &amp; ATS checklists)\n"
            "<i>All job/scholarship feeds, /expiring &amp; /setkeywords stay 100% free!</i>"
        )
        share_lines = [
            "<b>🎁 Invite 3 Friends &amp; Unlock Unlimited /pitch</b>",
            status_line,
        ]
        if ref_link:
            share_lines.append(f"🔗 <b>Your Personal Invite Link:</b>\n<code>{html.escape(ref_link)}</code>")
        if channel_link:
            share_lines.append(f"📢 <b>Channel:</b> {html.escape(channel_link)}")
        if site_url:
            share_lines.append(f"🌐 <b>Live Web Board:</b> {html.escape(site_url)}")

        share_rows: list[list[dict[str, str]]] = []
        if ref_link:
            share_rows.append([{
                "text": f"📤 Share My Invite Link ({min(count, goal)}/{goal})",
                "url": scraper.build_telegram_share_url(
                    ref_link,
                    "🚀 Free 24/7 Bot for Remote Tech Jobs, Web3 Roles & Fully Funded Scholarships!",
                ),
            }])
        row_b: list[dict[str, str]] = []
        if channel_link:
            row_b.append({
                "text": "📢 Share Channel",
                "url": scraper.build_telegram_share_url(
                    channel_link,
                    "📢 Daily curated Remote Tech Jobs, Web3 Roles & Scholarships — zero spam!",
                ),
            })
        if site_url:
            row_b.append({
                "text": "🌐 Share Web Board",
                "url": scraper.build_telegram_share_url(
                    site_url,
                    "🌐 Live searchable board for Remote Jobs, Web3 & Funded Scholarships!",
                ),
            })
        if row_b:
            share_rows.append(row_b)
        share_rows.append([{"text": "🔎 Share Any Opportunity Inline", "switch_inline_query": ""}])
        return [("\n\n".join(share_lines), {"inline_keyboard": share_rows})]

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
        subscribers = scraper.load_subscribers(subscribers_path)
        keywords = [kw.strip() for kw in arg.split(",") if kw.strip()]
        if not keywords:
            return [(
                "Please provide comma-separated keywords, for example:\n"
                "<code>/setkeywords python, backend, fully funded</code>",
                None,
            )]
        existing = subscribers.get(chat_id, {})
        existing["subscribed"] = True
        existing["keywords"] = keywords
        subscribers[chat_id] = existing
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

    if cmd == "/pitch":
        subscribers = scraper.load_subscribers(subscribers_path)
        allowed, used_trial = check_and_consume_pitch_access(
            subscribers, subscribers_path, chat_id, config
        )
        if not allowed:
            return [
                format_vip_lock_message(
                    "One-Tap Application Pitch (/pitch)",
                    chat_id,
                    subscribers,
                    config,
                    bot_url=bot_url,
                    site_url=site_url,
                    channel_link=channel_link,
                )
            ]
        items = scraper.interleave_by_category(get_recent_opportunities(config, latest_path))
        if arg:
            search_terms = [t.strip() for t in arg.replace(",", " ").split() if t.strip()]
            matched = [
                i
                for i in items
                if scraper.match_keywords(
                    f"{i.title} {i.summary} {i.source_name} {' '.join(i.matched_keywords)}",
                    search_terms,
                    [],
                )
            ]
            target = matched[0] if matched else None
        else:
            target = items[0] if items else None
        if not target:
            return [(
                f"No cached opportunity matched <code>{html.escape(arg)}</code>. Try /latest and tap any <b>📝 Pitch #1–#5</b> button!",
                channel_markup,
            )]
        pitch_markup = scraper.build_item_reply_markup(
            target, channel_url=channel_link, bot_url=bot_url
        )
        pitch_text = build_application_pitch(target)
        if used_trial:
            pitch_text += "\n\n🎁 <i>Free preview used (1/1) — invite 3 friends via /share to unlock unlimited pitches!</i>"
        return [(pitch_text, pitch_markup)]

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

    if cmd in {"/latest", "/jobs", "/web3", "/scholarships", "/search", "/worldwide", "/visa", "/expiring"}:
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
        ref_link = build_referral_link(
            chat_id, bot_url=bot_url, site_url=site_url, channel_url=channel_link
        )
        markup = (
            build_list_markup(
                cmd_name=cmd_name,
                page=safe_page,
                total_items=total,
                page_size=page_size,
                query=query,
                channel_url=channel_link,
                bot_url=bot_url,
                site_url=site_url,
                page_items=page_items,
                start_index=start + 1,
                ref_link=ref_link,
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

    if data.startswith("pitch:"):
        target_id = data.split(":", 1)[1].strip()
        subscribers = scraper.load_subscribers(subscribers_path)
        allowed, used_trial = check_and_consume_pitch_access(
            subscribers, subscribers_path, chat_id, config
        )
        channel_link = get_channel_display(config)
        site_url = scraper.get_public_site_url(config)
        bot_url = scraper.get_bot_url(bot_token, config)
        if not allowed:
            lock_msg, lock_markup = format_vip_lock_message(
                "One-Tap Application Pitch",
                chat_id,
                subscribers,
                config,
                bot_url=bot_url,
                site_url=site_url,
                channel_link=channel_link,
            )
            scraper.send_telegram_message(
                bot_token,
                chat_id,
                lock_msg,
                reply_markup=lock_markup,
                disable_web_page_preview=True,
            )
            scraper.answer_callback_query(bot_token, cq_id, text="🔒 Invite 3 friends for unlimited Pitch!")
            return 1

        items = get_recent_opportunities(config, latest_path)
        target = next((i for i in items if i.item_id.startswith(target_id)), items[0] if items else None)
        if target:
            pitch_markup = scraper.build_item_reply_markup(
                target, channel_url=channel_link, bot_url=bot_url
            )
            pitch_text = build_application_pitch(target)
            if used_trial:
                pitch_text += "\n\n🎁 <i>Free preview used (1/1) — invite 3 friends via /share to unlock unlimited pitches!</i>"
            scraper.send_telegram_message(
                bot_token,
                chat_id,
                pitch_text,
                reply_markup=pitch_markup,
                disable_web_page_preview=True,
            )
        scraper.answer_callback_query(bot_token, cq_id, text="📝 Pitch generated!")
        return 1

    if data in {"sub:on", "sub:off"}:
        cmd_text = "/subscribe" if data == "sub:on" else "/unsubscribe"
        responses = build_command_responses(
            chat_id, cmd_text, config, latest_path, subscribers_path, bot_token=bot_token
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
        chat_id, cmd_text, config, latest_path, subscribers_path, page=page, bot_token=bot_token
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
    responses = build_command_responses(
        chat_id, text, config, latest_path, subscribers_path, bot_token=bot_token
    )
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

        responses = build_command_responses(
            chat_id, text, config, latest_path, subscribers_path, bot_token=bot_token
        )
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
