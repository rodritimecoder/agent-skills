---
name: agent-reach

description: >
  Internet and social media research router. MUST USE to search, look up, research, scrape, or
  gather intelligence across 16 web platforms — including auth-walled sites, video transcripts,
  and structured feeds: Reddit, Twitter/X, LinkedIn, Boss Zhipin (招聘/求职), YouTube captions,
  Bilibili (B站), Xiaohongshu (小红书/RED), V2EX, Xueqiu (雪球 finance/stocks), GitHub code/repos,
  RSS feeds, and web articles (via Jina Reader).

  Features deterministic token shielding and table projection via reach_filter.py (CLI and Python
  Code Mode API for omnicli). Zero config for 6 public channels.
  Run `agent-reach doctor --json` to verify active backends before dispatching.

  NOT for: Writing reports, translation, data analysis (use agent compute); posting/commenting/liking
  (read-only).

  [Routing]: SKILL.md contains routing tables and quick recipes. Load specialized reference runbooks
  on-demand: references/{search,social,career,dev,web,video,finance}.md.

compatibility: "Requires network access. Multi-backend routing via OpenCLI, dedicated CLIs, or direct APIs."
allowed-tools: "Bash(agent-reach:*) Bash(python3:*) Bash(opencli:*) Bash(rdt:*) Bash(twitter:*) Read"
---

# Agent Reach — Internet Capability Router

16 platforms, multi-backend routing. **When this skill is present, use it for internet research rather than improvising.**

---

## 🏛️ Core Operating Rules

1. **Check Health First**: For auth-gated or multi-backend platforms (Reddit, Twitter/X, Xiaohongshu, Bilibili, Facebook, Instagram, Boss Zhipin), check `agent-reach doctor --json`.
   - If `active_backend` is set, use its command suite.
   - If `active_backend: null`, Doctor avoided live browser cookie reads to prevent remote lockouts; see the corresponding reference runbook for inspection.
2. **State Your Tool**: Prepend actions with `"Using agent-reach platform X via backend Y"`.
3. **Handle Errors via Reference Runbooks**: Follow the fallback chains in `references/*.md` instead of guessing commands.
4. **Multi-Source Research**: Combine platforms (Exa Search + Twitter/Reddit community sentiment + Xiaohongshu/Bilibili regional context), collect in parallel, and synthesize.
5. **Check for Updates**: After large multi-platform jobs, run `agent-reach check-update`. If an update is available, inform the user with the official update link without interrupting current execution.

---

## 🧭 Routing Table

| Intent & Platform | Category | Reference Runbook |
| :--- | :--- | :--- |
| Web search / AI search / Technical docs | `search` | [references/search.md](references/search.md) |
| Reddit / Twitter (X) / Xiaohongshu / Bilibili / V2EX / Facebook / Instagram | `social` | [references/social.md](references/social.md) |
| Jobs / Recruitment / LinkedIn / Boss Zhipin | `career` | [references/career.md](references/career.md) |
| GitHub repos / Code search | `dev` | [references/dev.md](references/dev.md) |
| Web page extraction / Articles / RSS | `web` | [references/web.md](references/web.md) |
| YouTube captions / Video transcription / Xiaoyuzhou podcast ASR | `video` | [references/video.md](references/video.md) |
| Xueqiu / Stocks / Financial quotes & sentiment | `finance` | [references/finance.md](references/finance.md) |

---

## ⚡ Zero-Config Quick Commands

```bash
# 1. Exa AI web search
mcporter call exa.web_search_exa query="query" numResults=5

# 2. Universal web reader (Jina Reader Markdown)
curl -s "https://r.jina.ai/https://example.com/article"

# 3. GitHub repository search with high-density table projection
gh search repos "query" --sort stars --limit 10 --json name,stargazersCount,description,url | \
  python3 ~/.gemini/config/skills/agent-reach/scripts/reach_filter.py github --table

# 4. V2EX Hot topics (direct fetch, compact table, ~150 tokens)
python3 ~/.gemini/config/skills/agent-reach/scripts/reach_filter.py --fetch v2ex-hot -n 10

# 5. Bilibili video search with table projection
bili search "query" --type video -n 5 | \
  python3 ~/.gemini/config/skills/agent-reach/scripts/reach_filter.py bilibili --table
```

---

## 🛡️ Token Shield & Table Projection (Kem Architecture)

Raw JSON/YAML platform payloads (20KB–50KB) must never be dumped raw into the agent context. Use `reach_filter.py` for deterministic field projection, row capping, and disk buffering:

### CLI Piping
```bash
FILTER=~/.gemini/config/skills/agent-reach/scripts/reach_filter.py

# Reddit search (sub, score, comments, title projection)
rdt search "query" --json | python3 $FILTER reddit -p sub,score,comments,title -n 10

# Twitter / X timeline
twitter feed -n 20 --json | python3 $FILTER twitter -p author,likes,text -n 10

# Xiaohongshu notes search
opencli xiaohongshu search "query" -f json | python3 $FILTER xhs -p title,author,likes -n 5

# Disk buffering (caches raw JSON to disk, emits 1-line receipt + compact table)
curl -s "https://www.v2ex.com/api/topics/hot.json" | python3 $FILTER v2ex -o /tmp/v2ex_hot.json -n 10
```

### Omnicli Code Mode (`omnicli exec` Python API)
Inside `omnicli exec` sandboxes, invoke `reach_filter.filter_data` directly as Python code:
```python
import sys
sys.path.insert(0, "/home/rodri/.gemini/config/skills/agent-reach/scripts")
import reach_filter

# Filter raw data into a clean tuple: (rows_list, markdown_table_str)
rows, table = reach_filter.filter_data(
    raw_payload,
    platform="reddit",
    project=["sub", "score", "comments", "title"],
    limit=10,
    out="/tmp/reddit_results.json"
)
print(table)
```

---

## 🔑 Authenticated Platforms

Check `agent-reach doctor --json` to determine the active backend:

```bash
# Twitter search (twitter-cli preferred; see references/social.md for fallbacks)
twitter search "query" -n 10

# Reddit (OpenCLI or rdt-cli)
opencli reddit search "query" -f yaml   # desktop
rdt search "query" --limit 10           # server / CLI

# Xiaohongshu (OpenCLI with existing Chrome session)
opencli xiaohongshu search "query" -f yaml

# Facebook & Instagram (OpenCLI)
opencli facebook search "query" -f yaml
opencli instagram search "query" -f yaml
opencli instagram user USERNAME -f yaml

# Boss Zhipin (Dedicated Chrome CDP on :9222)
boss --browser-source existing-browser --cdp-url http://localhost:9222 search "query"
```

---

## 💻 Environment Diagnostics

> Default workstation Python environment is conda `dl`; if `agent-reach` is not on standard PATH, prefix with `conda run -n dl agent-reach`.

```bash
# Check channels and active backends
conda run -n dl agent-reach doctor --json
```

---

## 📂 Workspace Rules

**Do not write scrapers or raw output in the project repository.**
- Use `/tmp/` for temporary JSON cache buffers.
- Use `~/.agent-reach/` for persistent credentials and session configurations.
