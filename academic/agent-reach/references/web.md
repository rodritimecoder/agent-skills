# Web Page Extraction (`references/web.md`)

Universal web article extraction, Jina Reader, and RSS feeds.

---

## 🌐 Jina Reader (Zero Config)

Converts any public web page into clean, LLM-friendly Markdown.

```bash
# Read any URL
curl -s "https://r.jina.ai/https://example.com/article"

# Extract documentation page
curl -s "https://r.jina.ai/https://docs.rs/tokio/latest/tokio/"
```

**Key Advantages:**
- Bypasses basic client-side rendering traps.
- Strips ads, navigation clutter, cookie modals, and tracking scripts.
- Pure Markdown output ready for immediate token-efficient agent ingestion.

---

## 📰 Web Reader (MCP)

When local MCP tooling is preferred:

```bash
# Read web page in Markdown format
mcporter call web-reader.webReader url="https://example.com"

# Retain image links
mcporter call web-reader.webReader url="https://example.com" retain_images=true
```

---

## 📡 RSS Feeds

```bash
# Read RSS feed content
opencli rss read "https://example.com/feed.xml" --limit 5
```
