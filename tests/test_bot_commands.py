import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import bot_commands
import scraper
from api import webhook


def make_sample_config() -> dict:
    return {
        "settings": {
            "max_alerts_per_run": 15,
            "latest_cache_limit": 20,
            "max_post_age_days": 3,
            "allow_undated_posts": True,
        },
        "categories": {
            "jobs": {
                "label": "💼 Job Alert",
                "max_post_age_days": 3,
                "include_keywords": ["python", "backend"],
                "exclude_keywords": ["senior only"],
                "sources": [{"name": "We Work Remotely", "type": "rss", "url": "https://example.com/jobs.rss", "enabled": True}],
            },
            "web3_jobs": {
                "label": "⛓️ Web3 Remote Job",
                "max_post_age_days": 3,
                "require_keywords": ["remote"],
                "include_keywords": ["solidity", "zk"],
                "exclude_keywords": [],
                "sources": [{"name": "Cryptocurrency Jobs", "type": "rss", "url": "https://example.com/web3.xml", "enabled": True}],
            },
            "scholarships": {
                "label": "🎓 Scholarship & Fellowship",
                "max_post_age_days": 7,
                "include_keywords": ["fully funded", "africa"],
                "exclude_keywords": [],
                "sources": [{"name": "Opportunity Desk", "type": "rss", "url": "https://example.com/sch.rss", "enabled": True}],
            },
        },
    }


class BotCommandsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.latest_path = self.root / "latest_items.json"
        self.subs_path = self.root / "subscribers.json"
        self.state_path = self.root / "bot_state.json"
        self.config = make_sample_config()

        now = datetime.now(timezone.utc)
        items = [
            scraper.Opportunity(
                item_id="j1",
                category="jobs",
                category_label="💼 Job Alert",
                source_name="WWR",
                title="Python Backend Engineer",
                link="https://example.com/j1",
                summary="Build APIs in Python",
                matched_keywords=["python", "backend"],
                published="Today",
                published_dt=now,
            ),
            scraper.Opportunity(
                item_id="w1",
                category="web3_jobs",
                category_label="⛓️ Web3 Remote Job",
                source_name="Cryptocurrency Jobs",
                title="Solidity Protocol Engineer",
                link="https://example.com/w1",
                summary="100% remote Web3 smart contract role",
                matched_keywords=["solidity"],
                published="Today",
                published_dt=now,
            ),
            scraper.Opportunity(
                item_id="s1",
                category="scholarships",
                category_label="🎓 Scholarship & Fellowship",
                source_name="Opportunity Desk",
                title="Fully Funded Africa STEM Fellowship",
                link="https://example.com/s1",
                summary="Open to African students",
                matched_keywords=["fully funded", "africa"],
                published="Today",
                published_dt=now,
            ),
        ]
        scraper.save_latest_items(self.latest_path, items, self.config)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_start_and_keywords_and_sources(self) -> None:
        self.config["settings"]["channel_id"] = "@latestjobsandscholarship"
        self.config["settings"]["public_channel_url"] = "https://t.me/latestjobsandscholarship"
        self.assertEqual(scraper.get_broadcast_target(self.config), "@latestjobsandscholarship")

        start_reply = bot_commands.handle_command("123", "/start", self.config, self.latest_path, self.subs_path)
        self.assertIn("/latest", start_reply[0])
        self.assertIn("https://t.me/latestjobsandscholarship", start_reply[0])

        kw_reply = bot_commands.handle_command("123", "/keywords", self.config, self.latest_path, self.subs_path)
        self.assertIn("python, backend", kw_reply[0])

        src_reply = bot_commands.handle_command("123", "/sources", self.config, self.latest_path, self.subs_path)
        self.assertIn("We Work Remotely", src_reply[0])
        self.assertIn("Opportunity Desk", src_reply[0])

    def test_latest_jobs_and_scholarships_commands(self) -> None:
        latest = bot_commands.handle_command("123", "/latest", self.config, self.latest_path, self.subs_path)
        self.assertIn("Python Backend Engineer", latest[0])
        self.assertIn("Fully Funded Africa STEM Fellowship", latest[0])

        jobs = bot_commands.handle_command("123", "/jobs python", self.config, self.latest_path, self.subs_path)
        self.assertIn("Python Backend Engineer", jobs[0])
        self.assertNotIn("STEM Fellowship", jobs[0])

        web3 = bot_commands.handle_command("123", "/web3 solidity", self.config, self.latest_path, self.subs_path)
        self.assertIn("Solidity Protocol Engineer", web3[0])
        self.assertNotIn("Python Backend Engineer", web3[0])

        sch = bot_commands.handle_command("123", "/scholarships@MyTestBot africa", self.config, self.latest_path, self.subs_path)
        self.assertIn("Fully Funded Africa STEM Fellowship", sch[0])

    def test_setkeywords_subscribe_and_unsubscribe(self) -> None:
        set_reply = bot_commands.handle_command(
            "999", "/setkeywords python, remote", self.config, self.latest_path, self.subs_path
        )
        self.assertIn("saved", set_reply[0].lower())
        subs = json.loads(self.subs_path.read_text(encoding="utf-8"))
        self.assertTrue(subs["999"]["subscribed"])
        self.assertEqual(subs["999"]["keywords"], ["python", "remote"])

        unsub = bot_commands.handle_command(
            "999", "/unsubscribe", self.config, self.latest_path, self.subs_path
        )
        self.assertIn("paused", unsub[0].lower())
        subs = json.loads(self.subs_path.read_text(encoding="utf-8"))
        self.assertFalse(subs["999"]["subscribed"])

    @patch("bot_commands.get_updates")
    @patch("scraper.send_telegram_message")
    @patch("scraper.load_config")
    def test_process_updates_once_advances_offset(
        self, mock_cfg, mock_send, mock_updates
    ) -> None:
        mock_cfg.return_value = self.config
        mock_updates.return_value = [
            {
                "update_id": 500,
                "message": {
                    "chat": {"id": 42},
                    "text": "/keywords",
                },
            }
        ]
        sent = bot_commands.process_updates_once(
            bot_token="fake-token",
            config_path=self.root / "config.yaml",
            latest_path=self.latest_path,
            state_path=self.state_path,
            subscribers_path=self.subs_path,
        )
        self.assertEqual(sent, 1)
        mock_send.assert_called_once()
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["last_update_id"], 500)

    @patch("bot_commands.requests.get")
    def test_get_updates_skips_gracefully_on_409_webhook_conflict(self, mock_get) -> None:
        resp = MagicMock()
        resp.status_code = 409
        mock_get.return_value = resp
        self.assertEqual(bot_commands.get_updates("fake-token", offset=1), [])

    @patch("scraper.send_telegram_message")
    def test_vercel_webhook_handler_processes_command_and_checks_secret(self, mock_send) -> None:
        payload = json.dumps({
            "update_id": 777,
            "message": {"chat": {"id": 42}, "text": "/web3"},
        }).encode("utf-8")

        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_WEBHOOK_SECRET": "sec"}):
            code_bad, _ = webhook.handle_webhook_request(payload, secret_header="wrong")
            self.assertEqual(code_bad, 403)
            mock_send.assert_not_called()

            code_ok, body_ok = webhook.handle_webhook_request(payload, secret_header="sec")
            self.assertEqual(code_ok, 200)
            self.assertTrue(body_ok["ok"])
            self.assertEqual(body_ok["handled"], 1)
            mock_send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
