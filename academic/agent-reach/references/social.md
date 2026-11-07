# Social Media Research (`references/social.md`)

Multi-platform intelligence: Reddit, Twitter/X, Xiaohongshu (RED), Bilibili, V2EX, Facebook, and Instagram.

---

## 🛡️ Zero-Overhead Token Shield

All social media feeds return bulky payloads (20KB–50KB). Always route output through `reach_filter.py`:

```bash
FILTER=~/.gemini/config/skills/agent-reach/scripts/reach_filter.py
```

---

## 🤖 Reddit Research

```bash
# Search subreddits or topics (project: sub, score, comments, title)
rdt search "query" --json | python3 $FILTER reddit -p sub,score,comments,title -n 10

# Read thread comments
rdt comments "THREAD_ID" --json | python3 $FILTER reddit -n 15

# Desktop alternative (via OpenCLI)
opencli reddit search "query" -f yaml
```

---

## 🐦 Twitter / X

> Note: Never echo or export raw credentials in command prompts. Set `TWITTER_AUTH_TOKEN` and `TWITTER_CT0` in subshell environments when invoking `twitter-cli`.

```bash
# Search tweets
twitter search "query" -n 10

# Read user feed with table projection
twitter feed -n 20 --json | python3 $FILTER twitter -p author,likes,text -n 10

# Desktop alternative (OpenCLI)
opencli twitter search "query" -f yaml
```

---

## 📕 Xiaohongshu / RED (小红书)

> OpenCLI attaches to your existing Chrome profile session. It never automates login or extracts passwords.

```bash
# Search notes (project title, author, likes)
opencli xiaohongshu search "query" -f json | python3 $FILTER xhs -p title,author,likes -n 5

# Read note content
opencli xiaohongshu note "NOTE_ID" -f yaml
```

---

## 💬 V2EX Community

```bash
# Direct fetch hot topics (no curl needed, ~150 tokens)
python3 $FILTER --fetch v2ex-hot -n 10

# Fetch specific node (e.g. create, dev, python)
python3 $FILTER --fetch v2ex-node --node python -n 10

# Buffer to disk for complete analysis without context bloat
python3 $FILTER --fetch v2ex-hot -o /tmp/v2ex_hot.json -n 10
```

---

## 👥 Facebook & Instagram (OpenCLI)

```bash
# Facebook public search & group posts
opencli facebook search "query" -f yaml
opencli facebook groups -f yaml

# Instagram user discovery & recent posts
opencli instagram search "query" -f yaml
opencli instagram user USERNAME -f yaml
```
