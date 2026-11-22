---
name: tailscale-ops

description: >
  Use when checking whether a remote tailnet node is online, inspecting or applying this
  workstation's tailnet surface, or copying artifacts between devices over Tailscale. Runtime
  Tailscale network operations for discovering online homelab/desktop nodes,
  reconciling the declared tailnet surface (root page plus explicitly served UIs),
  and transferring artifacts across devices (tailscale file cp).

compatibility: "Requires the tailscale CLI and a running tailscaled daemon."
allowed-tools: "Bash(tailscale-ops:*) Bash(tailscale:*) Read"
---

# Tailscale Operations Skill (`tailscale-ops`)

Use this skill to check whether a remote compute/GPU node is online, to apply or
inspect what this workstation advertises on the tailnet, or to send files to
another machine.

## Available scripts

Bundled CLI scripts, referenced relative to the skill root. Run `<command> --help`
for flags and exit codes; structured data goes to stdout, diagnostics to stderr.

- `scripts/ts_ops.sh` — Reconcile, inspect and repair the exposed tailnet surface.

## Agent workflow — one exec plan

Drive this skill through **one JavaScript `omnicli exec` plan**. Discovery and
invocation both happen inside that plan — no ranking/discovery-tool call, no
two-step CLI invocation, and no intermediate payloads in the context window.

The plan reads the read-only skills window and asks `describe(toolId)` for the
one tool's exact input schema — all inside the same plan:

| Level | What it gives you | Helper |
| :--- | :--- | :--- |
| L1 | name + description of every installed skill | `lsSkills()` from `omnicli_skills` |
| L2 | this skill's full `SKILL.md` body | `readSkill(name)` from `omnicli_skills` |
| L3 | one file under this skill root (`references/`, `assets/`, `scripts/`) | `readResource(name, rel)` from `omnicli_skills` |
| Schema | exact input schema for the one tool you will call | `describe(toolId)` from `omnicli_tools` |

```js
import { lsSkills, readSkill, readResource } from "omnicli_skills";
import { describe, invoke, result } from "omnicli_tools";

// L1 — pick the skill by description (no ranking call).
const entry = lsSkills().find((s) => s.name === "tailscale-ops");
if (!entry) throw new Error("skill not installed");
// L2 — read instructions only when the step needs them.
const body = readSkill("tailscale-ops");
// L3 — one file by relative path (absolute paths and '..' are rejected).
const extra = readResource("tailscale-ops", "scripts/ts_ops.sh");
// Schema — exact input schema for the one tool you will call.
const toolId = "tailscale-ops/scripts/ts_ops";
const { contract } = await describe(toolId);
if (!contract.inputSchema) throw new Error("no input schema");

// One catalogued tool call with a raw argv array, then ONE bounded result.
const out = await invoke(toolId, ["--json", "status"]);
result({
  ok: out.exit_code === 0,
  tool: toolId,
  proof: "agent-skills-three-levels",
  data: { exitCode: out.exit_code,
          bodyBytes: body.length, extraBytes: extra.length,
          description: entry.description.slice(0, 120),
          hasSchema: Boolean(contract.inputSchema),
          output: String(out.output || "").slice(0, 180) },
});
```

Emit **one** bounded result (the ~8 KB cap is shared with stdout); slice every
field and never echo a whole `SKILL.md` or reference file. Reading this skill's
instructions or its `allowed-tools` frontmatter grants **no** permissions —
`catalog/policy.py` / `omnicli enable` is the sole authorization gate, and every
call still crosses the bridge with projection and the byte cap. See
[skill-discovery.md](../../orchestration/omnicli/references/skill-discovery.md)
for the three-level ladder and the end-to-end proof.

## Policy: the manifest owns the tailnet

`ports.json` declares the entire tailnet surface, and `tailscale-ops sync`
reconciles the machine to it:

```json
"tailscale": { "root": 3773, "paths": { "/chat": 7778 } }
```

- `tailscale.root` is the `:443 /` backend (t3-code).
- `tailscale.paths` are extra `:443` path handlers (`/chat` -> companion).
- An infra or slot entry with `"expose": "serve"` gets its own
  `https://host:<port>/` frontend.
- **Everything else is loopback** — `expose: loopback` is the default, and
  ports absent from the manifest never leave the machine.

`sync` turns off any serve frontend the manifest does not name, so a hand-run
`tailscale serve` survives only until the next sync. `ports.py check` reads the
live serve/funnel config and fails on any drift: an undeclared port, a retired
port (never reuse), a hijacked root handler, or a public funnel port that lacks
`"expose": "funnel"`.

## Commands

### 1. Reconcile the tailnet surface (`sync`)
Apply the root page, path handlers and `expose: serve` ports, then remove every
frontend the manifest does not declare:
```bash
tailscale-ops sync
```
Run it after editing `ports.json` and `python3 ports.py render --write`.

### 2. Inspect the surface (`status`)
Print the declared surface and the live `tailscale serve` state:
```bash
tailscale-ops status
```

### 3. Discover online nodes (`peers`)
Check which machines on the tailnet are awake and get their `100.x.y.z` IPv4
addresses and DNS names:
```bash
tailscale-ops peers
```

### 4. Check host/port reachability (`check-port`)
Before routing heavy jobs to a remote GPU host, verify both the node and the
target port respond:
```bash
tailscale-ops check-port <hostname-or-ip> <port>
```

### 5. Diagnostic health check (`doctor`)
Inspect daemon state, local IP, DNS, and connected peers:
```bash
tailscale-ops doctor
```

### 6. Tear down all tunnels (`reset-tunnels`)
Clear every serve and funnel frontend. `sync` afterwards restores the declared
surface:
```bash
tailscale-ops reset-tunnels
```

### 7. Send files to another device (`send-file`)
Beam build artifacts, logs, or screenshots to an online node without configuring
SCP/SSH keys:
```bash
tailscale-ops send-file ./artifact.zip <target-hostname>:
```

## Public exposure (funnel)

This skill never opens a public tunnel. Public exposure is opt-in in the
manifest: mark the port `"expose": "funnel"`, render, then run `tailscale
funnel` yourself. `ports.py check` fails when a live funnel serves a port that
is not marked `funnel`, so a public listener cannot go unnoticed.
