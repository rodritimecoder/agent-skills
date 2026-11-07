# Financial Quotes & Market Sentiment (`references/finance.md`)

Xueqiu (雪球) stock quotes, market search, and investor sentiment.

---

## 📈 Stock Quotes & Ticker Search

```bash
FILTER=~/.gemini/config/skills/agent-reach/scripts/reach_filter.py

# Search tickers and company profiles
opencli xueqiu search "NVIDIA" -f json | python3 $FILTER generic --table

# Get real-time stock quote
opencli xueqiu quote "NVDA" -f json

# Hot community discussions & trending stocks
opencli xueqiu hot -f json | python3 $FILTER generic --table -n 10
```

---

## ⚡ Fallback Chain

1. Primary: `opencli xueqiu ...`
2. Fallback: If OpenCLI Xueqiu adapter is unconfigured or rate-limited, query market news via Exa search `mcporter call exa.web_search_exa query="NVDA stock price earnings"`.
