# 📦 Boxxy Claw & Terminal Harness Guide for omnicli

> *"Boxxy Claw is a terminal companion and agent harness featuring hot-reloaded skill discovery, SQLite WAL state management, and bubblewrap sandboxing."*

This guide specifies how `omnicli` integrates with **Boxxy Claw** to ensure memory safety, sandboxed execution, and multi-agent coordination.

---

## ⚡ Integration Architecture in Boxxy

Boxxy operates with:
1. **Claw Discovery:** `~/.config/boxxy-terminal/boxxyclaw/skills/` is continuously monitored. Upstream edits synced via `sync-skills` are hot-reloaded into active Boxxy terminals without session restarts.
2. **Execution Environment:** Commands run within user terminal sessions or rootless sandboxes.

---

## 🛡️ Sandboxed Plan Execution (`omnicli exec`)

Boxxy agents frequently generate Python multi-step scripts to execute complex tasks. `omnicli` provides bubblewrap-based sandboxing natively matched to Boxxy's containment requirements:

```bash
# Execute plan in write-isolated bubblewrap container
omnicli exec plan.py --sandbox write

# Execute plan in strict isolation (network unshared, home masked, IPC locked)
omnicli exec plan.py --sandbox strict
```

### Sandbox Guarantees

| Mode | Filesystem | Network | Tool Access |
| :--- | :--- | :--- | :--- |
| **`write`** | Workspace & `/tmp` writable; root `/` read-only | Normal | Direct |
| **`strict`** | Home masked; ephemeral `/tmp`; root `/` read-only | Unshared (offline) | Crossed via UNIX bridge socket (`bridge.sock`) |
| **`none`** | Host environment | Normal | Direct |

In `strict` mode, the plan holds zero credentials and cannot open network sockets; every tool call crosses an authenticated UNIX socket to the parent gateway.

---

## 💾 SQLite Catalog Concurrency & WAL Safety

Boxxy runs multiple worker terminals simultaneously. `omnicli`'s SQLite catalog (`~/.local/share/omnicli/catalog.db`) uses Write-Ahead Logging (WAL):
- Concurrent readers never block writers.
- Read operations from multiple Boxxy terminals take `<2ms`.
- Atomic enable/disable decisions (`omnicli policy`) are serialized safely across processes.

---

## 🩺 Real-Time Telemetry & Health Checks

Boxxy companions display status widgets. `omnicli status --json` emits structured telemetry reporting daemon availability, catalog freshness, and retrieval tiers:

```bash
omnicli status --json
```

```json
{
  "tailnet_ip": "100.83.178.106",
  "catalog": {
    "skills": 54,
    "tools": 494,
    "freshness": "fresh",
    "tier": "bm25"
  },
  "services": {
    "genesis_35b": "offline",
    "decision_8083": "offline",
    "audiocpp_8081": "offline"
  }
}
```

---

## 🏛️ Boxxy Host Invariants

1. **Hot-Reload View:** Files in `~/.config/boxxy-terminal/boxxyclaw/skills/` are managed by `sync-skills`. Never make untracked direct modifications there.
2. **Memory Safety:** Enforce `--omni-max-bytes` on all tool outputs to protect Boxxy's memory database from bloat.

---

## 🔍 Verification

Run the automated verification suite to confirm Boxxy Claw integration:

```bash
omnicli harness verify boxxy
```
