"""Self-contained SEO + AI-Search-ready HTML renderer for the live Web Board."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import Any

import scraper

DEFAULT_SITE_URL = "https://job-scholarship-alert-bot-chi.vercel.app"


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
        cards.append(
            f"""<article class="card">
  <div class="card-top">
    <span class="cat-tag">{html.escape(item.category_label)}</span>
    <span>{html.escape(item.source_name)}</span>
  </div>
  <h2><a href="{html.escape(item.link, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(item.title)}</a></h2>
  {f'<div class="badges">{badges_html}</div>' if badges_html else ''}
  {deadline_html}
  {summary_html}
  <div class="card-footer">
    <span class="kw-list">{date_prefix}🏷 {kws}</span>
    <a class="apply-btn" href="{html.escape(item.link, quote=True)}" target="_blank" rel="noopener noreferrer">Apply ↗</a>
  </div>
</article>"""
        )
    return "\n".join(cards)


def build_structured_data(
    site_url: str,
    items: list[scraper.Opportunity],
) -> dict[str, Any]:
    """Build Schema.org JSON-LD graph for Google Search & AI Search engines."""
    clean_url = site_url.rstrip("/")
    list_elements: list[dict[str, Any]] = []
    for idx, item in enumerate(items[:25], start=1):
        if item.category in {"jobs", "web3_jobs"}:
            node: dict[str, Any] = {
                "@type": "JobPosting",
                "title": item.title,
                "url": item.link,
                "description": item.summary or item.title,
                "hiringOrganization": {
                    "@type": "Organization",
                    "name": item.source_name,
                },
                "jobLocationType": "TELECOMMUTE",
            }
            if item.published_dt:
                node["datePosted"] = item.published_dt.date().isoformat()
        else:
            node = {
                "@type": "CreativeWork",
                "name": item.title,
                "url": item.link,
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
                "@type": "WebSite",
                "name": "Jobs, Web3 & Scholarships Live Board",
                "url": f"{clean_url}/",
                "description": (
                    "Daily curated remote tech jobs, Web3 remote roles, and "
                    "funded international scholarships and fellowships."
                ),
            },
            {
                "@type": "ItemList",
                "name": "Latest Remote Jobs, Web3 Roles & Scholarships",
                "numberOfItems": len(list_elements),
                "itemListElement": list_elements,
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
        "> Curated recent remote software/tech jobs, Web3 remote roles, and funded international scholarships & fellowships, synced automatically every 6 hours.",
        "",
        f"- Web Board: {clean_url}/",
        f"- JSON Feed: {clean_url}/api/opportunities",
        f"- Telegram Channel ({channel_handle}): {channel_url}",
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


def render_web_board_html(
    items: list[scraper.Opportunity],
    channel_url: str = "https://t.me/latestjobsandscholarship",
    channel_handle: str = "@latestjobsandscholarship",
    site_url: str = DEFAULT_SITE_URL,
) -> str:
    """Render a responsive, SEO + AI-Search-ready web board."""
    clean_site_url = site_url.rstrip("/")
    payload = [item.to_dict() for item in items]
    safe_json = json.dumps(payload).replace("</", "<\\/")
    structured_json = json.dumps(build_structured_data(clean_site_url, items)).replace("</", "<\\/")
    safe_channel_url = html.escape(channel_url or "https://t.me/latestjobsandscholarship", quote=True)
    safe_handle = html.escape(channel_handle or "@latestjobsandscholarship")
    safe_canonical = html.escape(f"{clean_site_url}/", quote=True)
    meta_desc = (
        f"Browse {len(items)} recent remote tech jobs, Web3 remote opportunities, "
        "visa-sponsored roles, and fully funded scholarships & fellowships updated daily."
    )
    safe_desc = html.escape(meta_desc, quote=True)
    ssr_cards = _render_ssr_cards(items)
    total_count = len(items)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Jobs, Web3 &amp; Scholarships Live Board | Remote Roles &amp; Funded Fellowships</title>
  <meta name="description" content="{safe_desc}" />
  <meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large" />
  <link rel="canonical" href="{safe_canonical}" />
  <meta property="og:type" content="website" />
  <meta property="og:title" content="Jobs, Web3 &amp; Scholarships Live Board" />
  <meta property="og:description" content="{safe_desc}" />
  <meta property="og:url" content="{safe_canonical}" />
  <meta property="og:site_name" content="Jobs, Web3 &amp; Scholarships Live Board" />
  <meta name="twitter:card" content="summary" />
  <meta name="twitter:title" content="Jobs, Web3 &amp; Scholarships Live Board" />
  <meta name="twitter:description" content="{safe_desc}" />
  <script type="application/ld+json">{structured_json}</script>
  <style>
    :root {{
      --bg: #0b1120;
      --surface: #111827;
      --surface-2: #1e293b;
      --border: #263248;
      --text: #f8fafc;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --accent-2: #818cf8;
      --green: #34d399;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
      background: radial-gradient(circle at top, #172554 0%, var(--bg) 42%);
      color: var(--text);
      min-height: 100vh;
      line-height: 1.5;
    }}
    .container {{
      max-width: 1060px;
      margin: 0 auto;
      padding: 28px 18px 60px;
    }}
    .hero {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      background: rgba(17, 24, 39, 0.85);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 22px 24px;
      margin-bottom: 20px;
    }}
    .hero h1 {{
      margin: 0 0 6px;
      font-size: 1.55rem;
      letter-spacing: -0.02em;
    }}
    .hero p {{
      margin: 0;
      color: var(--muted);
      font-size: 0.95rem;
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
      border-radius: 10px;
      font-size: 0.92rem;
      white-space: nowrap;
    }}
    .tg-btn:hover {{ opacity: 0.92; }}
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
      flex: 1;
      min-width: 240px;
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 10px;
      padding: 11px 14px;
      font-size: 0.95rem;
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
    }}
    .stats-pill strong {{ color: var(--text); }}
    .filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .chip {{
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--muted);
      border-radius: 999px;
      padding: 7px 13px;
      font-size: 0.84rem;
      cursor: pointer;
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
      grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
      gap: 14px;
    }}
    .card {{
      background: rgba(17, 24, 39, 0.92);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px 18px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .card:hover {{ border-color: #3b4f73; }}
    .card-top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
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
      color: #fbbf24;
      font-weight: 600;
    }}
    .summary {{
      margin: 0;
      color: var(--muted);
      font-size: 0.86rem;
      flex-grow: 1;
    }}
    .card-footer {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding-top: 8px;
      border-top: 1px solid rgba(38, 50, 72, 0.7);
      font-size: 0.78rem;
      color: var(--muted);
    }}
    .kw-list {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .apply-btn {{
      background: var(--surface-2);
      border: 1px solid var(--border);
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
      padding: 6px 11px;
      border-radius: 8px;
      white-space: nowrap;
    }}
    .apply-btn:hover {{ border-color: var(--accent); }}
    .empty {{
      grid-column: 1 / -1;
      text-align: center;
      padding: 40px 20px;
      color: var(--muted);
      background: var(--surface);
      border: 1px dashed var(--border);
      border-radius: 14px;
    }}
    .site-footer {{
      margin-top: 32px;
      padding-top: 16px;
      border-top: 1px solid var(--border);
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 10px;
      color: var(--muted);
      font-size: 0.82rem;
    }}
    .site-footer a {{ color: var(--accent); text-decoration: none; }}
    .site-footer a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="container">
    <header class="hero">
      <div>
        <h1>🚀 Jobs, Web3 &amp; Scholarships Live Board</h1>
        <p>Automatically curated recent opportunities — synced with {safe_handle} on Telegram.</p>
      </div>
      <a class="tg-btn" href="{safe_channel_url}" target="_blank" rel="noopener noreferrer">
        📢 Join {safe_handle}
      </a>
    </header>

    <section class="controls" aria-label="Filter opportunities">
      <div class="search-row">
        <input id="searchInput" class="search-input" type="search" placeholder="Search roles, skills, countries (e.g. python, solidity, nigeria, fully funded)..." />
        <div class="stats-pill"><strong id="shownCount">{total_count}</strong> of <strong id="totalCount">{total_count}</strong> recent posts</div>
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

    <footer class="site-footer">
      <span>Updated automatically from verified RSS &amp; job APIs.</span>
      <span>
        <a href="/api/opportunities">JSON Feed</a> ·
        <a href="/llms.txt">llms.txt</a> ·
        <a href="/sitemap.xml">Sitemap</a>
      </span>
    </footer>
  </div>

  <script>
    const ITEMS = {safe_json};
    let activeCat = "all";
    let activeBadge = "";
    let searchTerm = "";

    const esc = (v) => String(v || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

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

      document.getElementById("totalCount").textContent = ITEMS.length;
      document.getElementById("shownCount").textContent = filtered.length;

      const grid = document.getElementById("cardsGrid");
      if (!filtered.length) {{
        grid.innerHTML = '<div class="empty">No matching opportunities found. Try clearing filters or searching another keyword.</div>';
        return;
      }}

      grid.innerHTML = filtered.map((item) => {{
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
            <h2><a href="${{esc(item.link)}}" target="_blank" rel="noopener noreferrer">${{esc(item.title)}}</a></h2>
            ${{badgesHtml ? `<div class="badges">${{badgesHtml}}</div>` : ""}}
            ${{deadlineHtml}}
            ${{item.summary ? `<p class="summary">${{esc(item.summary)}}</p>` : ""}}
            <div class="card-footer">
              <span class="kw-list">${{shortDate ? shortDate + " · " : ""}}🏷 ${{kws}}</span>
              <a class="apply-btn" href="${{esc(item.link)}}" target="_blank" rel="noopener noreferrer">Apply ↗</a>
            </div>
          </article>
        `;
      }}).join("");
    }};

    document.getElementById("searchInput").addEventListener("input", (e) => {{
      searchTerm = e.target.value;
      render();
    }});

    document.getElementById("catFilters").addEventListener("click", (e) => {{
      const btn = e.target.closest(".chip");
      if (!btn) return;
      activeCat = btn.dataset.cat;
      document.querySelectorAll("#catFilters .chip").forEach((c) => c.classList.toggle("active", c === btn));
      render();
    }});

    document.getElementById("badgeFilters").addEventListener("click", (e) => {{
      const btn = e.target.closest(".chip");
      if (!btn) return;
      const b = btn.dataset.badge;
      activeBadge = activeBadge === b ? "" : b;
      document.querySelectorAll("#badgeFilters .chip").forEach((c) => c.classList.toggle("active", c.dataset.badge === activeBadge));
      render();
    }});
  </script>
</body>
</html>
"""
