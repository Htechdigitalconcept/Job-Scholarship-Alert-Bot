"""Vercel Python WSGI entrypoint: Telegram Webhook, Live Web Board & SEO/AI endpoints."""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import scraper

logging.getLogger().addFilter(scraper.SecretRedactingFilter())
logger = logging.getLogger(__name__)

MAX_WEBHOOK_BYTES = 1_048_576  # 1 MiB cap against payload DoS
DEFAULT_PUBLIC_SITE = "https://job-scholarship-alert-bot-chi.vercel.app"
_RATE_BUCKETS: dict[tuple[str, str], deque[float]] = {}
_RATE_WINDOW_SECONDS = 60.0
_API_RATE_LIMIT = 60
_WEBHOOK_RATE_LIMIT = 120


def _get_client_ip(environ: dict[str, Any]) -> str:
    fwd = str(environ.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if fwd:
        return fwd.split(",", 1)[0].strip()
    return str(environ.get("REMOTE_ADDR") or "unknown").strip()


def _is_rate_limited(client_ip: str, bucket: str, limit: int) -> bool:
    if not client_ip or client_ip == "unknown":
        return False
    now = time.monotonic()
    key = (bucket, client_ip)
    q = _RATE_BUCKETS.get(key)
    if q is None:
        q = deque()
        _RATE_BUCKETS[key] = q
    cutoff = now - _RATE_WINDOW_SECONDS
    while q and q[0] < cutoff:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    if len(_RATE_BUCKETS) > 1000:
        stale = [k for k, dq in _RATE_BUCKETS.items() if not dq or dq[-1] < cutoff]
        for k in stale:
            _RATE_BUCKETS.pop(k, None)
    return False

SECURITY_HEADERS: list[tuple[str, str]] = [
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Permissions-Policy", "geolocation=(), microphone=(), camera=()"),
    ("Strict-Transport-Security", "max-age=31536000; includeSubDomains"),
]

HTML_CSP_HEADER = (
    "Content-Security-Policy",
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://telegram.org; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org; "
    "base-uri 'self'; "
    "form-action 'self'",
)

STATUS_TEXT = {
    200: "200 OK",
    400: "400 Bad Request",
    403: "403 Forbidden",
    404: "404 Not Found",
    405: "405 Method Not Allowed",
    413: "413 Payload Too Large",
    429: "429 Too Many Requests",
    500: "500 Internal Server Error",
}


def handle_webhook_request(
    raw_body: bytes,
    secret_header: str = "",
) -> tuple[int, dict[str, Any]]:
    """Process a raw webhook POST payload and return (status_code, json_body)."""
    if len(raw_body) > MAX_WEBHOOK_BYTES:
        return 413, {"ok": False, "error": "Payload too large"}

    expected_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    require_secret = os.environ.get("REQUIRE_WEBHOOK_SECRET", "").strip().lower() in {"1", "true", "yes"}
    if require_secret and not expected_secret:
        return 500, {"ok": False, "error": "Webhook secret not configured"}
    if expected_secret:
        if not secret_header or not hmac.compare_digest(
            secret_header.encode("utf-8"),
            expected_secret.encode("utf-8"),
        ):
            return 403, {"ok": False, "error": "Invalid secret token"}

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        return 500, {"ok": False, "error": "Missing TELEGRAM_BOT_TOKEN"}

    try:
        update = json.loads(raw_body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 400, {"ok": False, "error": "Invalid JSON body"}

    if not isinstance(update, dict):
        return 400, {"ok": False, "error": "Expected JSON object"}

    try:
        import bot_commands

        handled = bot_commands.process_webhook_update(
            update=update,
            bot_token=bot_token,
            config_path=BASE_DIR / "config.yaml",
            latest_path=BASE_DIR / "data" / "latest_items.json",
            subscribers_path=BASE_DIR / "data" / "subscribers.json",
        )
        return 200, {"ok": True, "handled": handled}
    except Exception as exc:  # noqa: BLE001
        logger.error("Webhook error: %s", scraper.redact_secrets(str(exc)))
        return 200, {"ok": False, "error": "Webhook processing error"}


def _detect_site_url(environ: dict[str, Any]) -> str:
    env_url = scraper.sanitize_http_url(os.environ.get("PUBLIC_SITE_URL", "").strip())
    if env_url:
        return env_url.rstrip("/")

    raw_host = str(environ.get("HTTP_X_FORWARDED_HOST") or environ.get("HTTP_HOST") or "").strip()
    host_only = raw_host.split(",", 1)[0].strip().split(":", 1)[0].lower()
    allowed_default_host = (urlparse(DEFAULT_PUBLIC_SITE).hostname or "").lower()
    if host_only and (
        host_only == allowed_default_host
        or re.fullmatch(r"[a-z0-9-]{1,63}\.vercel\.app", host_only)
    ):
        proto = str(environ.get("HTTP_X_FORWARDED_PROTO") or "https").strip().lower()
        if proto not in {"http", "https"}:
            proto = "https"
        return f"{proto}://{host_only}".rstrip("/")
    return DEFAULT_PUBLIC_SITE


def _load_board_data() -> tuple[list[Any], str, str, list[dict[str, str]]]:
    import bot_commands
    import scraper

    config = scraper.load_config(BASE_DIR / "config.yaml")
    items = bot_commands.get_recent_opportunities(config, BASE_DIR / "data" / "latest_items.json")
    channel_url = scraper.get_public_channel_url(config) or "https://t.me/latestjobsandscholarship"
    channel_handle = str(config.get("settings", {}).get("channel_id", "@latestjobsandscholarship")).strip()
    tools = scraper.get_recommended_tools(config)
    return items, channel_url, channel_handle, tools


def app(
    environ: dict[str, Any],
    start_response: Callable[[str, list[tuple[str, str]]], Any],
) -> Iterable[bytes]:
    """Standard WSGI entrypoint serving Web Board, SEO/AI endpoints, and Telegram Webhook."""
    method = str(environ.get("REQUEST_METHOD", "GET")).upper()
    path = str(environ.get("PATH_INFO", "/")).rstrip("/") or "/"
    site_url = _detect_site_url(environ)

    if method in {"GET", "HEAD"}:
        if path in {"/", "/index.html"}:
            import web_board

            items, channel_url, channel_handle, tools = _load_board_data()
            qs = parse_qs(str(environ.get("QUERY_STRING", "")), keep_blank_values=False)
            focus_item_id = (qs.get("item") or [""])[0].strip()[:32]
            html_doc = web_board.render_web_board_html(
                items,
                channel_url=channel_url,
                channel_handle=channel_handle,
                site_url=site_url,
                recommended_tools=tools,
                focus_item_id=focus_item_id,
            )
            body = html_doc.encode("utf-8")
            headers = [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("X-Robots-Tag", "index, follow"),
                HTML_CSP_HEADER,
                *SECURITY_HEADERS,
            ]
            start_response(STATUS_TEXT[200], headers)
            return [] if method == "HEAD" else [body]

        if path == "/robots.txt":
            import web_board

            body = web_board.render_robots_txt(site_url).encode("utf-8")
            headers = [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(body))),
                *SECURITY_HEADERS,
            ]
            start_response(STATUS_TEXT[200], headers)
            return [] if method == "HEAD" else [body]

        if path == "/sitemap.xml":
            import web_board

            items, _url, _handle, _tools = _load_board_data()
            body = web_board.render_sitemap_xml(site_url, items).encode("utf-8")
            headers = [
                ("Content-Type", "application/xml; charset=utf-8"),
                ("Content-Length", str(len(body))),
                *SECURITY_HEADERS,
            ]
            start_response(STATUS_TEXT[200], headers)
            return [] if method == "HEAD" else [body]

        if path in {"/feed.xml", "/rss.xml"}:
            import web_board

            items, _url, _handle, _tools = _load_board_data()
            body = web_board.render_rss_feed(site_url, items).encode("utf-8")
            headers = [
                ("Content-Type", "application/rss+xml; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "public, max-age=1800"),
                *SECURITY_HEADERS,
            ]
            start_response(STATUS_TEXT[200], headers)
            return [] if method == "HEAD" else [body]

        if path == "/llms.txt":
            import web_board

            items, channel_url, channel_handle, _tools = _load_board_data()
            body = web_board.render_llms_txt(
                site_url, items, channel_url=channel_url, channel_handle=channel_handle
            ).encode("utf-8")
            headers = [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(body))),
                *SECURITY_HEADERS,
            ]
            start_response(STATUS_TEXT[200], headers)
            return [] if method == "HEAD" else [body]

        if path == "/logo.png":
            logo_file = BASE_DIR / "assets" / "logo.png"
            if logo_file.is_file():
                body = logo_file.read_bytes()
                headers = [
                    ("Content-Type", "image/png"),
                    ("Content-Length", str(len(body))),
                    ("Cache-Control", "public, max-age=86400"),
                    *SECURITY_HEADERS,
                ]
                start_response(STATUS_TEXT[200], headers)
                return [] if method == "HEAD" else [body]

        if path in {"/favicon.png", "/favicon.ico"}:
            fav_file = BASE_DIR / "assets" / "favicon.png"
            if fav_file.is_file():
                body = fav_file.read_bytes()
                headers = [
                    ("Content-Type", "image/png"),
                    ("Content-Length", str(len(body))),
                    ("Cache-Control", "public, max-age=86400"),
                    *SECURITY_HEADERS,
                ]
                start_response(STATUS_TEXT[200], headers)
                return [] if method == "HEAD" else [body]

        if re.fullmatch(r"/google[0-9a-f]+\.html", path):
            verify_file = BASE_DIR / path.lstrip("/")
            if verify_file.is_file():
                body = verify_file.read_bytes()
                headers = [
                    ("Content-Type", "text/html; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                    *SECURITY_HEADERS,
                ]
                start_response(STATUS_TEXT[200], headers)
                return [] if method == "HEAD" else [body]

        if path == "/BingSiteAuth.xml":
            bing_file = BASE_DIR / "BingSiteAuth.xml"
            if bing_file.is_file():
                body = bing_file.read_bytes()
                headers = [
                    ("Content-Type", "application/xml; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                    *SECURITY_HEADERS,
                ]
                start_response(STATUS_TEXT[200], headers)
                return [] if method == "HEAD" else [body]

        import scraper as _scraper
        indexnow_key = _scraper.get_indexnow_key()
        if path == f"/{indexnow_key}.txt":
            body = indexnow_key.encode("utf-8")
            headers = [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(body))),
                *SECURITY_HEADERS,
            ]
            start_response(STATUS_TEXT[200], headers)
            return [] if method == "HEAD" else [body]

        if path == "/api/opportunities":
            if _is_rate_limited(_get_client_ip(environ), "api", _API_RATE_LIMIT):
                status = 429
                payload = {"ok": False, "error": "Rate limit exceeded"}
            else:
                items, _url, _handle, _tools = _load_board_data()
                qs = parse_qs(str(environ.get("QUERY_STRING", "")))
                q_val = (qs.get("q") or [""])[0].strip().lower()
                cat_val = (qs.get("cat") or [""])[0].strip()
                badge_val = (qs.get("badge") or [""])[0].strip().lower()
                if cat_val and cat_val != "all":
                    items = [i for i in items if i.category == cat_val]
                if badge_val:
                    items = [i for i in items if any(badge_val in b.lower() for b in i.badges)]
                if q_val:
                    terms = q_val.split()
                    items = [
                        i
                        for i in items
                        if all(
                            t
                            in f"{i.title} {i.summary} {i.source_name} {' '.join(i.matched_keywords)} {' '.join(i.badges)}".lower()
                            for t in terms
                        )
                    ]
                total_filtered = len(items)
                limit_raw = (qs.get("limit") or [""])[0].strip()
                page_raw = (qs.get("page") or ["1"])[0].strip()
                if limit_raw.isdigit() and int(limit_raw) > 0:
                    limit_n = min(200, int(limit_raw))
                    page_n = max(1, int(page_raw) if page_raw.isdigit() else 1)
                    start_i = (page_n - 1) * limit_n
                    items = items[start_i : start_i + limit_n]
                status = 200
                payload: dict[str, Any] = {
                    "ok": True,
                    "count": total_filtered,
                    "items": [item.to_dict() for item in items],
                }
        else:
            status = 404
            payload = {"ok": False, "error": "Not found"}
    elif method == "POST":
        if _is_rate_limited(_get_client_ip(environ), "webhook", _WEBHOOK_RATE_LIMIT):
            status, payload = 429, {"ok": False, "error": "Rate limit exceeded"}
        else:
            try:
                length = int(environ.get("CONTENT_LENGTH") or 0)
            except (TypeError, ValueError):
                length = -1
            if length < 0:
                status, payload = 400, {"ok": False, "error": "Invalid Content-Length"}
            elif length > MAX_WEBHOOK_BYTES:
                status, payload = 413, {"ok": False, "error": "Payload too large"}
            else:
                wsgi_input = environ.get("wsgi.input")
                raw_body = wsgi_input.read(length) if (wsgi_input and length > 0) else b"{}"
                secret_header = str(environ.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN", ""))
                status, payload = handle_webhook_request(raw_body, secret_header=secret_header)
    else:
        status = 405
        payload = {"ok": False, "error": f"Method {method} not allowed"}

    body = json.dumps(payload).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        *SECURITY_HEADERS,
    ]
    if status == 429:
        headers.append(("Retry-After", str(int(_RATE_WINDOW_SECONDS))))
    start_response(STATUS_TEXT.get(status, f"{status} Error"), headers)
    return [] if method == "HEAD" else [body]
