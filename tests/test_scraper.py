import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import scraper


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Junior Python Backend Engineer (Remote)</title>
      <link>https://example.com/jobs/1</link>
      <description><![CDATA[<p>Work with Python and APIs remotely.</p>]]></description>
      <pubDate>Thu, 19 Nov 2026 08:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Senior Only Java Architect</title>
      <link>https://example.com/jobs/2</link>
      <description>Requires 10+ years experience.</description>
    </item>
  </channel>
</rss>
"""

SAMPLE_HTML = """
<html>
  <body>
    <article class="job-card">
      <h2><a href="/scholarships/stem-africa">Fully Funded STEM Masters Scholarship</a></h2>
      <p class="summary">Open to applicants from Nigeria and across Africa.</p>
    </article>
  </body>
</html>
"""


class ScraperTests(unittest.TestCase):
    def test_match_keywords_include_and_exclude(self) -> None:
        matched = scraper.match_keywords(
            "Junior Python Backend Role",
            include_keywords=["python", "remote"],
            exclude_keywords=["senior only"],
        )
        self.assertEqual(matched, ["python"])

        blocked = scraper.match_keywords(
            "Senior Only Python Engineer",
            include_keywords=["python"],
            exclude_keywords=["senior only"],
        )
        self.assertEqual(blocked, [])

    def test_match_keywords_require_keywords(self) -> None:
        on_site = scraper.match_keywords(
            "Solidity Engineer based in New York",
            include_keywords=["solidity"],
            exclude_keywords=[],
            require_keywords=["remote", "remotely"],
        )
        self.assertEqual(on_site, [])

        remote = scraper.match_keywords(
            "Solidity Engineer - 100% Remote",
            include_keywords=["solidity"],
            exclude_keywords=[],
            require_keywords=["remote", "remotely"],
        )
        self.assertEqual(remote, ["solidity"])

    def test_match_keywords_avoids_partial_word_false_positives(self) -> None:
        # 'intern' should not match 'international'
        matched = scraper.match_keywords(
            "International Relations Officer",
            include_keywords=["intern"],
            exclude_keywords=[],
        )
        self.assertEqual(matched, [])

    @patch("scraper.fetch_url", return_value=SAMPLE_RSS)
    def test_parse_rss_source(self, _mock_fetch) -> None:
        items = scraper.parse_rss_source(
            source={"name": "Test RSS", "url": "https://example.com/rss"},
            category_key="jobs",
            category_label="💼 Job Alert",
            include_kw=["python", "remote"],
            exclude_kw=["senior only"],
            timeout=10,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Junior Python Backend Engineer (Remote)")
        self.assertEqual(items[0].matched_keywords, ["python", "remote"])

    @patch("scraper.fetch_url", return_value=SAMPLE_RSS)
    def test_parse_rss_source_filters_old_posts(self, _mock_fetch) -> None:
        old_now = datetime(2026, 11, 30, 12, 0, tzinfo=timezone.utc)
        items = scraper.parse_rss_source(
            source={"name": "Test RSS", "url": "https://example.com/rss"},
            category_key="jobs",
            category_label="💼 Job Alert",
            include_kw=["python", "remote"],
            exclude_kw=["senior only"],
            timeout=10,
            max_age_days=3,
            now=old_now,
        )
        self.assertEqual(items, [])

    def test_is_recent_post(self) -> None:
        now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(scraper.is_recent_post(now - timedelta(days=1), max_age_days=3, now=now))
        self.assertFalse(scraper.is_recent_post(now - timedelta(days=5), max_age_days=3, now=now))
        self.assertTrue(scraper.is_recent_post(None, max_age_days=3, allow_undated=True, now=now))
        self.assertFalse(scraper.is_recent_post(None, max_age_days=3, allow_undated=False, now=now))

    @patch("scraper.fetch_url", return_value=SAMPLE_HTML)
    def test_parse_html_source(self, _mock_fetch) -> None:
        items = scraper.parse_html_source(
            source={
                "name": "Test HTML",
                "url": "https://example.com/list",
                "item_selector": "article.job-card",
                "title_selector": "h2 a",
                "link_selector": "h2 a",
                "summary_selector": "p.summary",
            },
            category_key="scholarships",
            category_label="🎓 Scholarship",
            include_kw=["fully funded", "nigeria"],
            exclude_kw=[],
            timeout=10,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].link, "https://example.com/scholarships/stem-africa")
        self.assertEqual(items[0].matched_keywords, ["fully funded", "nigeria"])

    def test_prune_seen_items(self) -> None:
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=120)).isoformat()
        recent = (now - timedelta(days=5)).isoformat()
        pruned = scraper.prune_seen_items({"old": old, "recent": recent}, retention_days=90)
        self.assertNotIn("old", pruned)
        self.assertIn("recent", pruned)

    def test_format_telegram_message_escapes_html(self) -> None:
        opp = scraper.Opportunity(
            item_id="abc123",
            category="jobs",
            category_label="💼 Job Alert",
            source_name="Feed <1>",
            title="Python & Data <Intern>",
            link="https://example.com/?a=1&b=2",
            summary="Great <script>alert(1)</script> role",
            matched_keywords=["python", "intern"],
        )
        msg = scraper.format_telegram_message(opp)
        self.assertIn("&lt;Intern&gt;", msg)
        self.assertNotIn("<script>", msg)
        self.assertIn("https://example.com/?a=1&amp;b=2", msg)

    def test_interleave_by_category(self) -> None:
        t_old = datetime(2026, 11, 17, tzinfo=timezone.utc)
        t_new = datetime(2026, 11, 19, tzinfo=timezone.utc)
        j1 = scraper.Opportunity("1", "jobs", "J", "S", "J1", "u1", "", ["python"], published_dt=t_old)
        j2 = scraper.Opportunity("2", "jobs", "J", "S", "J2", "u2", "", ["python"], published_dt=t_new)
        s1 = scraper.Opportunity("3", "scholarships", "Sc", "S", "S1", "u3", "", ["stem"], published_dt=t_new)
        ordered = scraper.interleave_by_category([j1, j2, s1])
        self.assertEqual([o.item_id for o in ordered], ["2", "3", "1"])

    def test_extract_badges_and_deadline(self) -> None:
        text = (
            "Junior Python Backend Intern (Work from anywhere, Worldwide). "
            "Visa sponsorship available. Fully funded fellowship. Deadline: December 15, 2026."
        )
        badges = scraper.extract_badges(text)
        self.assertIn("🌍 Worldwide", badges)
        self.assertIn("🛂 Visa Sponsored", badges)
        self.assertIn("💰 Fully Funded", badges)
        self.assertIn("🟢 Entry / Intern", badges)
        self.assertEqual(scraper.extract_deadline(text), "December 15, 2026")

    def test_parse_himalayas_and_arbeitnow_sources(self) -> None:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        him_json = json.dumps({
            "jobs": [{
                "title": "Backend Engineer",
                "companyName": "Acme",
                "applicationLink": "https://himalayas.app/jobs/1",
                "excerpt": "Python backend role.",
                "locationRestrictions": [],
                "seniority": ["Mid"],
                "pubDate": now_ts,
            }]
        })
        arb_json = json.dumps({
            "data": [{
                "title": "Python Developer",
                "company_name": "BerlinCo",
                "url": "https://arbeitnow.com/jobs/1",
                "description": "Remote Python role with visa sponsorship.",
                "tags": ["Remote", "Visa Sponsorship"],
                "remote": True,
                "created_at": now_ts,
            }]
        })
        with patch("scraper.fetch_url", return_value=him_json):
            him = scraper.parse_himalayas_source(
                {"name": "Himalayas", "url": "https://himalayas.app/jobs/api"},
                "jobs", "💼 Job Alert", ["python"], [], 10, max_age_days=3,
            )
        self.assertEqual(len(him), 1)
        self.assertIn("🌍 Worldwide", him[0].badges)

        with patch("scraper.fetch_url", return_value=arb_json):
            arb = scraper.parse_arbeitnow_source(
                {"name": "Arbeitnow", "url": "https://www.arbeitnow.com/api/job-board-api"},
                "jobs", "💼 Job Alert", ["python"], [], 10, max_age_days=3,
            )
        self.assertEqual(len(arb), 1)
        self.assertIn("🛂 Visa Sponsored", arb[0].badges)

    def test_save_latest_items_balances_categories(self) -> None:
        now = datetime.now(timezone.utc)
        many_jobs = [
            scraper.Opportunity(f"j{i}", "jobs", "J", "WWR", f"Job {i}", f"https://ex.com/j{i}", "", ["remote"], published_dt=now)
            for i in range(10)
        ]
        one_web3 = scraper.Opportunity("w1", "web3_jobs", "W3", "CCJ", "Web3 Role", "https://ex.com/w1", "", ["web3"], published_dt=now - timedelta(hours=5))
        one_sch = scraper.Opportunity("s1", "scholarships", "Sc", "OD", "Scholarship", "https://ex.com/s1", "", ["africa"], published_dt=now - timedelta(hours=5))
        cfg = {"settings": {"max_post_age_days": 3, "allow_undated_posts": True}, "categories": {}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "latest.json"
            saved = scraper.save_latest_items(path, [*many_jobs, one_web3, one_sch], cfg, limit=5)
            cats = {item.category for item in saved}
            self.assertEqual(cats, {"jobs", "web3_jobs", "scholarships"})

    def test_duplicate_title_deduplication(self) -> None:
        now = datetime.now(timezone.utc)
        a = scraper.Opportunity("id_1", "jobs", "J", "WWR", "Dropbox: Backend Engineer", "https://ex.com/1", "", ["backend"], published_dt=now)
        b = scraper.Opportunity("id_2", "jobs", "J", "Himalayas", "Dropbox — Backend Engineer!", "https://ex.com/2", "", ["backend"], published_dt=now)
        self.assertEqual(scraper.make_title_id(a.title), scraper.make_title_id(b.title))
        cfg = {"settings": {"max_post_age_days": 3, "allow_undated_posts": True}, "categories": {}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "latest.json"
            saved = scraper.save_latest_items(path, [a, b], cfg, limit=10)
            self.assertEqual(len(saved), 1)

    def test_seen_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seen.json"
            scraper.save_seen_items(path, {"id1": "2026-11-19T00:00:00+00:00"})
            loaded, existed = scraper.load_seen_items(path)
            self.assertTrue(existed)
            self.assertEqual(loaded, {"id1": "2026-11-19T00:00:00+00:00"})

    def test_cycle_reminder_and_subscriber_dm(self) -> None:
        now = datetime.now(timezone.utc)
        items = [
            scraper.Opportunity(
                "j1", "jobs", "💼 Job Alert", "WWR", "Python API Dev", "https://ex.com/j1",
                "Remote worldwide", ["python"], published_dt=now, badges=["🌍 Worldwide"],
            ),
            scraper.Opportunity(
                "s1", "scholarships", "🎓 Scholarship & Fellowship", "OD", "STEM Award", "https://ex.com/s1",
                "Fully funded", ["fully funded"], published_dt=now, badges=["💰 Fully Funded"],
            ),
        ]
        msg = scraper.format_cycle_reminder(
            items,
            channel_tag="@latestjobsandscholarship",
            site_url="https://job-scholarship-alert-bot-chi.vercel.app",
        )
        self.assertIn("New Cycle Update", msg)
        self.assertIn("1 Job", msg)
        self.assertIn("1 Scholarship", msg)
        self.assertIn("Python API Dev", msg)

        with tempfile.TemporaryDirectory() as tmp:
            subs_path = Path(tmp) / "subscribers.json"
            scraper.save_subscribers(subs_path, {
                "111": {"subscribed": True, "keywords": []},
                "222": {"subscribed": True, "keywords": ["solidity"]},
                "333": {"subscribed": False, "keywords": []},
            })
            with patch("scraper.send_telegram_message") as mock_send:
                sent = scraper.send_subscriber_alerts(
                    "tok",
                    items,
                    subs_path,
                    "@latestjobsandscholarship",
                    channel_url="https://t.me/latestjobsandscholarship",
                    channel_tag="@latestjobsandscholarship",
                    site_url="https://job-scholarship-alert-bot-chi.vercel.app",
                )
            self.assertEqual(sent, 1)
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            self.assertEqual(args[1], "111")
            self.assertIn("New Cycle Alert", args[2])
            self.assertIn("#RemoteJobs", args[2])
            self.assertEqual(kwargs["reply_markup"]["inline_keyboard"][1][0]["callback_data"], "sub:off")

        tags = scraper.build_telegram_hashtags(items[0])
        self.assertIn("#RemoteJobs", tags)
        self.assertIn("#WorldwideRemote", tags)

        markup = scraper.build_item_reply_markup(
            items[0],
            channel_url="https://t.me/latestjobsandscholarship",
            bot_url="https://t.me/JobAlertSampleBot",
        )
        btn_texts = [b["text"] for b in markup["inline_keyboard"][0]]
        self.assertEqual(btn_texts, ["Apply Now 🔗", "Filter in Bot 🤖"])
        self.assertEqual(
            markup["inline_keyboard"][0][1]["url"],
            "https://t.me/JobAlertSampleBot?start=latest",
        )
        self.assertEqual(markup["inline_keyboard"][1][0]["text"], "📤 Share Opportunity")
        self.assertIn("https://t.me/share/url?", markup["inline_keyboard"][1][0]["url"])

        cycle_markup = scraper.build_cycle_reminder_markup(
            channel_url="https://t.me/latestjobsandscholarship",
            site_url="https://job-scholarship-alert-bot-chi.vercel.app",
            bot_url="https://t.me/JobAlertSampleBot",
            include_unsubscribe=False,
        )
        cycle_btns = [b["text"] for b in cycle_markup["inline_keyboard"][0]]
        self.assertEqual(cycle_btns, ["🌐 Live Web Board", "Filter in Bot 🤖"])
        self.assertEqual(cycle_markup["inline_keyboard"][1][0]["text"], "📤 Share Bot with a Friend")

    def test_ping_indexnow_posts_valid_payload(self) -> None:
        mock_resp = Mock(status_code=202)
        with patch("scraper.requests.post", return_value=mock_resp) as post_mock:
            ok = scraper.ping_indexnow(
                "https://job-scholarship-alert-bot-chi.vercel.app",
                [
                    "https://job-scholarship-alert-bot-chi.vercel.app/",
                    "https://job-scholarship-alert-bot-chi.vercel.app/feed.xml",
                    "https://evil.example.com/ignored",
                ],
                key="e4c9a8d2f1b740369c5d8e2a1f7b3094",
            )
            self.assertTrue(ok)
            _, kwargs = post_mock.call_args
            sent = kwargs["json"]
            self.assertEqual(sent["host"], "job-scholarship-alert-bot-chi.vercel.app")
            self.assertEqual(sent["key"], "e4c9a8d2f1b740369c5d8e2a1f7b3094")
            self.assertEqual(
                sent["keyLocation"],
                "https://job-scholarship-alert-bot-chi.vercel.app/e4c9a8d2f1b740369c5d8e2a1f7b3094.txt",
            )
            self.assertEqual(
                sent["urlList"],
                [
                    "https://job-scholarship-alert-bot-chi.vercel.app/",
                    "https://job-scholarship-alert-bot-chi.vercel.app/feed.xml",
                ],
            )


if __name__ == "__main__":
    unittest.main()
