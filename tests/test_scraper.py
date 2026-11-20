import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

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

    def test_seen_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seen.json"
            scraper.save_seen_items(path, {"id1": "2026-11-19T00:00:00+00:00"})
            loaded, existed = scraper.load_seen_items(path)
            self.assertTrue(existed)
            self.assertEqual(loaded, {"id1": "2026-11-19T00:00:00+00:00"})


if __name__ == "__main__":
    unittest.main()
