"""Self-contained SEO + AI-Search-ready HTML renderer for the live Web Board."""

from __future__ import annotations

import base64
import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import scraper

DEFAULT_SITE_URL = "https://job-scholarship-alert-bot-chi.vercel.app"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def _load_logo_data_uri() -> str:
    """Return an inline data URI for the navbar/footer logo icon, or '/logo.png' fallback."""
    icon_path = ASSETS_DIR / "logo-icon.png"
    if icon_path.is_file():
        encoded = base64.b64encode(icon_path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    return "/logo.png"


def _strip_tz_suffix(published: str) -> str:
    return re.sub(r"\s*(?:[+-]\d{4}|GMT|UTC)$", "", published).strip()


def _render_ssr_cards(items: list[scraper.Opportunity]) -> str:
    """Server-side render opportunity cards so Google & AI bots index all content."""
    if not items:
        return (
            '<div class="empty">No recent opportunities cached right now. '
            "Check back soon or join the Telegram channel.</div>"
        )

    cards: list[str] = []
    for item in items:
        badges_html = "".join(
            f'<span class="badge">{html.escape(b)}</span>' for b in item.badges
        )
        deadline_html = (
            f'<div class="deadline">⏳ Deadline: {html.escape(item.deadline)}</div>'
            if item.deadline
            else ""
        )
        summary_html = (
            f'<p class="summary">{html.escape(item.summary)}</p>'
            if item.summary
            else ""
        )
        short_date = html.escape(_strip_tz_suffix(item.published)) if item.published else ""
        kws = html.escape(", ".join(item.matched_keywords))
        date_prefix = f"{short_date} · " if short_date else ""
        safe_link = html.escape(scraper.sanitize_http_url(item.link, fallback="#"), quote=True)
        cards.append(
            f"""<article class="card">
  <div class="card-top">
    <span class="cat-tag">{html.escape(item.category_label)}</span>
    <span>{html.escape(item.source_name)}</span>
  </div>
  <h2><a href="{safe_link}" target="_blank" rel="noopener noreferrer">{html.escape(item.title)}</a></h2>
  {f'<div class="badges">{badges_html}</div>' if badges_html else ''}
  {deadline_html}
  {summary_html}
  <div class="card-footer">
    <span class="kw-list">{date_prefix}🏷 {kws}</span>
    <div class="card-actions">
      <button type="button" class="pitch-btn" data-pitch-id="{html.escape(item.item_id, quote=True)}">📝 Pitch</button>
      <a class="apply-btn" href="{safe_link}" target="_blank" rel="noopener noreferrer">Apply ↗</a>
    </div>
  </div>
</article>"""
        )
    return "\n".join(cards)


def _infer_applicant_location_requirements(item: scraper.Opportunity) -> list[dict[str, str]]:
    """Infer valid Schema.org Country entries for remote JobPosting markup."""
    blob = f"{item.title} {item.summary}".lower()
    country_rules = [
        (r"\b(?:usa|u\.s\.a\.|united states|us remote|remote us|north america)\b", "USA"),
        (r"\b(?:uk|u\.k\.|united kingdom|london|england)\b", "United Kingdom"),
        (r"\b(?:germany|deutschland|berlin|munich|\(w/m/d\)|\(m/w/d\))\b", "Germany"),
        (r"\b(?:canada|toronto|vancouver)\b", "Canada"),
        (r"\b(?:australia|sydney|melbourne)\b", "Australia"),
        (r"\b(?:nigeria|lagos|abuja)\b", "Nigeria"),
        (r"\b(?:india|bangalore|bengaluru)\b", "India"),
        (r"\b(?:france|paris)\b", "France"),
        (r"\b(?:netherlands|amsterdam)\b", "Netherlands"),
    ]
    matched: list[str] = []
    for pattern, country in country_rules:
        if re.search(pattern, blob) and country not in matched:
            matched.append(country)
    if not matched and re.search(r"\b(?:europe|eu|emea)\b", blob):
        matched = ["Germany", "United Kingdom", "France", "Netherlands"]
    if not matched and re.search(r"\b(?:apac|asia)\b", blob):
        matched = ["Singapore", "Australia", "India", "Japan"]
    if not matched:
        matched = ["USA", "United Kingdom", "Canada", "Germany", "Nigeria"]
    return [{"@type": "Country", "name": c} for c in matched]


def _infer_employment_type(item: scraper.Opportunity) -> str:
    blob = f"{item.title} {item.summary} {' '.join(item.badges)}".lower()
    if re.search(r"\b(?:intern|internship)\b", blob):
        return "INTERN"
    if re.search(r"\b(?:contractor|contract|freelance)\b", blob):
        return "CONTRACTOR"
    if re.search(r"\b(?:part[- ]?time)\b", blob):
        return "PART_TIME"
    return "FULL_TIME"


def _infer_valid_through(item: scraper.Opportunity) -> str:
    base_dt = item.published_dt or datetime.now(timezone.utc)
    if item.deadline:
        for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
            try:
                return datetime.strptime(item.deadline.strip(), fmt).date().isoformat()
            except ValueError:
                continue
    return (base_dt + timedelta(days=30)).date().isoformat()


def build_structured_data(
    site_url: str,
    items: list[scraper.Opportunity],
    channel_url: str = "https://t.me/latestjobsandscholarship",
) -> dict[str, Any]:
    """Build Schema.org JSON-LD graph for Google Search & AI Search engines."""
    clean_url = site_url.rstrip("/")
    list_elements: list[dict[str, Any]] = []
    for idx, item in enumerate(items[:25], start=1):
        safe_item_url = scraper.sanitize_http_url(item.link, fallback=f"{clean_url}/")
        if item.category in {"jobs", "web3_jobs"}:
            node: dict[str, Any] = {
                "@type": "JobPosting",
                "title": item.title,
                "url": safe_item_url,
                "description": item.summary or item.title,
                "datePosted": (item.published_dt or datetime.now(timezone.utc)).date().isoformat(),
                "validThrough": _infer_valid_through(item),
                "employmentType": _infer_employment_type(item),
                "hiringOrganization": {
                    "@type": "Organization",
                    "name": item.source_name,
                },
                "jobLocationType": "TELECOMMUTE",
                "applicantLocationRequirements": _infer_applicant_location_requirements(item),
            }
        else:
            node = {
                "@type": "CreativeWork",
                "name": item.title,
                "url": safe_item_url,
                "description": item.summary or item.title,
                "publisher": {
                    "@type": "Organization",
                    "name": item.source_name,
                },
            }
            if item.published_dt:
                node["datePublished"] = item.published_dt.date().isoformat()
        list_elements.append({"@type": "ListItem", "position": idx, "item": node})

    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "name": "Jobs, Web3 & Scholarships Live Board",
                "url": f"{clean_url}/",
                "logo": f"{clean_url}/logo.png",
                "sameAs": [channel_url] if channel_url else [],
            },
            {
                "@type": "WebSite",
                "name": "Jobs, Web3 & Scholarships Live Board",
                "url": f"{clean_url}/",
                "image": f"{clean_url}/logo.png",
                "description": (
                    "Daily curated remote tech jobs, Web3 remote roles, "
                    "visa-sponsored jobs, and funded international scholarships and fellowships."
                ),
                "potentialAction": {
                    "@type": "SearchAction",
                    "target": f"{clean_url}/?q={{search_term_string}}",
                    "query-input": "required name=search_term_string",
                },
            },
            {
                "@type": "ItemList",
                "name": "Latest Remote Jobs, Web3 Roles & Scholarships",
                "numberOfItems": len(list_elements),
                "itemListElement": list_elements,
            },
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": "How often are remote jobs, Web3 roles, and scholarships updated?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": (
                                "Our automated radar scans 9 verified feeds every 6 hours, "
                                "keeping only recent jobs (up to 3 days old) and scholarships "
                                "(up to 7 days old) while removing cross-source duplicates."
                            ),
                        },
                    },
                    {
                        "@type": "Question",
                        "name": "How can I find worldwide remote or visa-sponsored jobs?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": (
                                "Click the Worldwide or Visa Sponsored filter chips on the Live Web Board, "
                                "or send /worldwide or /visa to our 24/7 Telegram bot."
                            ),
                        },
                    },
                    {
                        "@type": "Question",
                        "name": "How do I get free Telegram alerts when new jobs or scholarships are posted?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": (
                                f"Join {channel_url} on Telegram for 6-hour alerts, cycle update reminders, "
                                "and a daily 06:00 UTC digest, or message the bot with /subscribe."
                            ),
                        },
                    },
                ],
            },
        ],
    }


def render_robots_txt(site_url: str = DEFAULT_SITE_URL) -> str:
    """Generate robots.txt welcoming Google, Bing, and AI Search crawlers."""
    clean_url = site_url.rstrip("/")
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /api/opportunities\n"
        "Allow: /feed.xml\n"
        "Allow: /llms.txt\n"
        "Disallow: /api/webhook\n\n"
        "User-agent: Googlebot\n"
        "Allow: /\n\n"
        "User-agent: Google-Extended\n"
        "Allow: /\n\n"
        "User-agent: OAI-SearchBot\n"
        "Allow: /\n\n"
        "User-agent: GPTBot\n"
        "Allow: /\n\n"
        "User-agent: ChatGPT-User\n"
        "Allow: /\n\n"
        "User-agent: PerplexityBot\n"
        "Allow: /\n\n"
        "User-agent: ClaudeBot\n"
        "Allow: /\n\n"
        f"Sitemap: {clean_url}/sitemap.xml\n"
    )


def render_sitemap_xml(
    site_url: str = DEFAULT_SITE_URL,
    items: list[scraper.Opportunity] | None = None,
) -> str:
    """Generate an XML sitemap for search engines."""
    clean_url = site_url.rstrip("/")
    latest_dt = None
    for item in items or []:
        if item.published_dt and (latest_dt is None or item.published_dt > latest_dt):
            latest_dt = item.published_dt
    lastmod = (latest_dt or datetime.now(timezone.utc)).date().isoformat()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{html.escape(clean_url)}/</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{html.escape(clean_url)}/feed.xml</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>{html.escape(clean_url)}/llms.txt</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>{html.escape(clean_url)}/api/opportunities</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.7</priority>
  </url>
</urlset>
"""


def render_rss_feed(
    site_url: str,
    items: list[scraper.Opportunity],
) -> str:
    """Generate an RSS 2.0 XML feed for aggregators, readers, and search syndication."""
    clean_url = site_url.rstrip("/")
    now_rfc = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    item_blocks: list[str] = []
    for item in items[:40]:
        pub_rfc = (
            item.published_dt.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
            if item.published_dt
            else now_rfc
        )
        safe_orig_link = scraper.sanitize_http_url(item.link)
        item_board_url = f"{clean_url}/?item={item.item_id}"
        desc_parts = [item.category_label, f"Source: {item.source_name}"]
        if item.badges:
            desc_parts.append(" | ".join(item.badges))
        if item.deadline:
            desc_parts.append(f"Deadline: {item.deadline}")
        if item.summary:
            desc_parts.append(item.summary)
        if safe_orig_link:
            desc_parts.append(f"Apply: {safe_orig_link}")
        item_blocks.append(
            f"""    <item>
      <title>{html.escape(item.title)}</title>
      <link>{html.escape(item_board_url)}</link>
      <guid isPermaLink="true">{html.escape(item_board_url)}</guid>
      <category>{html.escape(item.category_label)}</category>
      <pubDate>{pub_rfc}</pubDate>
      <description>{html.escape(" — ".join(desc_parts))}</description>
    </item>"""
        )
    joined_items = "\n".join(item_blocks)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Jobs, Web3 &amp; Scholarships Live Board</title>
    <link>{html.escape(clean_url)}/</link>
    <atom:link href="{html.escape(clean_url)}/feed.xml" rel="self" type="application/rss+xml" />
    <description>Recent remote tech jobs, Web3 remote roles, visa-sponsored openings, and fully funded scholarships updated every 6 hours.</description>
    <language>en-us</language>
    <lastBuildDate>{now_rfc}</lastBuildDate>
{joined_items}
  </channel>
</rss>
"""


def render_llms_txt(
    site_url: str,
    items: list[scraper.Opportunity],
    channel_url: str = "https://t.me/latestjobsandscholarship",
    channel_handle: str = "@latestjobsandscholarship",
) -> str:
    """Generate /llms.txt Markdown index for AI Search engines and LLM agents."""
    clean_url = site_url.rstrip("/")
    lines = [
        "# Jobs, Web3 & Scholarships Live Board",
        "",
        "> Real-time radar for remote tech jobs, Web3 remote roles, visa-sponsored openings, and fully funded international scholarships & fellowships — filtered for freshness (jobs <=3 days, scholarships <=7 days), deduplicated across 9 verified sources, and synced every 6 hours.",
        "",
        f"- Live Web Board: {clean_url}/",
        f"- RSS 2.0 Feed: {clean_url}/feed.xml",
        f"- JSON Feed: {clean_url}/api/opportunities",
        f"- Telegram Channel ({channel_handle}): {channel_url}",
        "",
        "## Interactive Telegram Bot Commands",
        "- `/latest` — 5 newest opportunities with inline pagination",
        "- `/jobs [keyword]` — Filter recent remote software/tech jobs",
        "- `/web3 [keyword]` — Filter recent Web3 & blockchain remote roles",
        "- `/scholarships [keyword]` — Filter recent funded scholarships & fellowships",
        "- `/worldwide` — Filter Worldwide remote roles",
        "- `/visa` — Filter Visa-sponsored roles",
        "- `/digest` — Daily top opportunities summary",
        "",
        "## Recent Opportunities",
        "",
    ]
    for item in items[:30]:
        badge_str = f" [{' | '.join(item.badges)}]" if item.badges else ""
        deadline_str = f" (Deadline: {item.deadline})" if item.deadline else ""
        lines.append(
            f"- [{item.title}]({item.link}) — {item.category_label} via {item.source_name}"
            f"{badge_str}{deadline_str}"
        )
    lines.append("")
    return "\n".join(lines)


DEFAULT_RECOMMENDED_TOOLS: list[dict[str, str]] = [
    {
        "id": "raenest",
        "badge": "💳 Remote USD / EUR / GBP Payouts",
        "name": "Raenest — Global Foreign Bank Accounts",
        "description": "Receive remote tech & Web3 salaries, freelance payouts, or scholarship stipends globally with USD, EUR & GBP accounts.",
        "cta": "Open Free Raenest Account ↗",
        "url": "https://referral.raenest.com/WzbV/i?referral_code=adehab359122",
    }
]


def _render_recommended_tools(tools: list[dict[str, str]]) -> tuple[str, str]:
    """Render (tools_section_html, modal_partner_tip_html) for configured referral tools."""
    if not tools:
        return "", ""
    cards_html = []
    for tool in tools:
        badge = html.escape(tool.get("badge") or "🧰 Recommended Tool")
        name = html.escape(tool.get("name") or "")
        desc = html.escape(tool.get("description") or "")
        cta = html.escape(tool.get("cta") or "Open Tool ↗")
        url = html.escape(tool.get("url") or "#", quote=True)
        cards_html.append(
            f"""        <article class="tool-card">
          <div class="tool-top">
            <span class="tool-badge">{badge}</span>
            <span class="partner-tag">Partner Link</span>
          </div>
          <h3>{name}</h3>
          <p>{desc}</p>
          <a class="tool-cta" href="{url}" target="_blank" rel="noopener noreferrer sponsored">{cta}</a>
        </article>"""
        )

    tools_section = f"""    <section id="tools" class="tools-section" aria-label="Recommended tools for remote workers and fellows">
      <div class="tools-head">
        <div>
          <h2>🧰 Recommended Tools for Global Earners &amp; Fellows</h2>
          <p class="seo-lead" style="margin-bottom:0;">Essential accounts &amp; resources for receiving remote salaries, Web3 payouts, and international stipends.</p>
        </div>
      </div>
      <div class="tools-grid">
{chr(10).join(cards_html)}
      </div>
    </section>"""

    first = tools[0]
    first_url = html.escape(first.get("url") or "#", quote=True)
    first_name = html.escape(first.get("name") or "Raenest")
    modal_tip = (
        f'<div class="modal-partner-tip">'
        f'<span>💳 <strong>Getting paid remotely in USD/EUR/GBP?</strong> Set up a free global payout account via <a href="{first_url}" target="_blank" rel="noopener noreferrer sponsored">{first_name} ↗</a></span>'
        f"</div>"
    )
    return tools_section, modal_tip


def render_web_board_html(
    items: list[scraper.Opportunity],
    channel_url: str = "https://t.me/latestjobsandscholarship",
    channel_handle: str = "@latestjobsandscholarship",
    site_url: str = DEFAULT_SITE_URL,
    recommended_tools: list[dict[str, str]] | None = None,
    focus_item_id: str = "",
) -> str:
    """Render a responsive, SEO + AI-Search-ready web board."""
    clean_site_url = site_url.rstrip("/")
    ordered_items = list(items)
    if focus_item_id:
        for idx, it in enumerate(ordered_items):
            if it.item_id == focus_item_id:
                if idx > 0:
                    ordered_items.insert(0, ordered_items.pop(idx))
                break
    items = ordered_items
    tools_list = DEFAULT_RECOMMENDED_TOOLS if recommended_tools is None else recommended_tools
    tools_section_html, modal_partner_tip_html = _render_recommended_tools(tools_list)
    payload = [item.to_dict() for item in items]
    safe_json = json.dumps(payload).replace("</", "<\\/")
    structured_json = json.dumps(
        build_structured_data(clean_site_url, items, channel_url=channel_url or "https://t.me/latestjobsandscholarship")
    ).replace("</", "<\\/")
    safe_channel_url = html.escape(channel_url or "https://t.me/latestjobsandscholarship", quote=True)
    safe_handle = html.escape(channel_handle or "@latestjobsandscholarship")
    safe_canonical = html.escape(f"{clean_site_url}/", quote=True)
    meta_desc = (
        "Browse up to 200 fresh remote tech jobs, Web3 remote roles, "
        "visa-sponsored openings, and fully funded scholarships & fellowships — with one-tap application pitches."
    )
    safe_desc = html.escape(meta_desc, quote=True)
    ssr_cards = _render_ssr_cards(items[:24])
    total_count = len(items)
    jobs_count = sum(1 for i in items if i.category == "jobs")
    web3_count = sum(1 for i in items if i.category == "web3_jobs")
    scholarships_count = sum(1 for i in items if i.category == "scholarships")
    sources_count = len({i.source_name for i in items if i.source_name}) or 9
    current_year = datetime.now(timezone.utc).year
    logo_src = _load_logo_data_uri()
    safe_logo_url = html.escape(f"{clean_site_url}/logo.png", quote=True)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Remote Tech Jobs, Web3 Roles &amp; Funded Scholarships | Live Board</title>
  <meta name="description" content="{safe_desc}" />
  <meta name="keywords" content="remote tech jobs, web3 remote jobs, solidity developer jobs, visa sponsored remote jobs, worldwide remote work, fully funded scholarships, international fellowships, tech internships" />
  <meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large" />
  <link rel="canonical" href="{safe_canonical}" />
  <link rel="alternate" type="application/rss+xml" title="Jobs, Web3 &amp; Scholarships RSS Feed" href="/feed.xml" />
  <link rel="icon" type="image/png" href="/favicon.png" />
  <link rel="apple-touch-icon" href="/logo.png" />
  <meta property="og:type" content="website" />
  <meta property="og:title" content="Remote Tech Jobs, Web3 Roles &amp; Funded Scholarships | Live Board" />
  <meta property="og:description" content="{safe_desc}" />
  <meta property="og:url" content="{safe_canonical}" />
  <meta property="og:image" content="{safe_logo_url}" />
  <meta property="og:site_name" content="Jobs, Web3 &amp; Scholarships Live Board" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="Remote Tech Jobs, Web3 Roles &amp; Funded Scholarships | Live Board" />
  <meta name="twitter:description" content="{safe_desc}" />
  <meta name="twitter:image" content="{safe_logo_url}" />
  <script type="application/ld+json">{structured_json}</script>
  <script src="https://telegram.org/js/telegram-web-app.js" defer></script>
  <style>
    :root {{
      --bg: #070b14;
      --surface: #0f172a;
      --surface-2: #1e293b;
      --border: #24324a;
      --text: #f8fafc;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --accent-2: #818cf8;
      --green: #34d399;
      --amber: #fbbf24;
    }}
    * {{ box-sizing: border-box; }}
    html {{
      scroll-behavior: smooth;
      overflow-x: clip;
      -webkit-text-size-adjust: 100%;
    }}
    body {{
      margin: 0;
      overflow-x: clip;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
      background:
        radial-gradient(ellipse 80% 50% at 50% -10%, rgba(56, 189, 248, 0.18), transparent),
        radial-gradient(ellipse 60% 40% at 85% 0%, rgba(129, 140, 248, 0.14), transparent),
        var(--bg);
      color: var(--text);
      min-height: 100vh;
      line-height: 1.5;
      display: flex;
      flex-direction: column;
    }}
    .topbar {{
      position: sticky;
      top: 0;
      z-index: 40;
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
      background: rgba(7, 11, 20, 0.78);
      border-bottom: 1px solid rgba(36, 50, 74, 0.8);
    }}
    .topbar-inner {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 12px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
    }}
    .brand {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
      text-decoration: none;
      color: var(--text);
      font-weight: 700;
      font-size: 0.96rem;
      letter-spacing: -0.01em;
    }}
    .brand-title {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .brand-icon {{
      width: 38px;
      height: 38px;
      border-radius: 10px;
      display: grid;
      place-items: center;
      background: #ffffff;
      border: 1px solid rgba(56, 189, 248, 0.45);
      box-shadow: 0 2px 10px rgba(56, 189, 248, 0.22);
      padding: 2px;
      overflow: hidden;
      flex-shrink: 0;
    }}
    .brand-logo {{
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
    }}
    .nav-links {{
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }}
    .nav-link {{
      color: var(--muted);
      text-decoration: none;
      font-size: 0.85rem;
      font-weight: 500;
      padding: 6px 11px;
      border-radius: 8px;
      transition: all 0.15s ease;
    }}
    .nav-link:hover {{
      color: var(--text);
      background: rgba(30, 41, 59, 0.7);
    }}
    .nav-cta {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(56, 189, 248, 0.14);
      border: 1px solid rgba(56, 189, 248, 0.38);
      color: var(--accent);
      text-decoration: none;
      font-size: 0.84rem;
      font-weight: 600;
      padding: 7px 13px;
      border-radius: 9px;
      white-space: nowrap;
      transition: all 0.15s ease;
    }}
    .nav-cta:hover {{
      background: rgba(56, 189, 248, 0.24);
      color: #e0f2fe;
    }}
    .container {{
      width: 100%;
      max-width: 1100px;
      margin: 0 auto;
      padding: 26px 18px 48px;
      flex: 1;
    }}
    .hero {{
      position: relative;
      overflow: hidden;
      background:
        linear-gradient(145deg, rgba(15, 23, 42, 0.96), rgba(15, 23, 42, 0.82)),
        var(--surface);
      border: 1px solid rgba(56, 189, 248, 0.22);
      border-radius: 20px;
      padding: 28px 28px 24px;
      margin-bottom: 22px;
      box-shadow: 0 20px 50px -24px rgba(0, 0, 0, 0.75);
    }}
    .hero::before {{
      content: "";
      position: absolute;
      inset: 0;
      background-image: radial-gradient(rgba(148, 163, 184, 0.12) 1px, transparent 1px);
      background-size: 22px 22px;
      mask-image: linear-gradient(to bottom, rgba(0,0,0,0.45), transparent 85%);
      pointer-events: none;
    }}
    .hero-top {{
      position: relative;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: flex-start;
      gap: 20px;
    }}
    .hero-copy {{
      max-width: 650px;
      min-width: 0;
    }}
    .live-pill {{
      display: inline-flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      max-width: 100%;
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--green);
      background: rgba(52, 211, 153, 0.1);
      border: 1px solid rgba(52, 211, 153, 0.28);
      padding: 4px 11px;
      border-radius: 999px;
      margin-bottom: 12px;
    }}
    .pulse-dot {{
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.7);
      animation: pulse 2s infinite;
    }}
    @keyframes pulse {{
      0% {{ box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.65); }}
      70% {{ box-shadow: 0 0 0 7px rgba(52, 211, 153, 0); }}
      100% {{ box-shadow: 0 0 0 0 rgba(52, 211, 153, 0); }}
    }}
    .hero h1 {{
      margin: 0 0 10px;
      font-size: clamp(1.55rem, 2.8vw, 2.15rem);
      line-height: 1.18;
      letter-spacing: -0.025em;
    }}
    .hero h1 .grad {{
      background: linear-gradient(120deg, #38bdf8, #818cf8 60%, #34d399);
      -webkit-background-clip: text;
      background-clip: text;
      color: transparent;
    }}
    .hero p {{
      margin: 0;
      color: var(--muted);
      font-size: 0.96rem;
      max-width: 58ch;
    }}
    .hero-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    .tg-btn {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      color: #06101f;
      font-weight: 700;
      text-decoration: none;
      padding: 11px 18px;
      border-radius: 11px;
      font-size: 0.9rem;
      white-space: nowrap;
      box-shadow: 0 8px 24px -8px rgba(56, 189, 248, 0.65);
      transition: transform 0.15s ease, opacity 0.15s ease;
    }}
    .tg-btn:hover {{ opacity: 0.94; transform: translateY(-1px); }}
    .ghost-btn {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      background: rgba(30, 41, 59, 0.72);
      border: 1px solid var(--border);
      color: var(--text);
      font-weight: 600;
      text-decoration: none;
      padding: 11px 16px;
      border-radius: 11px;
      font-size: 0.88rem;
      white-space: nowrap;
      transition: border-color 0.15s ease, background 0.15s ease;
    }}
    .ghost-btn:hover {{
      border-color: var(--accent);
      background: rgba(30, 41, 59, 0.95);
    }}
    button.ghost-btn {{
      cursor: pointer;
      font-family: inherit;
    }}
    .share-strip {{
      position: relative;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      margin-top: 14px;
      padding: 11px 14px;
      background: rgba(15, 23, 42, 0.72);
      border: 1px solid rgba(56, 189, 248, 0.25);
      border-radius: 12px;
      font-size: 0.82rem;
      color: var(--muted);
    }}
    .share-reason {{
      flex: 1 1 100%;
      color: var(--text);
      font-weight: 500;
      margin-bottom: 2px;
    }}
    .share-reason strong {{
      color: var(--accent);
    }}
    .share-pill {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      background: rgba(30, 41, 59, 0.65);
      border: 1px solid rgba(36, 50, 74, 0.9);
      color: var(--text);
      text-decoration: none;
      font-size: 0.78rem;
      font-weight: 600;
      padding: 5px 11px;
      border-radius: 999px;
      cursor: pointer;
      font-family: inherit;
      transition: border-color 0.15s ease, color 0.15s ease;
    }}
    .share-pill:hover {{
      border-color: var(--accent);
      color: var(--accent);
    }}
    .hero-kpis {{
      position: relative;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 20px;
      padding-top: 18px;
      border-top: 1px solid rgba(36, 50, 74, 0.75);
    }}
    .kpi {{
      background: rgba(7, 11, 20, 0.55);
      border: 1px solid rgba(36, 50, 74, 0.85);
      border-radius: 12px;
      padding: 10px 14px;
      text-align: left;
      cursor: pointer;
      color: inherit;
      font-family: inherit;
      transition: border-color 0.15s ease, transform 0.15s ease;
    }}
    .kpi:hover {{
      border-color: var(--accent);
      transform: translateY(-1px);
    }}
    .kpi-label {{
      display: block;
      font-size: 0.75rem;
      color: var(--muted);
      margin-bottom: 2px;
    }}
    .kpi-value {{
      font-size: 1.18rem;
      font-weight: 700;
      color: var(--text);
      letter-spacing: -0.01em;
    }}
    .controls {{
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-bottom: 18px;
    }}
    .search-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    .search-input {{
      flex: 1 1 220px;
      min-width: 0;
      width: 100%;
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 10px;
      padding: 11px 14px;
      font-size: 16px;
      outline: none;
    }}
    .search-input:focus {{ border-color: var(--accent); }}
    .stats-pill {{
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--muted);
      border-radius: 10px;
      padding: 10px 14px;
      font-size: 0.88rem;
      white-space: nowrap;
    }}
    .stats-pill strong {{ color: var(--text); }}
    .filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .filters::-webkit-scrollbar {{ display: none; }}
    .chip {{
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--muted);
      border-radius: 999px;
      padding: 7px 13px;
      font-size: 0.84rem;
      cursor: pointer;
      white-space: nowrap;
      flex-shrink: 0;
      transition: all 0.15s ease;
    }}
    .chip:hover {{ border-color: var(--accent); color: var(--text); }}
    .chip.active {{
      background: rgba(56, 189, 248, 0.15);
      border-color: var(--accent);
      color: var(--accent);
      font-weight: 600;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
      gap: 14px;
    }}
    .card {{
      min-width: 0;
      background: rgba(15, 23, 42, 0.92);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px 18px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      transition: border-color 0.15s ease, transform 0.15s ease;
    }}
    .card:hover {{ border-color: #3b4f73; transform: translateY(-1px); }}
    .card-top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      font-size: 0.78rem;
      color: var(--muted);
    }}
    .cat-tag {{
      background: var(--surface-2);
      color: var(--text);
      padding: 3px 9px;
      border-radius: 6px;
      font-weight: 600;
    }}
    .card h2 {{
      margin: 0;
      font-size: 1.03rem;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}
    .card h2 a {{
      color: var(--text);
      text-decoration: none;
    }}
    .card h2 a:hover {{ color: var(--accent); }}
    .badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .badge {{
      font-size: 0.76rem;
      background: rgba(52, 211, 153, 0.12);
      color: var(--green);
      border: 1px solid rgba(52, 211, 153, 0.28);
      padding: 2px 8px;
      border-radius: 999px;
    }}
    .deadline {{
      font-size: 0.8rem;
      color: var(--amber);
      font-weight: 600;
    }}
    .summary {{
      margin: 0;
      color: var(--muted);
      font-size: 0.86rem;
      flex-grow: 1;
      overflow-wrap: anywhere;
    }}
    .card-footer {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      min-width: 0;
      padding-top: 8px;
      border-top: 1px solid rgba(36, 50, 74, 0.7);
      font-size: 0.78rem;
      color: var(--muted);
    }}
    .kw-list {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .card-actions {{
      display: flex;
      align-items: center;
      gap: 6px;
      flex-shrink: 0;
    }}
    .pitch-btn {{
      background: rgba(129, 140, 248, 0.14);
      border: 1px solid rgba(129, 140, 248, 0.38);
      color: #c7d2fe;
      font: inherit;
      font-size: 0.78rem;
      font-weight: 600;
      padding: 7px 10px;
      border-radius: 8px;
      white-space: nowrap;
      cursor: pointer;
      transition: border-color 0.15s ease, background 0.15s ease;
    }}
    .pitch-btn:hover {{
      border-color: var(--accent-2);
      background: rgba(129, 140, 248, 0.24);
    }}
    .apply-btn {{
      background: var(--surface-2);
      border: 1px solid var(--border);
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
      padding: 7px 12px;
      border-radius: 8px;
      white-space: nowrap;
      flex-shrink: 0;
    }}
    .apply-btn:hover {{ border-color: var(--accent); }}
    .modal-backdrop {{
      position: fixed;
      inset: 0;
      z-index: 60;
      background: rgba(2, 6, 23, 0.78);
      backdrop-filter: blur(6px);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }}
    .modal-backdrop.open {{ display: flex; }}
    .modal-card {{
      width: 100%;
      max-width: 620px;
      max-height: 90vh;
      overflow-y: auto;
      background: #0f172a;
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 20px;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.65);
    }}
    .modal-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 10px;
    }}
    .modal-head h2 {{
      margin: 0;
      font-size: 1.08rem;
      line-height: 1.35;
    }}
    .modal-close {{
      background: var(--surface-2);
      border: 1px solid var(--border);
      color: var(--text);
      width: 38px;
      height: 38px;
      border-radius: 10px;
      font-size: 1.1rem;
      cursor: pointer;
      flex-shrink: 0;
    }}
    .modal-meta {{
      font-size: 0.82rem;
      color: var(--muted);
      margin-bottom: 12px;
    }}
    .pitch-box {{
      width: 100%;
      min-height: 185px;
      background: rgba(7, 11, 20, 0.9);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      color: var(--text);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.84rem;
      line-height: 1.5;
      resize: vertical;
      outline: none;
    }}
    .pitch-box:focus {{ border-color: var(--accent); }}
    .checklist-box {{
      margin: 12px 0 16px;
      padding: 12px 14px;
      background: rgba(30, 41, 59, 0.55);
      border: 1px solid rgba(52, 211, 153, 0.28);
      border-radius: 12px;
      font-size: 0.84rem;
    }}
    .checklist-box h3 {{
      margin: 0 0 6px;
      font-size: 0.84rem;
      color: var(--green);
    }}
    .checklist-box ul {{
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
    }}
    .modal-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .modal-actions .tg-btn,
    .modal-actions .ghost-btn {{
      min-height: 44px;
      padding: 10px 16px;
    }}
    .empty {{
      grid-column: 1 / -1;
      text-align: center;
      padding: 40px 20px;
      color: var(--muted);
      background: var(--surface);
      border: 1px dashed var(--border);
      border-radius: 14px;
    }}
    .pagination {{
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      align-items: center;
      gap: 8px;
      margin-top: 22px;
    }}
    .page-btn {{
      min-height: 40px;
      min-width: 40px;
      padding: 8px 13px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
      font: inherit;
      font-size: 0.86rem;
      font-weight: 600;
      cursor: pointer;
      transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
    }}
    .page-btn:hover:not(:disabled) {{
      border-color: var(--accent);
      color: var(--accent);
    }}
    .page-btn.active {{
      background: linear-gradient(135deg, #0284c7, #4f46e5);
      border-color: transparent;
      color: #fff;
    }}
    .page-btn:disabled {{
      opacity: 0.42;
      cursor: not-allowed;
    }}
    .page-dots {{
      color: var(--muted);
      padding: 0 4px;
      font-size: 0.86rem;
    }}
    .tools-section {{
      margin-top: 30px;
      background: linear-gradient(145deg, rgba(16, 185, 129, 0.10), rgba(15, 23, 42, 0.88));
      border: 1px solid rgba(52, 211, 153, 0.30);
      border-radius: 18px;
      padding: 22px 24px;
    }}
    .tools-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 12px;
      margin-bottom: 16px;
    }}
    .tools-head h2 {{
      margin: 0 0 6px;
      font-size: 1.15rem;
    }}
    .tools-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
      gap: 14px;
    }}
    .tool-card {{
      display: flex;
      flex-direction: column;
      gap: 10px;
      background: rgba(7, 11, 20, 0.62);
      border: 1px solid rgba(52, 211, 153, 0.25);
      border-radius: 14px;
      padding: 16px 18px;
    }}
    .tool-top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .tool-badge {{
      font-size: 0.76rem;
      font-weight: 700;
      color: var(--green);
      background: rgba(52, 211, 153, 0.14);
      border: 1px solid rgba(52, 211, 153, 0.32);
      padding: 3px 10px;
      border-radius: 999px;
    }}
    .partner-tag {{
      font-size: 0.72rem;
      color: var(--muted);
    }}
    .tool-card h3 {{
      margin: 0;
      font-size: 0.98rem;
      color: var(--text);
    }}
    .tool-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 0.85rem;
      line-height: 1.5;
    }}
    .tool-cta {{
      align-self: flex-start;
      margin-top: auto;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      text-decoration: none;
      background: linear-gradient(135deg, #059669, #0284c7);
      color: #fff;
      font-size: 0.84rem;
      font-weight: 700;
      padding: 9px 14px;
      border-radius: 10px;
    }}
    .tool-cta:hover {{ filter: brightness(1.08); }}
    .modal-partner-tip {{
      margin-top: 12px;
      padding: 10px 12px;
      border-radius: 10px;
      background: rgba(16, 185, 129, 0.10);
      border: 1px solid rgba(52, 211, 153, 0.28);
      font-size: 0.82rem;
      color: #cbd5e1;
      line-height: 1.45;
    }}
    .modal-partner-tip a {{
      color: var(--green);
      font-weight: 700;
      text-decoration: none;
    }}
    .modal-partner-tip a:hover {{ text-decoration: underline; }}
    .site-footer {{
      margin-top: auto;
      background: rgba(11, 17, 32, 0.95);
      border-top: 1px solid var(--border);
    }}
    .footer-inner {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 36px 18px 26px;
    }}
    .footer-grid {{
      display: grid;
      grid-template-columns: 1.6fr 1fr 1fr;
      gap: 28px;
      padding-bottom: 24px;
      border-bottom: 1px solid rgba(36, 50, 74, 0.75);
    }}
    .footer-brand p {{
      margin: 10px 0 14px;
      color: var(--muted);
      font-size: 0.86rem;
      max-width: 40ch;
    }}
    .footer-pill {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      font-size: 0.78rem;
      color: var(--muted);
      background: var(--surface);
      border: 1px solid var(--border);
      padding: 5px 11px;
      border-radius: 999px;
    }}
    .footer-col h3 {{
      margin: 0 0 12px;
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--text);
    }}
    .footer-links {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .footer-links a,
    .footer-links button {{
      background: none;
      border: none;
      padding: 0;
      font: inherit;
      color: var(--muted);
      text-decoration: none;
      font-size: 0.86rem;
      cursor: pointer;
      text-align: left;
      transition: color 0.15s ease;
    }}
    .footer-links a:hover,
    .footer-links button:hover {{
      color: var(--accent);
    }}
    .footer-bottom {{
      padding-top: 18px;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      color: var(--muted);
      font-size: 0.8rem;
    }}
    .back-top {{
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }}
    .back-top:hover {{ text-decoration: underline; }}
    .seo-section {{
      margin-top: 34px;
      background: rgba(15, 23, 42, 0.72);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 24px;
    }}
    .seo-section h2 {{
      margin: 0 0 6px;
      font-size: 1.2rem;
    }}
    .seo-lead {{
      margin: 0 0 18px;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .seo-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 230px), 1fr));
      gap: 14px;
    }}
    .seo-card {{
      min-width: 0;
      background: rgba(7, 11, 20, 0.52);
      border: 1px solid rgba(36, 50, 74, 0.85);
      border-radius: 12px;
      padding: 14px 16px;
    }}
    .seo-card h3 {{
      margin: 0 0 6px;
      font-size: 0.94rem;
      color: var(--text);
    }}
    .seo-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 0.84rem;
      overflow-wrap: anywhere;
    }}
    @media (max-width: 780px) {{
      .nav-links .hide-sm {{ display: none; }}
      .hero {{ padding: 20px 18px; }}
      .hero-kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .footer-grid {{ grid-template-columns: 1fr; gap: 22px; }}
    }}
    @media (max-width: 640px) {{
      .topbar-inner {{ padding: 10px 14px; gap: 10px; }}
      .brand {{ font-size: 0.88rem; gap: 8px; }}
      .brand-icon {{ width: 32px; height: 32px; border-radius: 8px; }}
      .nav-cta {{ padding: 6px 11px; font-size: 0.8rem; }}
      .nav-cta-handle {{ display: none; }}
      .container {{ padding: 14px 12px 36px; }}
      .hero {{ padding: 18px 15px 16px; border-radius: 16px; margin-bottom: 16px; }}
      .hero h1 {{ font-size: 1.42rem; }}
      .hero p {{ font-size: 0.88rem; }}
      .hero-actions {{ width: 100%; }}
      .tg-btn, .ghost-btn {{
        flex: 1 1 140px;
        justify-content: center;
        min-height: 44px;
        padding: 10px 14px;
        font-size: 0.86rem;
      }}
      .hero-kpis {{ gap: 8px; margin-top: 16px; padding-top: 14px; }}
      .kpi {{ padding: 9px 11px; }}
      .kpi-value {{ font-size: 1.05rem; }}
      .search-row {{ flex-direction: column; align-items: stretch; }}
      .stats-pill {{ text-align: center; padding: 8px 12px; font-size: 0.82rem; }}
      .filters {{
        flex-wrap: nowrap;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
        padding-bottom: 2px;
      }}
      .chip {{ min-height: 38px; padding: 8px 14px; }}
      .grid {{ grid-template-columns: 1fr; gap: 12px; }}
      .card {{ padding: 14px 15px; }}
      .apply-btn {{ min-height: 38px; display: inline-flex; align-items: center; }}
      .seo-section {{ padding: 18px 14px; border-radius: 14px; margin-top: 24px; }}
      .seo-grid {{ grid-template-columns: 1fr; }}
      .footer-inner {{ padding: 26px 14px 20px; }}
      .footer-links a, .footer-links button {{
        min-height: 36px;
        display: inline-flex;
        align-items: center;
      }}
    }}
  </style>
</head>
<body id="top">
  <nav class="topbar" aria-label="Primary navigation">
    <div class="topbar-inner">
      <a class="brand" href="#top">
        <span class="brand-icon">
          <img class="brand-logo" src="{logo_src}" alt="Jobs, Web3 &amp; Scholarships Live Board logo" width="34" height="34" />
        </span>
        <span class="brand-title">Jobs &amp; Scholarships Live Board</span>
      </a>
      <div class="nav-links">
        <a class="nav-link hide-sm" href="#board" data-jump-cat="jobs">Remote Jobs</a>
        <a class="nav-link hide-sm" href="#board" data-jump-cat="web3_jobs">Web3</a>
        <a class="nav-link hide-sm" href="#board" data-jump-cat="scholarships">Scholarships</a>
        <a class="nav-link hide-sm" href="#tools">Tools</a>
        <a class="nav-link hide-sm" href="/api/opportunities">API</a>
        <a class="nav-cta" href="{safe_channel_url}" target="_blank" rel="noopener noreferrer">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71L12.6 16.3l-1.99 1.93c-.23.23-.42.42-.83.42z"/>
          </svg>
          <span>Telegram<span class="nav-cta-handle"> {safe_handle}</span></span>
        </a>
      </div>
    </div>
  </nav>

  <div class="container">
    <header class="hero">
      <div class="hero-top">
        <div class="hero-copy">
          <div class="live-pill">
            <span class="pulse-dot" aria-hidden="true"></span>
            <span>Live Board · {sources_count} Curated Sources · Synced Every 6h</span>
          </div>
          <h1>Remote Tech Jobs, <span class="grad">Web3 Roles</span> &amp; Funded Scholarships</h1>
          <p>Fresh, deduplicated opportunities filtered for global remote work, visa sponsorship, and fully funded fellowships — mirrored straight to {safe_handle}.</p>
        </div>
        <div class="hero-actions">
          <a class="tg-btn" href="{safe_channel_url}" target="_blank" rel="noopener noreferrer">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71L12.6 16.3l-1.99 1.93c-.23.23-.42.42-.83.42z"/>
            </svg>
            Join {safe_handle}
          </a>
          <a class="ghost-btn" href="#board">Browse Feed ↓</a>
          <button type="button" id="shareBoardBtn" class="ghost-btn">📤 Share</button>
        </div>
      </div>

      <div class="share-strip" aria-label="Share this board">
        <span class="share-reason">🎁 <strong>Know someone job-hunting or applying for scholarships?</strong> Share this free 24/7 board — plus invite 3 friends in our Telegram bot to unlock unlimited <strong>One-Tap Application Pitches &amp; ATS Checklists</strong>:</span>
        <a class="share-pill" href="https://t.me/share/url?url={safe_canonical}&amp;text=Free%20Live%20Board%20for%20Remote%20Tech%20Jobs%2C%20Web3%20%26%20Funded%20Scholarships" target="_blank" rel="noopener noreferrer">Telegram</a>
        <a class="share-pill" href="https://wa.me/?text=Free%20Live%20Board%20for%20Remote%20Tech%20Jobs%2C%20Web3%20%26%20Funded%20Scholarships%20{safe_canonical}" target="_blank" rel="noopener noreferrer">WhatsApp</a>
        <a class="share-pill" href="https://twitter.com/intent/tweet?text=Real-time%20radar%20for%20Remote%20Tech%20Jobs%2C%20Web3%20Roles%20%26%20Funded%20Scholarships&amp;url={safe_canonical}" target="_blank" rel="noopener noreferrer">X / Twitter</a>
        <a class="share-pill" href="https://www.linkedin.com/sharing/share-offsite/?url={safe_canonical}" target="_blank" rel="noopener noreferrer">LinkedIn</a>
        <button type="button" id="copyLinkBtn" class="share-pill">🔗 Copy Link</button>
      </div>

      <div class="hero-kpis" aria-label="Live category totals">
        <button type="button" class="kpi" data-jump-cat="all">
          <span class="kpi-label">Fresh Cache (≤200)</span>
          <span class="kpi-value">{total_count} Live</span>
        </button>
        <button type="button" class="kpi" data-jump-cat="jobs">
          <span class="kpi-label">💼 Remote Jobs</span>
          <span class="kpi-value">{jobs_count}</span>
        </button>
        <button type="button" class="kpi" data-jump-cat="web3_jobs">
          <span class="kpi-label">⛓️ Web3 Remote</span>
          <span class="kpi-value">{web3_count}</span>
        </button>
        <button type="button" class="kpi" data-jump-cat="scholarships">
          <span class="kpi-label">🎓 Scholarships</span>
          <span class="kpi-value">{scholarships_count}</span>
        </button>
      </div>
    </header>

    <section id="board" class="controls" aria-label="Filter opportunities">
      <div class="search-row">
        <input id="searchInput" class="search-input" type="search" placeholder="Search roles, skills, countries (e.g. python, solidity, nigeria, fully funded)..." />
        <div class="stats-pill"><strong id="shownCount">{total_count}</strong> of <strong id="totalCount">{total_count}</strong> fresh posts (3–7d window · max 200)</div>
      </div>
      <div class="filters" id="catFilters">
        <button class="chip active" data-cat="all">All</button>
        <button class="chip" data-cat="jobs">💼 Remote Jobs</button>
        <button class="chip" data-cat="web3_jobs">⛓️ Web3 Remote</button>
        <button class="chip" data-cat="scholarships">🎓 Scholarships</button>
      </div>
      <div class="filters" id="badgeFilters">
        <button class="chip" data-badge="🌍 Worldwide">🌍 Worldwide</button>
        <button class="chip" data-badge="🛂 Visa Sponsored">🛂 Visa Sponsored</button>
        <button class="chip" data-badge="💰 Fully Funded">💰 Fully Funded</button>
        <button class="chip" data-badge="🟢 Entry / Intern">🟢 Entry / Intern</button>
      </div>
    </section>

    <main class="grid" id="cardsGrid">
{ssr_cards}
    </main>

    <nav id="paginationBar" class="pagination" aria-label="Opportunity pages"></nav>

{tools_section_html}

    <section class="seo-section" aria-label="About and frequently asked questions">
      <h2>How Our Automated Job, Web3 &amp; Scholarship Radar Works</h2>
      <p class="seo-lead">Curated every 6 hours from {sources_count} trusted job boards &amp; scholarship portals — built for global builders, software engineers, and fellows.</p>
      <div class="seo-grid">
        <article class="seo-card">
          <h3>Freshness-First Filtering (Up to 200 Live)</h3>
          <p>Why 200? We cap the live board at the 200 newest deduplicated opportunities—and expire remote tech/Web3 jobs after 3 days (7 days for scholarships)—so every listing stays fast to browse and never stale.</p>
        </article>
        <article class="seo-card">
          <h3>Cross-Source Deduplication</h3>
          <p>Identical roles reposted across multiple boards are automatically merged by normalized title, leaving a clean, zero-spam feed.</p>
        </article>
        <article class="seo-card">
          <h3>Smart Triage Badges</h3>
          <p>Spot 🌍 Worldwide remote roles, 🛂 Visa Sponsored openings, 💰 Fully Funded fellowships, 🟢 Entry/Intern roles, and ⏳ extracted deadlines in seconds.</p>
        </article>
        <article class="seo-card">
          <h3>24/7 Telegram Channel &amp; Bot</h3>
          <p>Join {safe_handle} on Telegram for 6-hour alerts, cycle reminders, and daily 06:00 UTC digests — or message the bot with /latest, /web3, /scholarships, /worldwide, and /visa.</p>
        </article>
      </div>
    </section>
  </div>

  <footer class="site-footer">
    <div class="footer-inner">
      <div class="footer-grid">
        <div class="footer-brand">
          <a class="brand" href="#top">
            <span class="brand-icon">
              <img class="brand-logo" src="{logo_src}" alt="Jobs, Web3 &amp; Scholarships Live Board logo" width="34" height="34" />
            </span>
            <span>Jobs &amp; Scholarships Live Board</span>
          </a>
          <p>Zero-cost automated radar tracking recent remote software roles, Web3 jobs, visa-sponsored openings, and funded scholarships worldwide.</p>
          <span class="footer-pill">
            <span class="pulse-dot" aria-hidden="true"></span>
            Auto-synced every 6 hours · Cross-source deduplicated
          </span>
        </div>

        <div class="footer-col">
          <h3>Quick Filters</h3>
          <ul class="footer-links">
            <li><button type="button" data-jump-cat="jobs">💼 Remote Tech Jobs</button></li>
            <li><button type="button" data-jump-cat="web3_jobs">⛓️ Web3 Remote Roles</button></li>
            <li><button type="button" data-jump-cat="scholarships">🎓 Scholarships &amp; Fellowships</button></li>
            <li><button type="button" data-jump-badge="🌍 Worldwide">🌍 Worldwide Remote</button></li>
            <li><button type="button" data-jump-badge="🛂 Visa Sponsored">🛂 Visa Sponsored</button></li>
          </ul>
        </div>

        <div class="footer-col">
          <h3>Channels &amp; Feeds</h3>
          <ul class="footer-links">
            <li><a href="{safe_channel_url}" target="_blank" rel="noopener noreferrer">📢 Telegram ({safe_handle})</a></li>
            <li><a href="#tools">💳 Payout &amp; Career Tools</a></li>
            <li><a href="/feed.xml">📡 RSS Feed (/feed.xml)</a></li>
            <li><a href="/api/opportunities">⚡ JSON API (/api/opportunities)</a></li>
            <li><a href="/llms.txt">🤖 AI Index (/llms.txt)</a></li>
            <li><a href="/sitemap.xml">🗺️ XML Sitemap</a></li>
            <li><a href="/robots.txt">🕷️ Robots.txt</a></li>
          </ul>
        </div>
      </div>

      <div class="footer-bottom">
        <span>© {current_year} Jobs, Web3 &amp; Scholarships Live Board · Curated from {sources_count} verified feeds.</span>
        <a class="back-top" href="#top">Back to top ↑</a>
      </div>
    </div>
  </footer>

  <div id="pitchModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="pitchModalTitle">
    <div class="modal-card">
      <div class="modal-head">
        <div>
          <span id="pitchBadgeLabel" class="cat-tag">📝 One-Tap Pitch &amp; ATS Checklist</span>
          <h2 id="pitchModalTitle" style="margin-top:8px;">Application Pitch</h2>
        </div>
        <button type="button" id="closePitchBtn" class="modal-close" aria-label="Close pitch modal">✕</button>
      </div>
      <div id="pitchMeta" class="modal-meta"></div>
      <textarea id="pitchTextarea" class="pitch-box" aria-label="Editable application pitch"></textarea>
      <div class="checklist-box">
        <h3>🎯 Prep &amp; ATS Checklist</h3>
        <ul id="pitchChecklist"></ul>
      </div>
      {modal_partner_tip_html}
      <div class="modal-actions">
        <button type="button" id="copyPitchBtn" class="tg-btn" style="border:none;cursor:pointer;font-family:inherit;">📋 Copy Pitch</button>
        <a id="pitchApplyLink" class="ghost-btn" href="#" target="_blank" rel="noopener noreferrer">Apply Now ↗</a>
        <a class="ghost-btn" href="{safe_channel_url}" target="_blank" rel="noopener noreferrer">📢 Join Telegram</a>
      </div>
    </div>
  </div>

  <script>
    const ITEMS = {safe_json};
    const PAGE_SIZE = 24;
    let activeCat = "all";
    let activeBadge = "";
    let searchTerm = "";
    let currentPage = 1;

    const esc = (v) => String(v || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

    const safeHref = (u) => {{
      const s = String(u || "").trim();
      return /^https?:\\/\\//i.test(s) ? s : "#";
    }};

    const syncFilterButtons = () => {{
      document.querySelectorAll("#catFilters .chip").forEach((c) => {{
        c.classList.toggle("active", c.dataset.cat === activeCat);
      }});
      document.querySelectorAll("#badgeFilters .chip").forEach((c) => {{
        c.classList.toggle("active", c.dataset.badge === activeBadge);
      }});
    }};

    const buildPageNumbers = (totalPages, page) => {{
      if (totalPages <= 7) return Array.from({{ length: totalPages }}, (_, i) => i + 1);
      const pages = new Set([1, totalPages, page - 1, page, page + 1]);
      const sorted = Array.from(pages).filter((p) => p >= 1 && p <= totalPages).sort((a, b) => a - b);
      const out = [];
      for (let i = 0; i < sorted.length; i++) {{
        if (i > 0 && sorted[i] - sorted[i - 1] > 1) out.push("...");
        out.push(sorted[i]);
      }}
      return out;
    }};

    const renderPagination = (totalItems, totalPages) => {{
      const bar = document.getElementById("paginationBar");
      if (!bar) return;
      if (totalPages <= 1) {{
        bar.innerHTML = "";
        return;
      }}
      const nums = buildPageNumbers(totalPages, currentPage);
      const numHtml = nums.map((n) => {{
        if (n === "...") return '<span class="page-dots">…</span>';
        const activeCls = n === currentPage ? " active" : "";
        return `<button type="button" class="page-btn${{activeCls}}" data-page="${{n}}" aria-label="Page ${{n}}"${{n === currentPage ? ' aria-current="page"' : ""}}>${{n}}</button>`;
      }}).join("");
      bar.innerHTML = `
        <button type="button" class="page-btn" data-page="${{currentPage - 1}}"${{currentPage <= 1 ? " disabled" : ""}}>◀ Prev</button>
        ${{numHtml}}
        <button type="button" class="page-btn" data-page="${{currentPage + 1}}"${{currentPage >= totalPages ? " disabled" : ""}}>Next ▶</button>
      `;
    }};

    const render = () => {{
      const q = searchTerm.trim().toLowerCase();
      const filtered = ITEMS.filter((item) => {{
        if (activeCat !== "all" && item.category !== activeCat) return false;
        if (activeBadge && !(item.badges || []).includes(activeBadge)) return false;
        if (q) {{
          const hay = [
            item.title,
            item.summary,
            item.source_name,
            ...(item.matched_keywords || []),
            ...(item.badges || []),
          ].join(" ").toLowerCase();
          if (!q.split(/\\s+/).every((part) => hay.includes(part))) return false;
        }}
        return true;
      }});

      const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
      if (currentPage > totalPages) currentPage = totalPages;
      if (currentPage < 1) currentPage = 1;
      const start = (currentPage - 1) * PAGE_SIZE;
      const pageItems = filtered.slice(start, start + PAGE_SIZE);

      document.getElementById("totalCount").textContent = ITEMS.length;
      document.getElementById("shownCount").textContent = filtered.length
        ? `${{start + 1}}–${{start + pageItems.length}} of ${{filtered.length}}`
        : "0";

      const grid = document.getElementById("cardsGrid");
      if (!filtered.length) {{
        grid.innerHTML = '<div class="empty">No matching opportunities found. Try clearing filters or searching another keyword.</div>';
        renderPagination(0, 0);
        return;
      }}

      grid.innerHTML = pageItems.map((item) => {{
        const badgesHtml = (item.badges || []).map((b) => `<span class="badge">${{esc(b)}}</span>`).join("");
        const deadlineHtml = item.deadline ? `<div class="deadline">⏳ Deadline: ${{esc(item.deadline)}}</div>` : "";
        const shortDate = item.published ? esc(item.published.replace(/\\s*[+-]\\d{{4}}$/, "").replace(/\\s*(?:GMT|UTC)$/, "")) : "";
        const kws = esc((item.matched_keywords || []).join(", "));
        return `
          <article class="card">
            <div class="card-top">
              <span class="cat-tag">${{esc(item.category_label)}}</span>
              <span>${{esc(item.source_name)}}</span>
            </div>
            <h2><a href="${{esc(safeHref(item.link))}}" target="_blank" rel="noopener noreferrer">${{esc(item.title)}}</a></h2>
            ${{badgesHtml ? `<div class="badges">${{badgesHtml}}</div>` : ""}}
            ${{deadlineHtml}}
            ${{item.summary ? `<p class="summary">${{esc(item.summary)}}</p>` : ""}}
            <div class="card-footer">
              <span class="kw-list">${{shortDate ? shortDate + " · " : ""}}🏷 ${{kws}}</span>
              <div class="card-actions">
                <button type="button" class="pitch-btn" data-pitch-id="${{esc(item.item_id)}}">📝 Pitch</button>
                <a class="apply-btn" href="${{esc(safeHref(item.link))}}" target="_blank" rel="noopener noreferrer">Apply ↗</a>
              </div>
            </div>
          </article>
        `;
      }}).join("");

      renderPagination(filtered.length, totalPages);
    }};

    document.getElementById("searchInput").addEventListener("input", (e) => {{
      searchTerm = e.target.value;
      currentPage = 1;
      render();
    }});

    document.getElementById("catFilters").addEventListener("click", (e) => {{
      const btn = e.target.closest(".chip");
      if (!btn) return;
      activeCat = btn.dataset.cat;
      currentPage = 1;
      syncFilterButtons();
      render();
    }});

    document.getElementById("badgeFilters").addEventListener("click", (e) => {{
      const btn = e.target.closest(".chip");
      if (!btn) return;
      const b = btn.dataset.badge;
      activeBadge = activeBadge === b ? "" : b;
      currentPage = 1;
      syncFilterButtons();
      render();
    }});

    document.getElementById("paginationBar")?.addEventListener("click", (e) => {{
      const btn = e.target.closest("[data-page]");
      if (!btn || btn.disabled) return;
      const next = parseInt(btn.dataset.page || "1", 10);
      if (!Number.isNaN(next)) {{
        currentPage = next;
        render();
        document.getElementById("board")?.scrollIntoView({{ behavior: "smooth" }});
      }}
    }});

    document.addEventListener("click", (e) => {{
      const jumpCat = e.target.closest("[data-jump-cat]");
      if (jumpCat) {{
        activeCat = jumpCat.dataset.jumpCat;
        activeBadge = "";
        currentPage = 1;
        syncFilterButtons();
        render();
        document.getElementById("board")?.scrollIntoView({{ behavior: "smooth" }});
        return;
      }}
      const jumpBadge = e.target.closest("[data-jump-badge]");
      if (jumpBadge) {{
        activeCat = "all";
        activeBadge = jumpBadge.dataset.jumpBadge;
        currentPage = 1;
        syncFilterButtons();
        render();
        document.getElementById("board")?.scrollIntoView({{ behavior: "smooth" }});
      }}
    }});

    (() => {{
      const params = new URLSearchParams(window.location.search);
      const itemParam = params.get("item");
      const qParam = params.get("q");
      const catParam = params.get("cat");
      const badgeParam = params.get("badge");
      const pageParam = parseInt(params.get("page") || "1", 10);
      if (itemParam) {{
        const idx = ITEMS.findIndex((it) => it.item_id === itemParam);
        if (idx > 0) {{
          ITEMS.unshift(ITEMS.splice(idx, 1)[0]);
        }}
      }}
      if (qParam) {{
        searchTerm = qParam;
        const input = document.getElementById("searchInput");
        if (input) input.value = qParam;
      }}
      if (catParam && ["all", "jobs", "web3_jobs", "scholarships"].includes(catParam)) {{
        activeCat = catParam;
      }}
      if (badgeParam) {{
        const match = Array.from(document.querySelectorAll("#badgeFilters .chip"))
          .map((c) => c.dataset.badge)
          .find((b) => b && b.toLowerCase().includes(badgeParam.toLowerCase()));
        if (match) activeBadge = match;
      }}
      if (!Number.isNaN(pageParam) && pageParam > 1) {{
        currentPage = pageParam;
      }}
      syncFilterButtons();
      render();
    }})();

    const copyBoardUrl = async (btn, originalLabel) => {{
      const url = window.location.href.split("#")[0];
      try {{
        await navigator.clipboard.writeText(url);
        btn.textContent = "✅ Link Copied!";
        setTimeout(() => {{ btn.textContent = originalLabel; }}, 2000);
      }} catch (_err) {{
        window.prompt("Copy link to share:", url);
      }}
    }};

    document.getElementById("shareBoardBtn")?.addEventListener("click", async (e) => {{
      const btn = e.currentTarget;
      const url = window.location.href.split("#")[0];
      if (navigator.share) {{
        try {{
          await navigator.share({{
            title: "Jobs, Web3 & Scholarships Live Board",
            text: "Fresh remote tech jobs, Web3 roles & fully funded scholarships — updated every 6 hours!",
            url,
          }});
          return;
        }} catch (_err) {{}}
      }}
      copyBoardUrl(btn, "📤 Share");
    }});

    document.getElementById("copyLinkBtn")?.addEventListener("click", (e) => {{
      copyBoardUrl(e.currentTarget, "🔗 Copy Link");
    }});

    const openPitchModal = (item) => {{
      const modal = document.getElementById("pitchModal");
      if (!modal || !item) return;
      const kws = (item.matched_keywords && item.matched_keywords.length) ? item.matched_keywords.slice(0, 5).join(", ") : "relevant experience";
      const isSch = item.category === "scholarships";
      document.getElementById("pitchBadgeLabel").textContent = isSch
        ? "🎓 One-Tap Scholarship Pitch & Checklist"
        : "📝 One-Tap Job Pitch & ATS Checklist";
      document.getElementById("pitchModalTitle").textContent = item.title;
      document.getElementById("pitchMeta").textContent = [
        item.source_name,
        ...(item.badges || []),
        item.deadline ? `⏳ Deadline: ${{item.deadline}}` : "",
      ].filter(Boolean).join(" · ");

      const pitchText = isSch
        ? `Dear ${{item.source_name}} Selection Committee,\n\nI am writing to express my strong interest in the ${{item.title}}. With a background aligned with ${{kws}}, my academic and community work focuses on [Your Field / Research Focus], including [Key Project, Publication, or Measurable Impact].\n\nReceiving this opportunity would enable me to [Specific Goal / Contribution], and I have prepared my academic transcripts, CV, and references for your review.\n\nBest regards,\n[Your Full Name] | [LinkedIn / Portfolio Link]`
        : `Subject: Application for ${{item.title}} — [Your Name]\n\nHi Hiring Team at ${{item.source_name}},\n\nI saw your opening for ${{item.title}} and wanted to reach out directly. I bring [X] years of hands-on experience with ${{kws}}, most recently [1-line achievement with metric or shipped project].\n\nPortfolio / GitHub: [Your Link]\nWould love to connect if my background fits what you're looking for.\n\nBest,\n[Your Name]`;

      document.getElementById("pitchTextarea").value = pitchText;
      const listEl = document.getElementById("pitchChecklist");
      const bullets = isSch
        ? [
            `Tailor your Statement of Purpose around: ${{kws}}`,
            "Prepare official transcripts, updated CV & 2 referee contacts",
            "Confirm eligibility criteria & deadline before submitting",
          ]
        : [
            `Mirror these ATS keywords in your CV summary: ${{kws}}`,
            "Attach 1–2 live proof links (GitHub, portfolio, or shipped product)",
            "Send the short DM above to the hiring manager on LinkedIn/X after applying",
          ];
      listEl.innerHTML = bullets.map((b) => `<li>${{esc(b)}}</li>`).join("");
      const applyLink = document.getElementById("pitchApplyLink");
      if (applyLink) applyLink.href = safeHref(item.link);
      modal.classList.add("open");
      try {{ window.Telegram?.WebApp?.BackButton?.show(); }} catch (_e) {{}}
    }};

    const closePitchModal = () => {{
      document.getElementById("pitchModal")?.classList.remove("open");
      try {{ window.Telegram?.WebApp?.BackButton?.hide(); }} catch (_e) {{}}
    }};

    document.addEventListener("click", (e) => {{
      const pBtn = e.target.closest("[data-pitch-id]");
      if (pBtn) {{
        const id = pBtn.dataset.pitchId;
        const found = ITEMS.find((i) => i.item_id === id);
        if (found) openPitchModal(found);
      }}
    }});

    document.getElementById("closePitchBtn")?.addEventListener("click", closePitchModal);
    document.getElementById("pitchModal")?.addEventListener("click", (e) => {{
      if (e.target.id === "pitchModal") closePitchModal();
    }});
    document.addEventListener("keydown", (e) => {{
      if (e.key === "Escape") closePitchModal();
    }});
    document.getElementById("copyPitchBtn")?.addEventListener("click", async (e) => {{
      const btn = e.currentTarget;
      const txt = document.getElementById("pitchTextarea")?.value || "";
      try {{
        await navigator.clipboard.writeText(txt);
        btn.textContent = "✅ Pitch Copied!";
        setTimeout(() => {{ btn.textContent = "📋 Copy Pitch"; }}, 2000);
      }} catch (_err) {{
        document.getElementById("pitchTextarea")?.select();
      }}
    }});

    window.addEventListener("DOMContentLoaded", () => {{
      const tgApp = window.Telegram && window.Telegram.WebApp;
      if (tgApp) {{
        tgApp.ready();
        tgApp.expand();
        try {{ tgApp.setHeaderColor("#0b1120"); }} catch (_e) {{}}
        try {{ tgApp.setBackgroundColor("#070b14"); }} catch (_e) {{}}
        try {{ tgApp.BackButton?.onClick(closePitchModal); }} catch (_e) {{}}

        document.addEventListener("click", (e) => {{
          const tgLink = e.target.closest('a[href^="https://t.me/"]');
          if (tgLink && typeof tgApp.openTelegramLink === "function") {{
            e.preventDefault();
            tgApp.openTelegramLink(tgLink.href);
          }}
        }});
      }}
    }});
  </script>
</body>
</html>
"""
