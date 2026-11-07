# Developer & Code Tools (`references/dev.md`)

GitHub repository discovery, code search, and issues exploration.

---

## 🐙 GitHub Search & Table Projection

Always project fields through `reach_filter.py github --table` to prevent dumping 30KB GitHub REST JSON payloads into context:

```bash
FILTER=~/.gemini/config/skills/agent-reach/scripts/reach_filter.py

# Search repositories sorted by stars
gh search repos "query" --sort stars --limit 10 --json name,stargazersCount,description,url | \
  python3 $FILTER github --table

# Search issues with open status
gh search issues "bug label:bug repo:owner/repo" --state open --limit 5 --json number,title,author,url | \
  python3 $FILTER github --table

# Code search across repositories
gh search code "symbol or function name" --limit 5 --json path,repository,url | \
  python3 $FILTER github --table
```

---

## ⚡ Fallback Chain

1. If `gh` is authenticated: `gh search repos ...`
2. If `gh` is unauthenticated: Fall back to Exa AI search `mcporter call exa.web_search_exa query="site:github.com ..."` or `curl -s "https://api.github.com/search/repositories?q=..."`.
