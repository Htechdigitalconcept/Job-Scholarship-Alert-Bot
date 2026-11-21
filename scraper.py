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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

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
DEFAULT_LATEST_PATH = Path("data/latest_items.json")
DEFAULT_SUBSCRIBERS_PATH = Path("data/subscribers.json")


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
    badges: list[str] = field(default_factory=list)
    deadline: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "category": self.category,
            "category_label": self.category_label,
            "source_name": self.source_name,
            "title": self.title,
            "link": self.link,
            "summary": self.summary,
            "matched_keywords": self.matched_keywords,
            "published": self.published,
            "published_iso": self.published_dt.isoformat() if self.published_dt else "",
            "badges": self.badges,
            "deadline": self.deadline,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Opportunity":
        published_dt: datetime | None = None
        iso_val = (data.get("published_iso") or "").strip()
        if iso_val:
            try:
                published_dt = datetime.fromisoformat(iso_val)
                if published_dt.tzinfo is None:
                    published_dt = published_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                published_dt = None
        return cls(
            item_id=str(data.get("item_id", "")),
            category=str(data.get("category", "")),
            category_label=str(data.get("category_label", "")),
            source_name=str(data.get("source_name", "")),
            title=str(data.get("title", "")),
            link=str(data.get("link", "")),
            summary=str(data.get("summary", "")),
            matched_keywords=[str(k) for k in data.get("matched_keywords", [])],
            published=str(data.get("published", "")),
            published_dt=published_dt,
            badges=[str(b) for b in data.get("badges", [])],
            deadline=str(data.get("deadline", "")),
        )


def make_item_id(link: str, title: str) -> str:
    """Create a stable hash ID for deduplication."""
    raw = (link.strip() or title.strip()).lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def normalize_title(title: str) -> str:
    """Normalize a posting title for cross-source duplicate detection."""
    cleaned = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def make_title_id(title: str) -> str:
    """Create a prefixed hash key from a normalized title."""
    norm = normalize_title(title)
    if not norm:
        return ""
    return "t:" + hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


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
    require_keywords: list[str] | None = None,
) -> list[str]:
    """Return matched include keywords if text passes require/include/exclude rules.

    - exclude_keywords: any match rejects the item.
    - require_keywords: if non-empty, at least one required keyword must match.
    - include_keywords: if empty, all passing items match with ['all'].
    """
    haystack = text.lower()

    def _contains_kw(kw: str) -> bool:
        kw_clean = kw.strip().lower()
        if not kw_clean:
            return False
        if re.fullmatch(r"[a-z0-9\s\-\+]+", kw_clean):
            pattern = r"(?<![a-z0-9])" + re.escape(kw_clean) + r"(?![a-z0-9])"
            return bool(re.search(pattern, haystack))
        return kw_clean in haystack

    for bad in exclude_keywords:
        if _contains_kw(bad):
            return []

    if require_keywords:
        req_clean = [k for k in require_keywords if k.strip()]
        if req_clean and not any(_contains_kw(req) for req in req_clean):
            return []

    if not include_keywords:
        return ["all"]

    matched: list[str] = []
    for kw in include_keywords:
        if _contains_kw(kw):
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


DEADLINE_RE = re.compile(
    r"(?:deadline|apply\s+by|closes(?:\s+on)?|closing\s+date|due\s+date)\s*[:\-–]?\s*"
    r"([A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}(?:,?\s*\d{4})?|"
    r"\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


def extract_deadline(text: str) -> str:
    """Extract a human-readable application deadline if mentioned."""
    if not text:
        return ""
    m = DEADLINE_RE.search(text)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip(" .,;:")[:40]


def extract_badges(
    text: str,
    category: str = "",
    extra_flags: dict[str, bool] | None = None,
) -> list[str]:
    """Derive helpful smart badges (Worldwide, Visa, Fully Funded, Entry/Intern)."""
    haystack = text.lower()
    flags = extra_flags or {}
    badges: list[str] = []

    if flags.get("worldwide") or any(
        term in haystack
        for term in (
            "worldwide",
            "no geographical restrictions",
            "work from anywhere",
            "anywhere in the world",
            "global remote",
        )
    ):
        badges.append("🌍 Worldwide")

    if flags.get("visa") or any(
        term in haystack
        for term in (
            "visa sponsorship",
            "visa sponsored",
            "sponsors visa",
            "relocation assistance",
            "relocation package",
        )
    ):
        badges.append("🛂 Visa Sponsored")

    if any(
        term in haystack
        for term in (
            "fully funded",
            "fully-funded",
            "full scholarship",
            "full funding",
            "tuition waiver",
            "all-expenses",
        )
    ):
        badges.append("💰 Fully Funded")

    if any(
        re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", haystack)
        for term in ("intern", "internship", "junior", "entry level", "entry-level", "graduate")
    ):
        badges.append("🟢 Entry / Intern")

    return badges


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
    require_kw: list[str] | None = None,
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
        matched = match_keywords(combined, include_kw, exclude_kw, require_keywords=require_kw)
        if not matched:
            continue

        full_text = f"{title} {clean_html_text(summary_raw, max_len=1200)}"
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
                badges=extract_badges(full_text, category=category_key),
                deadline=extract_deadline(full_text),
            )
        )
    return results


def parse_himalayas_source(
    source: dict[str, Any],
    category_key: str,
    category_label: str,
    include_kw: list[str],
    exclude_kw: list[str],
    timeout: int,
    max_age_days: float | None = None,
    allow_undated: bool = True,
    now: datetime | None = None,
    require_kw: list[str] | None = None,
) -> list[Opportunity]:
    """Fetch remote jobs from the public Himalayas JSON API."""
    raw_json = fetch_url(source["url"], timeout=timeout)
    payload = json.loads(raw_json)
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []

    results: list[Opportunity] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        raw_title = str(job.get("title") or "").strip()
        company = str(job.get("companyName") or "").strip()
        title = f"{company}: {raw_title}" if company and raw_title else raw_title
        link = str(job.get("applicationLink") or job.get("guid") or "").strip()
        summary_raw = str(job.get("excerpt") or job.get("description") or "")
        summary = clean_html_text(summary_raw, max_len=240)
        locs = job.get("locationRestrictions") or []
        seniority = " ".join(str(s) for s in (job.get("seniority") or []))

        published_dt: datetime | None = None
        published = ""
        pub_ts = job.get("pubDate")
        if isinstance(pub_ts, (int, float)):
            published_dt = datetime.fromtimestamp(float(pub_ts), tz=timezone.utc)
            published = published_dt.strftime("%a, %d %b %Y %H:%M:%S +0000")

        if not title or not link:
            continue
        if not is_recent_post(published_dt, max_age_days, allow_undated=allow_undated, now=now):
            continue

        loc_text = "worldwide remote" if not locs else f"remote {' '.join(str(x) for x in locs)}"
        combined = f"{title} {summary} {loc_text} {seniority}"
        matched = match_keywords(combined, include_kw, exclude_kw, require_keywords=require_kw)
        if not matched:
            continue

        full_text = f"{title} {clean_html_text(summary_raw, max_len=1200)} {loc_text} {seniority}"
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
                badges=extract_badges(
                    full_text,
                    category=category_key,
                    extra_flags={"worldwide": not locs},
                ),
                deadline=extract_deadline(full_text),
            )
        )
    return results


def parse_arbeitnow_source(
    source: dict[str, Any],
    category_key: str,
    category_label: str,
    include_kw: list[str],
    exclude_kw: list[str],
    timeout: int,
    max_age_days: float | None = None,
    allow_undated: bool = True,
    now: datetime | None = None,
    require_kw: list[str] | None = None,
) -> list[Opportunity]:
    """Fetch remote & visa-sponsored jobs from the public Arbeitnow JSON API."""
    raw_json = fetch_url(source["url"], timeout=timeout)
    payload = json.loads(raw_json)
    jobs = payload.get("data", []) if isinstance(payload, dict) else []

    results: list[Opportunity] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        raw_title = str(job.get("title") or "").strip()
        company = str(job.get("company_name") or "").strip()
        title = f"{company}: {raw_title}" if company and raw_title else raw_title
        link = str(job.get("url") or "").strip()
        summary_raw = str(job.get("description") or "")
        summary = clean_html_text(summary_raw, max_len=240)
        tags_text = " ".join(str(t) for t in (job.get("tags") or []))
        is_remote = bool(job.get("remote", False))
        has_visa = "visa" in tags_text.lower() or "visa sponsorship" in summary_raw.lower()

        if not (is_remote or has_visa):
            continue

        published_dt: datetime | None = None
        published = ""
        created_ts = job.get("created_at")
        if isinstance(created_ts, (int, float)):
            published_dt = datetime.fromtimestamp(float(created_ts), tz=timezone.utc)
            published = published_dt.strftime("%a, %d %b %Y %H:%M:%S +0000")

        if not title or not link:
            continue
        if not is_recent_post(published_dt, max_age_days, allow_undated=allow_undated, now=now):
            continue

        remote_tag = "remote" if is_remote else ""
        combined = f"{title} {summary} {tags_text} {remote_tag}"
        matched = match_keywords(combined, include_kw, exclude_kw, require_keywords=require_kw)
        if not matched:
            continue

        full_text = f"{title} {clean_html_text(summary_raw, max_len=1200)} {tags_text}"
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
                badges=extract_badges(
                    full_text,
                    category=category_key,
                    extra_flags={"visa": has_visa},
                ),
                deadline=extract_deadline(full_text),
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
    require_kw: list[str] | None = None,
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
        matched = match_keywords(combined, include_kw, exclude_kw, require_keywords=require_kw)
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
                badges=extract_badges(combined, category=category_key),
                deadline=extract_deadline(combined),
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


def load_latest_items(path: Path) -> list[Opportunity]:
    """Load cached recent opportunities from JSON."""
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [Opportunity.from_dict(item) for item in raw if isinstance(item, dict)]
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read %s (%s); ignoring cache.", path, exc)
    return []


def save_latest_items(
    path: Path,
    new_items: list[Opportunity],
    config: dict[str, Any],
    limit: int = 200,
) -> list[Opportunity]:
    """Merge fresh opportunities into latest_items.json, pruning stale entries."""
    settings = config.get("settings", {})
    default_max_age = settings.get("max_post_age_days")
    allow_undated = bool(settings.get("allow_undated_posts", True))
    categories = config.get("categories", {})

    existing = load_latest_items(path)
    merged_by_id: dict[str, Opportunity] = {}
    seen_titles: set[str] = set()
    for item in [*new_items, *existing]:
        if not item.item_id or item.item_id in merged_by_id:
            continue
        norm_title = normalize_title(item.title)
        if norm_title and norm_title in seen_titles:
            continue
        cat_cfg = categories.get(item.category, {})
        cat_max_age = cat_cfg.get("max_post_age_days", default_max_age)
        max_age = float(cat_max_age) if cat_max_age is not None else None
        if is_recent_post(item.published_dt, max_age, allow_undated=allow_undated):
            merged_by_id[item.item_id] = item
            if norm_title:
                seen_titles.add(norm_title)

    epoch = datetime.min.replace(tzinfo=timezone.utc)
    sorted_items = sorted(
        merged_by_id.values(),
        key=lambda o: o.published_dt or epoch,
        reverse=True,
    )
    balanced_items = interleave_by_category(sorted_items)[:limit]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([item.to_dict() for item in balanced_items], indent=2) + "\n",
        encoding="utf-8",
    )
    return balanced_items


def _get_gist_credentials() -> tuple[str, str]:
    """Return optional (gist_id, token) for private Gist subscriber storage."""
    gist_id = os.environ.get("SUBSCRIBERS_GIST_ID", "").strip()
    token = (
        os.environ.get("SUBSCRIBERS_GITHUB_TOKEN", "").strip()
        or os.environ.get("GITHUB_TOKEN", "").strip()
    )
    return gist_id, token


def load_subscribers(path: Path) -> dict[str, dict[str, Any]]:
    """Load optional personal DM subscriber preferences (Gist or local JSON)."""
    gist_id, token = _get_gist_credentials()
    if gist_id and token:
        try:
            resp = requests.get(
                f"https://api.github.com/gists/{gist_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=10,
            )
            resp.raise_for_status()
            files = resp.json().get("files", {})
            raw_content = (files.get("subscribers.json") or {}).get("content", "{}")
            data = json.loads(raw_content)
            if isinstance(data, dict):
                return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load subscribers from Gist (%s); falling back to disk.", exc)

    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read %s (%s); skipping subscribers.", path, exc)
    return {}


def save_subscribers(path: Path, subscribers: dict[str, dict[str, Any]]) -> None:
    """Persist personal DM subscriber preferences (private Gist or local JSON)."""
    payload_text = json.dumps(subscribers, indent=2, sort_keys=True) + "\n"
    gist_id, token = _get_gist_credentials()
    if gist_id and token:
        resp = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            json={"files": {"subscribers.json": {"content": payload_text}}},
            timeout=10,
        )
        resp.raise_for_status()
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload_text, encoding="utf-8")


def get_public_site_url(config: dict[str, Any] | None = None) -> str:
    """Return the public Live Web Board URL."""
    url = os.environ.get("PUBLIC_SITE_URL", "").strip()
    if url:
        return url.rstrip("/")
    if config:
        cfg_url = str(config.get("settings", {}).get("public_site_url", "")).strip()
        if cfg_url:
            return cfg_url.rstrip("/")
    return "https://job-scholarship-alert-bot-chi.vercel.app"


def get_broadcast_target(config: dict[str, Any] | None = None) -> str:
    """Return channel/chat target from env vars or config.yaml."""
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
    if channel_id:
        return channel_id
    if config:
        cfg_channel = str(config.get("settings", {}).get("channel_id", "")).strip()
        if cfg_channel:
            return cfg_channel
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def get_public_channel_url(config: dict[str, Any] | None = None) -> str:
    """Return the public Telegram channel URL if configured."""
    url = os.environ.get("PUBLIC_CHANNEL_URL", "").strip()
    if url:
        return url
    target = get_broadcast_target(config)
    if target.startswith("@"):
        return f"https://t.me/{target[1:]}"
    if config:
        cfg_url = str(config.get("settings", {}).get("public_channel_url", "")).strip()
        if cfg_url:
            return cfg_url
    return ""


_BOT_USERNAME_CACHE: dict[str, str] = {}


def get_bot_url(bot_token: str = "", config: dict[str, Any] | None = None) -> str:
    """Return the public Telegram bot URL (https://t.me/<bot_username>) for channel buttons."""
    direct_url = os.environ.get("PUBLIC_BOT_URL", "").strip()
    if direct_url:
        return direct_url.rstrip("/")

    username = os.environ.get("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
    if not username and config:
        username = str(config.get("settings", {}).get("bot_username", "")).strip().lstrip("@")
    if not username and bot_token and ":" in bot_token:
        if bot_token in _BOT_USERNAME_CACHE:
            username = _BOT_USERNAME_CACHE[bot_token]
        else:
            try:
                resp = requests.get(
                    f"https://api.telegram.org/bot{bot_token}/getMe",
                    timeout=10,
                )
                resp.raise_for_status()
                username = str((resp.json().get("result") or {}).get("username", "")).strip()
                if username:
                    _BOT_USERNAME_CACHE[bot_token] = username
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not fetch bot username via getMe: %s", exc)
    return f"https://t.me/{username}" if username else ""


def build_telegram_hashtags(item: Opportunity) -> str:
    """Build clickable Telegram search hashtags from category, badges, and keywords."""
    tags: list[str] = []
    if item.category == "jobs":
        tags.extend(["#RemoteJobs", "#TechJobs"])
    elif item.category == "web3_jobs":
        tags.extend(["#Web3Jobs", "#CryptoJobs", "#RemoteJobs"])
    elif item.category == "scholarships":
        tags.extend(["#Scholarships", "#Fellowships"])

    badge_map = {
        "🌍 Worldwide": "#WorldwideRemote",
        "🛂 Visa Sponsored": "#VisaSponsored",
        "💰 Fully Funded": "#FullyFunded",
        "🟢 Entry / Intern": "#EntryLevel",
    }
    for badge in item.badges:
        if badge in badge_map and badge_map[badge] not in tags:
            tags.append(badge_map[badge])

    for kw in item.matched_keywords[:3]:
        clean = re.sub(r"[^A-Za-z0-9]+", "", kw.title())
        if clean and len(clean) >= 2:
            ht = f"#{clean}"
            if ht not in tags:
                tags.append(ht)
    return " ".join(tags[:6])


def build_telegram_share_url(target_url: str, text: str) -> str:
    """Build a one-tap Telegram share link (https://t.me/share/url?...)."""
    return (
        "https://t.me/share/url"
        f"?url={quote(target_url, safe='')}"
        f"&text={quote(text, safe='')}"
    )


def build_item_reply_markup(
    item: Opportunity,
    channel_url: str = "",
    bot_url: str = "",
) -> dict[str, Any]:
    """Build inline Telegram buttons under an individual opportunity alert."""
    row: list[dict[str, str]] = [{"text": "Apply Now 🔗", "url": item.link}]
    if bot_url:
        row.append({"text": "Filter in Bot 🤖", "url": f"{bot_url}?start=latest"})
    elif channel_url:
        row.append({"text": "Join Channel 📢", "url": channel_url})
    share_target = bot_url or channel_url
    share_note = (
        f"{item.title} — found via {share_target}"
        if share_target
        else item.title
    )
    rows = [
        row,
        [{"text": "📤 Share Opportunity", "url": build_telegram_share_url(item.link, share_note)}],
    ]
    return {"inline_keyboard": rows}


def format_telegram_message(item: Opportunity, channel_tag: str = "") -> str:
    """Format an opportunity cleanly for Telegram HTML parse_mode."""
    label = html.escape(item.category_label)
    source = html.escape(item.source_name)
    title = html.escape(item.title)
    link = html.escape(item.link, quote=True)
    keywords = html.escape(", ".join(item.matched_keywords))
    hashtags = build_telegram_hashtags(item)

    lines = [
        f"<b>{label}</b> · <i>{source}</i>",
        f"<b><a href=\"{link}\">{title}</a></b>",
    ]
    if item.badges:
        lines.append(html.escape(" · ".join(item.badges)))
    if item.summary:
        lines.append(html.escape(item.summary))
    lines.append(f"🏷 <code>{keywords}</code>")
    if item.deadline:
        lines.append(f"⏳ <b>Deadline:</b> {html.escape(item.deadline)}")
    if item.published:
        lines.append(f"🗓 {html.escape(item.published)}")
    footer_parts = [p for p in [f"📢 {html.escape(channel_tag)}" if channel_tag else "", html.escape(hashtags)] if p]
    if footer_parts:
        lines.append(" · ".join(footer_parts))
    return "\n\n".join(lines)


def format_daily_digest(
    items: list[Opportunity],
    channel_tag: str = "",
    limit: int = 9,
) -> str:
    """Format a compact daily digest message across categories."""
    top = interleave_by_category(items)[:limit]
    today = datetime.now(timezone.utc).strftime("%b %d, %Y")
    if not top:
        return f"<b>☀️ Daily Opportunities Digest ({today})</b>\n\nNo recent opportunities found today."

    lines = [f"<b>☀️ Daily Opportunities Digest · {html.escape(today)}</b>"]
    for idx, item in enumerate(top, start=1):
        title = html.escape(item.title)
        link = html.escape(item.link, quote=True)
        badge_str = f" · {html.escape(' '.join(item.badges))}" if item.badges else ""
        deadline_str = f" · ⏳ {html.escape(item.deadline)}" if item.deadline else ""
        lines.append(
            f"{idx}. {html.escape(item.category_label)}: "
            f"<b><a href=\"{link}\">{title}</a></b>{badge_str}{deadline_str}"
        )
    if channel_tag:
        lines.append(f"📢 Follow {html.escape(channel_tag)} for instant updates")
    return "\n\n".join(lines)


def _post_telegram_api(bot_token: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST to Telegram Bot API with basic 429 retry handling."""
    api_url = f"https://api.telegram.org/bot{bot_token}/{method}"
    response = requests.post(api_url, json=payload, timeout=15)
    if response.status_code == 429:
        retry_after = response.json().get("parameters", {}).get("retry_after", 5)
        logger.warning("Telegram rate limit hit; sleeping %ss", retry_after)
        time.sleep(float(retry_after) + 0.5)
        response = requests.post(api_url, json=payload, timeout=15)
    response.raise_for_status()
    return response.json()


def build_cycle_reminder_markup(
    channel_url: str = "",
    site_url: str = "",
    bot_url: str = "",
    include_unsubscribe: bool = False,
) -> dict[str, Any] | None:
    """Build inline buttons for cycle summary reminder notifications."""
    rows: list[list[dict[str, str]]] = []
    link_row: list[dict[str, str]] = []
    if site_url:
        link_row.append({"text": "🌐 Live Web Board", "url": site_url})
    if include_unsubscribe:
        if channel_url:
            link_row.append({"text": "📢 Open Channel", "url": channel_url})
    else:
        if bot_url:
            link_row.append({"text": "Filter in Bot 🤖", "url": f"{bot_url}?start=latest"})
        elif channel_url:
            link_row.append({"text": "📢 Open Channel", "url": channel_url})
    if link_row:
        rows.append(link_row)
    if include_unsubscribe:
        rows.append([{"text": "🔕 Pause Reminders", "callback_data": "sub:off"}])
    else:
        share_url = bot_url or site_url or channel_url
        if share_url:
            rows.append([{
                "text": "📤 Share Bot with a Friend",
                "url": build_telegram_share_url(
                    share_url,
                    "🚀 Check out this free 24/7 Bot & Live Board for Remote Tech Jobs, Web3 Roles & Fully Funded Scholarships!",
                ),
            }])
    return {"inline_keyboard": rows} if rows else None


def format_cycle_reminder(
    items: list[Opportunity],
    channel_tag: str = "",
    site_url: str = "",
    for_subscriber: bool = False,
) -> str:
    """Format a cycle notification reminder summarizing newly posted items."""
    count = len(items)
    jobs_n = sum(1 for i in items if i.category == "jobs")
    web3_n = sum(1 for i in items if i.category == "web3_jobs")
    sch_n = sum(1 for i in items if i.category == "scholarships")

    breakdown_parts: list[str] = []
    if jobs_n:
        breakdown_parts.append(f"💼 {jobs_n} Job{'s' if jobs_n != 1 else ''}")
    if web3_n:
        breakdown_parts.append(f"⛓️ {web3_n} Web3")
    if sch_n:
        breakdown_parts.append(f"🎓 {sch_n} Scholarship{'s' if sch_n != 1 else ''}")

    header = (
        f"🔔 <b>New Cycle Alert: {count} New Match{'es' if count != 1 else ''} Posted!</b>"
        if for_subscriber
        else f"🔔 <b>New Cycle Update: {count} Fresh Opportunit{'ies' if count != 1 else 'y'} Just Posted!</b>"
    )
    lines = [header]
    if breakdown_parts:
        lines.append("📊 " + " · ".join(breakdown_parts))

    badge_counts: dict[str, int] = {}
    for item in items:
        for b in item.badges:
            badge_counts[b] = badge_counts.get(b, 0) + 1
    if badge_counts:
        badge_line = " · ".join(f"{b} ({c})" for b, c in badge_counts.items())
        lines.append(html.escape(badge_line))

    highlights = interleave_by_category(items)[:4]
    if highlights:
        top_lines = []
        for idx, item in enumerate(highlights, start=1):
            title = html.escape(item.title)
            link = html.escape(item.link, quote=True)
            top_lines.append(f"{idx}. <a href=\"{link}\">{title}</a>")
        lines.append("<b>Highlights:</b>\n" + "\n".join(top_lines))

    footer_bits = ["💡 Use /latest, /jobs, /web3, or /scholarships anytime."]
    if channel_tag:
        footer_bits.append(f"📢 Channel: {html.escape(channel_tag)}")
    if site_url:
        footer_bits.append(f"🌐 Web: {html.escape(site_url)}")
    footer_bits.append("#RemoteJobs #Web3Jobs #Scholarships #WorldwideRemote #FullyFunded")
    lines.append("\n".join(footer_bits))
    return "\n\n".join(lines)


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    reply_markup: dict[str, Any] | None = None,
    disable_web_page_preview: bool = False,
    disable_notification: bool = False,
) -> None:
    """Send one message via Telegram Bot API."""
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_web_page_preview,
    }
    if disable_notification:
        payload["disable_notification"] = True
    if reply_markup:
        payload["reply_markup"] = reply_markup
    _post_telegram_api(bot_token, "sendMessage", payload)


def edit_telegram_message(
    bot_token: str,
    chat_id: str,
    message_id: int,
    text: str,
    reply_markup: dict[str, Any] | None = None,
) -> None:
    """Edit an existing Telegram message in place (used for inline pagination)."""
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    _post_telegram_api(bot_token, "editMessageText", payload)


def answer_callback_query(
    bot_token: str,
    callback_query_id: str,
    text: str = "",
) -> None:
    """Acknowledge an inline keyboard button press."""
    payload: dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    _post_telegram_api(bot_token, "answerCallbackQuery", payload)


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
        require_kw = cat_cfg.get("require_keywords", [])
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
                        require_kw=require_kw,
                    )
                elif source_type == "himalayas":
                    found = parse_himalayas_source(
                        source,
                        cat_key,
                        label,
                        include_kw,
                        exclude_kw,
                        timeout,
                        max_age_days=max_age_days,
                        allow_undated=allow_undated,
                        require_kw=require_kw,
                    )
                elif source_type == "arbeitnow":
                    found = parse_arbeitnow_source(
                        source,
                        cat_key,
                        label,
                        include_kw,
                        exclude_kw,
                        timeout,
                        max_age_days=max_age_days,
                        allow_undated=allow_undated,
                        require_kw=require_kw,
                    )
                elif source_type == "html":
                    found = parse_html_source(
                        source,
                        cat_key,
                        label,
                        include_kw,
                        exclude_kw,
                        timeout,
                        require_kw=require_kw,
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


def send_subscriber_alerts(
    bot_token: str,
    items: list[Opportunity],
    subscribers_path: Path,
    broadcast_target: str,
    channel_url: str = "",
    channel_tag: str = "",
    site_url: str = "",
) -> int:
    """Send one cycle notification reminder DM per opted-in subscriber."""
    subscribers = load_subscribers(subscribers_path)
    if not subscribers or not items:
        return 0

    dm_sent = 0
    markup = build_cycle_reminder_markup(
        channel_url=channel_url,
        site_url=site_url,
        include_unsubscribe=True,
    )
    for chat_id, prefs in subscribers.items():
        if not prefs.get("subscribed", False):
            continue
        if str(chat_id) == str(broadcast_target):
            continue
        user_keywords = [k.strip() for k in prefs.get("keywords", []) if k.strip()]
        if user_keywords:
            matched = [
                item
                for item in items
                if match_keywords(f"{item.title} {item.summary}", user_keywords, [])
            ]
        else:
            matched = list(items)
        if not matched:
            continue
        reminder = format_cycle_reminder(
            matched,
            channel_tag=channel_tag,
            site_url=site_url,
            for_subscriber=True,
        )
        try:
            send_telegram_message(
                bot_token,
                str(chat_id),
                reminder,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            dm_sent += 1
            time.sleep(0.35)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed DM to subscriber %s: %s", chat_id, exc)
    return dm_sent


def run(
    config_path: Path,
    seen_path: Path,
    dry_run: bool = False,
    latest_path: Path = DEFAULT_LATEST_PATH,
    subscribers_path: Path = DEFAULT_SUBSCRIBERS_PATH,
    send_digest: bool = False,
) -> int:
    """Execute one scrape + alert cycle. Returns number of new alerts processed."""
    config = load_config(config_path)
    settings = config.get("settings", {})
    max_alerts = int(settings.get("max_alerts_per_run", 15))
    latest_cache_limit = int(settings.get("latest_cache_limit", 200))
    retention_days = int(settings.get("seen_retention_days", 90))
    seed_on_first_run = bool(settings.get("seed_only_on_first_run", False))
    cycle_reminder = bool(settings.get("cycle_reminder", True))
    quiet_item_alerts = bool(settings.get("quiet_item_alerts", True))

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    target_id = get_broadcast_target(config)
    channel_tag = target_id if target_id.startswith("@") else os.environ.get("PUBLIC_CHANNEL_HANDLE", "").strip()
    channel_url = get_public_channel_url(config)
    site_url = get_public_site_url(config)
    bot_url = get_bot_url(bot_token if not dry_run else "", config)

    if not dry_run and (not bot_token or not target_id):
        logger.error(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID/TELEGRAM_CHAT_ID. "
            "Set them as environment variables or run with --dry-run."
        )
        sys.exit(1)

    seen, existed = load_seen_items(seen_path)
    seen = prune_seen_items(seen, retention_days)

    opportunities = collect_opportunities(config)

    if not dry_run:
        save_latest_items(latest_path, opportunities, config, limit=latest_cache_limit)

    # Deduplicate across sources (both by link/item_id and normalized title)
    new_items: list[Opportunity] = []
    batch_ids: set[str] = set()
    batch_titles: set[str] = set()
    for item in opportunities:
        title_id = make_title_id(item.title)
        if item.item_id in seen or item.item_id in batch_ids:
            continue
        if title_id and (title_id in seen or title_id in batch_titles):
            continue
        batch_ids.add(item.item_id)
        if title_id:
            batch_titles.add(title_id)
        new_items.append(item)

    logger.info("Total new matching opportunities: %d", len(new_items))
    now_iso = datetime.now(timezone.utc).isoformat()

    if not existed and seed_on_first_run:
        logger.info("First run with seed_only_on_first_run=true; marking items seen without sending.")
        for item in new_items:
            seen[item.item_id] = now_iso
            title_id = make_title_id(item.title)
            if title_id:
                seen[title_id] = now_iso
        if not dry_run:
            save_seen_items(seen_path, seen)
        return 0

    to_send = interleave_by_category(new_items)[:max_alerts]
    posted_items: list[Opportunity] = []
    sent_count = 0

    for item in to_send:
        message = format_telegram_message(item, channel_tag=channel_tag)
        if dry_run:
            print("-" * 60)
            print(f"[DRY RUN] {item.category_label} | {item.source_name}")
            print(f"Title: {item.title}")
            print(f"Link:  {item.link}")
            if item.badges:
                print(f"Badge: {' · '.join(item.badges)}")
            if item.deadline:
                print(f"Due:   {item.deadline}")
            if item.published:
                print(f"Date:  {item.published}")
            print(f"Tags:  {', '.join(item.matched_keywords)}")
            posted_items.append(item)
            sent_count += 1
        else:
            try:
                reply_markup = build_item_reply_markup(
                    item, channel_url=channel_url, bot_url=bot_url
                )
                send_telegram_message(
                    bot_token,
                    target_id,
                    message,
                    reply_markup=reply_markup,
                    disable_notification=cycle_reminder and quiet_item_alerts,
                )
                seen[item.item_id] = now_iso
                title_id = make_title_id(item.title)
                if title_id:
                    seen[title_id] = now_iso
                posted_items.append(item)
                sent_count += 1
                time.sleep(0.5)  # Stay well below Telegram rate limits
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to send Telegram alert for '%s': %s", item.title, exc)

    if cycle_reminder and posted_items:
        reminder_text = format_cycle_reminder(
            posted_items,
            channel_tag=channel_tag,
            site_url=site_url,
            for_subscriber=False,
        )
        if dry_run:
            print("=" * 60)
            print("[DRY RUN CYCLE REMINDER]")
            print(reminder_text)
        else:
            try:
                reminder_markup = build_cycle_reminder_markup(
                    channel_url=channel_url,
                    site_url=site_url,
                    bot_url=bot_url,
                    include_unsubscribe=False,
                )
                send_telegram_message(
                    bot_token,
                    target_id,
                    reminder_text,
                    reply_markup=reminder_markup,
                    disable_web_page_preview=True,
                    disable_notification=False,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to send channel cycle reminder: %s", exc)

    if send_digest and opportunities:
        digest_text = format_daily_digest(opportunities, channel_tag=channel_tag)
        if dry_run:
            print("=" * 60)
            print("[DRY RUN DIGEST]")
            print(digest_text)
        else:
            try:
                digest_row: list[dict[str, str]] = []
                if site_url:
                    digest_row.append({"text": "🌐 Live Web Board", "url": site_url})
                if bot_url:
                    digest_row.append({"text": "Filter in Bot 🤖", "url": f"{bot_url}?start=latest"})
                elif channel_url:
                    digest_row.append({"text": "Join Channel 📢", "url": channel_url})
                markup = {"inline_keyboard": [digest_row]} if digest_row else None
                send_telegram_message(
                    bot_token,
                    target_id,
                    digest_text,
                    reply_markup=markup,
                    disable_web_page_preview=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to send daily digest: %s", exc)

    if not dry_run:
        save_seen_items(seen_path, seen)
        dm_count = send_subscriber_alerts(
            bot_token,
            posted_items,
            subscribers_path,
            target_id,
            channel_url=channel_url,
            channel_tag=channel_tag,
            site_url=site_url,
        )
        if dm_count:
            logger.info("Personal DM cycle reminders sent: %d", dm_count)

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
        "--latest",
        type=Path,
        default=DEFAULT_LATEST_PATH,
        help="Path to latest_items.json cache (default: data/latest_items.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print matching alerts to stdout instead of sending Telegram messages.",
    )
    parser.add_argument(
        "--digest",
        action="store_true",
        help="Also send a Daily Opportunities Digest summary message.",
    )
    parser.add_argument(
        "--digest-hour",
        type=int,
        default=None,
        help="Send the Daily Digest only when current UTC hour matches (e.g. 6).",
    )
    args = parser.parse_args()
    should_digest = bool(args.digest)
    if args.digest_hour is not None:
        should_digest = should_digest or (datetime.now(timezone.utc).hour == args.digest_hour)

    run(
        config_path=args.config,
        seen_path=args.seen,
        dry_run=args.dry_run,
        latest_path=args.latest,
        send_digest=should_digest,
    )


if __name__ == "__main__":
    main()
