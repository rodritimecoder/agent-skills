# 🛠️ T3 Code Harness Guide for omnicli

> *"T3 Code is an agentic IDE powered by the Agent Client Protocol (ACP); the agent it drives does the tool calling."*

T3 Code has **no omnicli integration of its own** — its provider drivers are `codex`, `claudeAgent`, `opencode`, `antigravity`, and `pi`, and none of them knows the catalogue exists. When the provider is **OpenCode** (the default here), the integration point is OpenCode's plugin surface: a native tool registration plus a routing hook. That is what this guide wires.

---

## ⚡ Three ways omnicli reaches a T3 session

### Path 1 — Native tools (default; install once)

A global OpenCode plugin registers three catalogue verbs and injects the routing rule at every model call. Because T3 enumerates the OpenCode tool list, the verbs appear in T3, and because they are registered with `codemode: true`, they are also callable inside OpenCode's Code Mode as `tools.omnicli.*`.

```bash
mkdir -p ~/.config/opencode/plugins
ln -sf ~/src/my-agent-skills/orchestration/omnicli/plugin/omnicli-route.js \
  ~/.config/opencode/plugins/omnicli-route.js
opencode reload          # or restart T3 Code / its OpenCode provider
omnicli harness verify t3-code
```

| Tool | What it does |
|---|---|
| `omnicli_search` / `tools.omnicli.search` | Rank catalogued tools by intent. Use **before** hand-writing a script or reading a skill. |
| `omnicli_invoke` / `tools.omnicli.invoke` | Run one tool; 8 KB cap, optional `project` fields and `buffer`. |
| `omnicli_exec` / `tools.omnicli.exec` | Run a JavaScript plan in one turn; `node:vm` under bubblewrap, 100-call budget, optional memory cap. |

The plugin also:

- injects a short `[omnicli route]` block into the system instructions on each model call;
- denies `read`/`grep`/`glob`/`list` (and read-only shell verbs) against `~/src/my-agent-skills/**` until the session has called `omnicli_search`/`omnicli_invoke`/`omnicli_exec` — the anti-pattern `AGENTS.md` names;
- exempts a session whose project root is inside the skills repo, and honours `~/src/my-agent-skills/.omnicli-route-exempt` for maintenance from another project;
- appends one JSON row per call to `~/.local/share/omnicli/route.jsonl`. Summarise it with `python3 scripts/route_stats.py` (bypass rate, denials, catalogue calls).

**The collision to know:** inside OpenCode Code Mode, the bare `search()` helper indexes *tool names*. The catalogue search is `tools.omnicli.search`. The injected routing block says so; do not rename it.

### Path 2 — Direct CLI (`omnicli` on the shell)

Still valid for one-shot commands and scripts outside the model loop:

```bash
omnicli search "transcribe zoom lecture"
omnicli describe zoom-recorder/scripts/zoom_download
omnicli invoke zoom-recorder/scripts/zoom_download \
  --omni-max-bytes 8000 --omni-project "status,transcript_path" \
  -- --url "https://zoom.us/rec/..."
```

### Path 3 — JavaScript Code Mode (`omnicli exec`)

For multi-step plans and heavy parsing, run sandboxed JavaScript in one turn with zero file staging overhead:

```bash
# Inline execution (the bindings are already globals)
omnicli exec -c 'const rows = await search("audio", 2); console.log(rows)'

# Piped stdin execution
cat << 'EOF' | omnicli exec -
import { search } from "omnicli_tools";
const hits = await search("audio transcription", 3);
console.log(hits);
EOF

# File execution
omnicli exec plan.mjs --sandbox write
```

```js
import { search, zoom } from "omnicli_tools";

const hits = await search("audio transcription", 3);
const result = zoom({ url: "https://zoom.us/rec/share/abc", format: "md" });
console.log(result.output.slice(0, 300));
```

Scripts run through `node:vm` inside `bwrap`, against generated
`omnicli_tools.mjs` bindings and their `omnicli_tools.d.ts` declarations. Use
`strict` when the plan handles untrusted input; `--max-calls` and `--mem-limit`
(a JS heap cap plus a floored `RLIMIT_AS`) are enforced inside the sandbox.
Python plans are retired — `omnicli exec plan.py` exits 2 with the migration
text.

---

## 🖼️ Visual Presentation & Previews

T3 provides `html_preview` and `html_render`. When omnicli produces tabular, diagnostic, or graphical reports:
1. Write an HTML report (e.g. `omnicli status --json` rendered to a dashboard).
2. Pass the file path to `html_preview`, then `html_render`.
3. Never start a background HTTP server for a static result.

---

## 🏛️ T3 Code Host Invariants

1. **Reactive wakeups:** never `sleep` or poll; let T3 resume the turn.
2. **Delegate worktrees:** pass `isolation: "worktree"`; never run `git worktree add` for a child.
3. **Artifacts:** keep traces and intermediate outputs in `<appDataDir>/brain/<conversation-id>/scratch/` or `.omnicli/`.
4. **Links:** reference threads with their markdown `link` verbatim.

---

## 🔍 Verification

```bash
omnicli harness verify t3-code     # 6 checks, including native_tool_plugin
omnicli harness config t3-code     # the install block above
python3 orchestration/omnicli/scripts/route_stats.py
```

`native_tool_plugin` fails when the symlink is missing or the plugin no longer parses — i.e. the check tracks the wiring, not the documentation.
