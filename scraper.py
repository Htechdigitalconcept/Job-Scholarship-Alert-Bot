#!/usr/bin/env python3
"""Job & Scholarship Alert Scraper with Telegram notifications."""

from __future__ import annotations

import argparse
import calendar
import hashlib
import html
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; JobScholarshipAlertBot/1.0; "
    "+https://github.com/actions)"
)

DEFAULT_CONFIG_PATH = Path("config.yaml")
DEFAULT_SEEN_PATH = Path("data/seen_items.json")


@dataclass
class Opportunity:
    item_id: str
    category: str
    category_label: str
    source_name: str
    title: str
    link: str
    summary: str
    matched_keywords: list[str]
    published: str = ""
    published_dt: datetime | None = None


def make_item_id(link: str, title: str) -> str:
    """Create a stable hash ID for deduplication."""
    raw = (link.strip() or title.strip()).lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def clean_html_text(raw_html: str, max_len: int = 240) -> str:
    """Strip HTML tags and collapse whitespace."""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def match_keywords(
    text: str,
    include_keywords: list[str],
    exclude_keywords: list[str],
) -> list[str]:
    """Return matched include keywords if text passes include/exclude rules.

    If include_keywords is empty, all non-excluded items match with ['all'].
    """
    haystack = text.lower()

    for bad in exclude_keywords:
        bad_clean = bad.strip().lower()
        if bad_clean and bad_clean in haystack:
            return []

    if not include_keywords:
        return ["all"]

    matched: list[str] = []
    for kw in include_keywords:
        kw_clean = kw.strip().lower()
        if not kw_clean:
            continue
        # Match whole words/phrases cleanly when alphanumeric, fallback to substring
        if re.fullmatch(r"[a-z0-9\s\-\+]+", kw_clean):
            pattern = r"(?<![a-z0-9])" + re.escape(kw_clean) + r"(?![a-z0-9])"
            if re.search(pattern, haystack):
                matched.append(kw.strip())
        elif kw_clean in haystack:
            matched.append(kw.strip())
    return matched


def fetch_url(url: str, timeout: int = 15) -> str:
    """Fetch URL content with a browser-like User-Agent."""
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def parse_entry_datetime(entry: Any) -> datetime | None:
    """Extract a UTC-aware publish datetime from an RSS/Atom entry."""
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct is not None:
        try:
            ts = calendar.timegm(struct)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            pass

    raw_date = (entry.get("published") or entry.get("updated") or "").strip()
    if raw_date:
        try:
            dt = parsedate_to_datetime(raw_date)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
    return None


def is_recent_post(
    published_dt: datetime | None,
    max_age_days: float | None,
    allow_undated: bool = True,
    now: datetime | None = None,
) -> bool:
    """Return True if the post is within max_age_days (or undated and allowed)."""
    if max_age_days is None or max_age_days <= 0:
        return True
    if published_dt is None:
        return allow_undated
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=max_age_days)
    return published_dt >= cutoff


def parse_rss_source(
    source: dict[str, Any],
    category_key: str,
    category_label: str,
    include_kw: list[str],
    exclude_kw: list[str],
    timeout: int,
    max_age_days: float | None = None,
    allow_undated: bool = True,
    now: datetime | None = None,
) -> list[Opportunity]:
    """Fetch and parse an RSS/Atom feed."""
    raw_xml = fetch_url(source["url"], timeout=timeout)
    feed = feedparser.parse(raw_xml)

    results: list[Opportunity] = []
    for entry in feed.entries:
        title = clean_html_text(entry.get("title", ""), max_len=200)
        link = (entry.get("link") or "").strip()
        summary_raw = entry.get("summary") or entry.get("description") or ""
        summary = clean_html_text(summary_raw, max_len=240)
        published = (entry.get("published") or entry.get("updated") or "").strip()
        published_dt = parse_entry_datetime(entry)

        if not title or not link:
            continue

        if not is_recent_post(published_dt, max_age_days, allow_undated=allow_undated, now=now):
            continue

        combined = f"{title} {summary}"
        matched = match_keywords(combined, include_kw, exclude_kw)
        if not matched:
            continue

        results.append(
            Opportunity(
                item_id=make_item_id(link, title),
                category=category_key,
                category_label=category_label,
                source_name=source["name"],
                title=title,
                link=link,
                summary=summary,
                matched_keywords=matched,
                published=published,
                published_dt=published_dt,
            )
        )
    return results


def parse_html_source(
    source: dict[str, Any],
    category_key: str,
    category_label: str,
    include_kw: list[str],
    exclude_kw: list[str],
    timeout: int,
) -> list[Opportunity]:
    """Fetch and parse an HTML page using CSS selectors from config.yaml."""
    page_html = fetch_url(source["url"], timeout=timeout)
    soup = BeautifulSoup(page_html, "html.parser")

    item_sel = source.get("item_selector", "")
    title_sel = source.get("title_selector", "a")
    link_sel = source.get("link_selector", "a")
    summary_sel = source.get("summary_selector", "")

    if not item_sel:
        logger.warning("HTML source '%s' missing item_selector; skipping.", source["name"])
        return []

    results: list[Opportunity] = []
    for card in soup.select(item_sel):
        title_el = card.select_one(title_sel) if title_sel else card
        link_el = card.select_one(link_sel) if link_sel else title_el
        summary_el = card.select_one(summary_sel) if summary_sel else None

        title = clean_html_text(title_el.get_text(" ", strip=True) if title_el else "", 200)
        href = link_el.get("href", "").strip() if link_el else ""
        link = urljoin(source["url"], href) if href else ""
        summary = clean_html_text(summary_el.get_text(" ", strip=True) if summary_el else "", 240)

        if not title or not link:
            continue

        combined = f"{title} {summary}"
        matched = match_keywords(combined, include_kw, exclude_kw)
        if not matched:
            continue

        results.append(
            Opportunity(
                item_id=make_item_id(link, title),
                category=category_key,
                category_label=category_label,
                source_name=source["name"],
                title=title,
                link=link,
                summary=summary,
                matched_keywords=matched,
            )
        )
    return results


def load_seen_items(path: Path) -> tuple[dict[str, str], bool]:
    """Load seen items map {item_id: iso_timestamp}. Returns (data, existed)."""
    if not path.exists():
        return {}, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}, True
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read %s (%s); starting fresh.", path, exc)
    return {}, True


def prune_seen_items(seen: dict[str, str], retention_days: int) -> dict[str, str]:
    """Drop entries older than retention_days to keep the JSON file small."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    kept: dict[str, str] = {}
    for item_id, ts in seen.items():
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                kept[item_id] = ts
        except ValueError:
            kept[item_id] = datetime.now(timezone.utc).isoformat()
    return kept


def save_seen_items(path: Path, seen: dict[str, str]) -> None:
    """Persist seen items JSON to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def format_telegram_message(item: Opportunity) -> str:
    """Format an opportunity cleanly for Telegram HTML parse_mode."""
    label = html.escape(item.category_label)
    source = html.escape(item.source_name)
    title = html.escape(item.title)
    link = html.escape(item.link, quote=True)
    keywords = html.escape(", ".join(item.matched_keywords))

    lines = [
        f"<b>{label}</b> · <i>{source}</i>",
        f"<b><a href=\"{link}\">{title}</a></b>",
    ]
    if item.summary:
        lines.append(html.escape(item.summary))
    lines.append(f"🏷 <code>{keywords}</code>")
    if item.published:
        lines.append(f"🗓 {html.escape(item.published)}")
    return "\n\n".join(lines)


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    """Send one message via Telegram Bot API."""
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    response = requests.post(api_url, json=payload, timeout=15)
    if response.status_code == 429:
        retry_after = response.json().get("parameters", {}).get("retry_after", 5)
        logger.warning("Telegram rate limit hit; sleeping %ss", retry_after)
        time.sleep(float(retry_after) + 0.5)
        response = requests.post(api_url, json=payload, timeout=15)
    response.raise_for_status()


def load_config(path: Path) -> dict[str, Any]:
    """Load YAML configuration."""
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "categories" not in data:
        raise ValueError(f"Invalid configuration in {path}")
    return data


def collect_opportunities(config: dict[str, Any]) -> list[Opportunity]:
    """Fetch all enabled sources across categories and return matched items."""
    settings = config.get("settings", {})
    timeout = int(settings.get("request_timeout", 15))
    default_max_age = settings.get("max_post_age_days")
    allow_undated = bool(settings.get("allow_undated_posts", True))
    all_items: list[Opportunity] = []

    for cat_key, cat_cfg in config.get("categories", {}).items():
        label = cat_cfg.get("label", cat_key.title())
        include_kw = cat_cfg.get("include_keywords", [])
        exclude_kw = cat_cfg.get("exclude_keywords", [])
        cat_max_age = cat_cfg.get("max_post_age_days", default_max_age)
        max_age_days = float(cat_max_age) if cat_max_age is not None else None

        for source in cat_cfg.get("sources", []):
            if not source.get("enabled", True):
                continue
            source_type = source.get("type", "rss").lower()
            source_name = source.get("name", source.get("url", "Unknown"))
            try:
                if source_type == "rss":
                    found = parse_rss_source(
                        source,
                        cat_key,
                        label,
                        include_kw,
                        exclude_kw,
                        timeout,
                        max_age_days=max_age_days,
                        allow_undated=allow_undated,
                    )
                elif source_type == "html":
                    found = parse_html_source(
                        source, cat_key, label, include_kw, exclude_kw, timeout
                    )
                else:
                    logger.warning("Unknown source type '%s' for %s", source_type, source_name)
                    continue
                logger.info("Source '%s' (%s): %d matched items", source_name, cat_key, len(found))
                all_items.extend(found)
            except Exception as exc:  # noqa: BLE001 - one bad feed shouldn't stop the rest
                logger.error("Failed to fetch '%s': %s", source_name, exc)

    return all_items


def interleave_by_category(items: list[Opportunity]) -> list[Opportunity]:
    """Sort each category newest-first and interleave so no category starves others."""
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    buckets: dict[str, list[Opportunity]] = {}
    for item in items:
        buckets.setdefault(item.category, []).append(item)

    for bucket in buckets.values():
        bucket.sort(key=lambda o: o.published_dt or epoch, reverse=True)

    result: list[Opportunity] = []
    queues = list(buckets.values())
    idx = 0
    while True:
        added = False
        for q in queues:
            if idx < len(q):
                result.append(q[idx])
                added = True
        if not added:
            break
        idx += 1
    return result


def run(config_path: Path, seen_path: Path, dry_run: bool = False) -> int:
    """Execute one scrape + alert cycle. Returns number of new alerts processed."""
    config = load_config(config_path)
    settings = config.get("settings", {})
    max_alerts = int(settings.get("max_alerts_per_run", 15))
    retention_days = int(settings.get("seen_retention_days", 90))
    seed_on_first_run = bool(settings.get("seed_only_on_first_run", False))

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not dry_run and (not bot_token or not chat_id):
        logger.error(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID. "
            "Set them as environment variables or run with --dry-run."
        )
        sys.exit(1)

    seen, existed = load_seen_items(seen_path)
    seen = prune_seen_items(seen, retention_days)

    opportunities = collect_opportunities(config)

    # Deduplicate across sources within the same run as well as prior runs
    new_items: list[Opportunity] = []
    batch_ids: set[str] = set()
    for item in opportunities:
        if item.item_id in seen or item.item_id in batch_ids:
            continue
        batch_ids.add(item.item_id)
        new_items.append(item)

    logger.info("Total new matching opportunities: %d", len(new_items))
    now_iso = datetime.now(timezone.utc).isoformat()

    if not existed and seed_on_first_run:
        logger.info("First run with seed_only_on_first_run=true; marking items seen without sending.")
        for item in new_items:
            seen[item.item_id] = now_iso
        if not dry_run:
            save_seen_items(seen_path, seen)
        return 0

    to_send = interleave_by_category(new_items)[:max_alerts]
    sent_count = 0

    for item in to_send:
        message = format_telegram_message(item)
        if dry_run:
            print("-" * 60)
            print(f"[DRY RUN] {item.category_label} | {item.source_name}")
            print(f"Title: {item.title}")
            print(f"Link:  {item.link}")
            if item.published:
                print(f"Date:  {item.published}")
            print(f"Tags:  {', '.join(item.matched_keywords)}")
            sent_count += 1
        else:
            try:
                send_telegram_message(bot_token, chat_id, message)
                seen[item.item_id] = now_iso
                sent_count += 1
                time.sleep(0.5)  # Stay well below Telegram rate limits
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to send Telegram alert for '%s': %s", item.title, exc)

    if not dry_run:
        save_seen_items(seen_path, seen)

    logger.info("Done. Alerts processed: %d", sent_count)
    return sent_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check job & scholarship feeds and send Telegram alerts."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to config.yaml (default: config.yaml)",
    )
    parser.add_argument(
        "--seen",
        type=Path,
        default=DEFAULT_SEEN_PATH,
        help="Path to seen_items.json (default: data/seen_items.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print matching alerts to stdout instead of sending Telegram messages.",
    )
    args = parser.parse_args()
    run(config_path=args.config, seen_path=args.seen, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
