"""Vercel Python WSGI entrypoint: Telegram Webhook, Live Web Board & SEO/AI endpoints."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

logger = logging.getLogger(__name__)

STATUS_TEXT = {
    200: "200 OK",
    400: "400 Bad Request",
    403: "403 Forbidden",
    405: "405 Method Not Allowed",
    500: "500 Internal Server Error",
}


def handle_webhook_request(
    raw_body: bytes,
    secret_header: str = "",
) -> tuple[int, dict[str, Any]]:
    """Process a raw webhook POST payload and return (status_code, json_body)."""
    expected_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if expected_secret and secret_header != expected_secret:
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
        logger.exception("Webhook error: %s", exc)
        return 200, {"ok": False, "error": str(exc)}


def _detect_site_url(environ: dict[str, Any]) -> str:
    env_url = os.environ.get("PUBLIC_SITE_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")
    host = str(environ.get("HTTP_X_FORWARDED_HOST") or environ.get("HTTP_HOST") or "").strip()
    if host:
        proto = str(environ.get("HTTP_X_FORWARDED_PROTO") or "https").strip()
        return f"{proto}://{host}".rstrip("/")
    return "https://job-scholarship-alert-bot-chi.vercel.app"


def _load_board_data() -> tuple[list[Any], str, str]:
    import bot_commands
    import scraper

    config = scraper.load_config(BASE_DIR / "config.yaml")
    items = bot_commands.get_recent_opportunities(config, BASE_DIR / "data" / "latest_items.json")
    channel_url = scraper.get_public_channel_url(config) or "https://t.me/latestjobsandscholarship"
    channel_handle = str(config.get("settings", {}).get("channel_id", "@latestjobsandscholarship")).strip()
    return items, channel_url, channel_handle


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

            items, channel_url, channel_handle = _load_board_data()
            html_doc = web_board.render_web_board_html(
                items,
                channel_url=channel_url,
                channel_handle=channel_handle,
                site_url=site_url,
            )
            body = html_doc.encode("utf-8")
            headers = [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("X-Robots-Tag", "index, follow"),
            ]
            start_response(STATUS_TEXT[200], headers)
            return [] if method == "HEAD" else [body]

        if path == "/robots.txt":
            import web_board

            body = web_board.render_robots_txt(site_url).encode("utf-8")
            headers = [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ]
            start_response(STATUS_TEXT[200], headers)
            return [] if method == "HEAD" else [body]

        if path == "/sitemap.xml":
            import web_board

            items, _url, _handle = _load_board_data()
            body = web_board.render_sitemap_xml(site_url, items).encode("utf-8")
            headers = [
                ("Content-Type", "application/xml; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ]
            start_response(STATUS_TEXT[200], headers)
            return [] if method == "HEAD" else [body]

        if path == "/llms.txt":
            import web_board

            items, channel_url, channel_handle = _load_board_data()
            body = web_board.render_llms_txt(
                site_url, items, channel_url=channel_url, channel_handle=channel_handle
            ).encode("utf-8")
            headers = [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(body))),
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
                ]
                start_response(STATUS_TEXT[200], headers)
                return [] if method == "HEAD" else [body]

        if path == "/api/opportunities":
            items, _url, _handle = _load_board_data()
            status = 200
            payload: dict[str, Any] = {
                "ok": True,
                "count": len(items),
                "items": [item.to_dict() for item in items],
            }
        else:
            status = 200
            payload = {
                "ok": True,
                "service": "Job & Scholarship Alert Bot Webhook",
            }
    elif method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            length = 0
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
    ]
    start_response(STATUS_TEXT.get(status, f"{status} Error"), headers)
    return [] if method == "HEAD" else [body]
