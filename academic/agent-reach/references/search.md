# Search Tools (`references/search.md`)

Exa AI Search Engine and Web Discovery.

---

## 🔍 Exa AI Search

High-precision AI search engine designed for technical documentation, code snippets, and authoritative web sources.

```bash
# General web search
mcporter call exa.web_search_exa query="query" numResults=5

# Technical documentation & code examples
mcporter call exa.web_search_exa query="fastapi dependency injection example" numResults=5
```

### Usage Scenarios

| Scenario | Parameter Pattern |
| :--- | :--- |
| General web search | `web_search_exa(query: "...", numResults: 5)` |
| Technical / framework documentation | `web_search_exa(query: "framework API code example", numResults: 5)` |

> Note: `get_code_context_exa` is deprecated and unregistered by default. Use `web_search_exa` for code questions; for exact repository contents, use GitHub search in `dev.md`.

---

## ⚡ Fallback Chain

1. Primary: `mcporter call exa.web_search_exa ...`
2. Fallback: If Exa quota is exhausted or MCP is unavailable, use standard curl with Jina Reader or duckduckgo search via OpenCLI.
