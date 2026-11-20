"""Vercel Python WSGI webhook for instant 24/7 Telegram bot replies."""

from __future__ import annotations

import json
import logging
import os
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


def app(
    environ: dict[str, Any],
    start_response: Callable[[str, list[tuple[str, str]]], Any],
) -> Iterable[bytes]:
    """Standard WSGI entrypoint for Vercel Python Runtime."""
    method = str(environ.get("REQUEST_METHOD", "GET")).upper()

    if method in {"GET", "HEAD"}:
        status = 200
        payload: dict[str, Any] = {
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
