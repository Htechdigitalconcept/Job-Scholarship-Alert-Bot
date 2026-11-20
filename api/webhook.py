"""Vercel Python serverless webhook for instant 24/7 Telegram bot replies."""

from __future__ import annotations

import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import bot_commands  # noqa: E402

logger = logging.getLogger(__name__)


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


class handler(BaseHTTPRequestHandler):
    """Vercel Serverless Function entrypoint."""

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._send_json(
            200,
            {"ok": True, "service": "Job & Scholarship Alert Bot Webhook"},
        )

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw_body = self.rfile.read(length) if length > 0 else b"{}"
        secret_header = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        status, payload = handle_webhook_request(raw_body, secret_header=secret_header)
        self._send_json(status, payload)
