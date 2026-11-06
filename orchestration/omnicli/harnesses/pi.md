# 🥧 Pi Agent Harness Guide for omnicli

> *"Pi Agent is a terminal-based, local agent harness running directly on the Linux workstation with fast feedback loops and hot-reloaded skills."*

This guide specifies how `omnicli` integrates with **Pi Agent** to provide late-binding tool discovery and tight token budget controls.

---

## ⚡ Integration Architecture in Pi Agent

Pi Agent operates with two primary mechanisms:
1. **Rsync Synchronization:** `sync-skills` distributes dereferenced skill directories into `~/.pi/agent/skills/`.
2. **Direct CLI Tool Execution:** Pi executes tools as standard host processes via its bash execution tool.

---

## 🚀 Interactive CLI Workflows

In Pi Agent's interactive terminal loops, latency and context token consumption are the primary bottlenecks. `omnicli` eliminates both:

### Fast Discovery (Sub-10ms)

```bash
# Natural-language search returns compact ranked candidates
omnicli search "extract slides from zoom video"
```

Output is cleanly formatted text (<350 tokens) rather than raw JSON schemas:

```
🔍 [omnicli] intent: 'extract slides from zoom video'   tier=bm25(gated)

  1. zoom-recorder   score=0.91  lex=34.25
       Download transcripts, audio, and visual keyframe slides...
       → omnicli tools zoom-recorder
```

### Bounded Invocations

Pi Agent's context window can easily degrade if a CLI tool prints megabytes of logs or raw HTML. `omnicli invoke` enforces a hard byte ceiling:

```bash
# Keep only essential fields and cap output to 4000 bytes
omnicli invoke academic-icm/scripts/fetch_course \
  --omni-project "id,course_name,assignments" \
  --omni-max-bytes 4000 \
  -- --course-id 12345
```

If the payload exceeds 4000 bytes, `omnicli` provides an exact head+tail preview and buffers the full payload to disk (`/tmp/...`).

---

## 🧠 Local Daemon Access for Pi

Pi connects directly to local inference endpoints without network round-trips:

```bash
# Query Genesis 35B coder locally
omnicli llm "Refactor this function to be thread-safe: $(cat utils.py)"

# Non-generative bool decision
omnicli decide "Git status shows uncommitted files in production branch" \
  "Should we halt deployment?"
```

---

## 🏛️ Pi Agent Host Invariants

1. **Source of Truth:** Never edit files inside `~/.pi/agent/skills/` directly. Always edit the canonical checkout in `~/src/my-agent-skills/` and propagate changes with `sync-skills`.
2. **Token Economy:** Never dump raw logs or full files into chat. Use `--omni-project` and `--omni-buffer` to keep Pi's context sharp.

---

## 🔍 Verification

Run the automated verification suite to confirm Pi Agent integration:

```bash
omnicli harness verify pi
```
