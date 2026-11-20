"""Self-contained HTML renderer for the live Job & Scholarship Web Board."""

from __future__ import annotations

import html
import json
from typing import Any

import scraper


def render_web_board_html(
    items: list[scraper.Opportunity],
    channel_url: str = "https://t.me/latestjobsandscholarship",
    channel_handle: str = "@latestjobsandscholarship",
) -> str:
    """Render a responsive, searchable web board with embedded opportunity data."""
    payload = [item.to_dict() for item in items]
    safe_json = json.dumps(payload).replace("</", "<\\/")
    safe_channel_url = html.escape(channel_url or "https://t.me/latestjobsandscholarship", quote=True)
    safe_handle = html.escape(channel_handle or "@latestjobsandscholarship")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Job, Web3 &amp; Scholarship Live Board</title>
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

    <section class="controls">
      <div class="search-row">
        <input id="searchInput" class="search-input" type="search" placeholder="Search roles, skills, countries (e.g. python, solidity, nigeria, fully funded)..." />
        <div class="stats-pill"><strong id="shownCount">0</strong> of <strong id="totalCount">0</strong> recent posts</div>
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

    <main class="grid" id="cardsGrid"></main>
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
        const shortDate = item.published ? esc(item.published.replace(/\\s*[+-]\\d{{4}}$/, "").replace(/\\s*GMT$/, "")) : "";
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

    render();
  </script>
</body>
</html>
"""
