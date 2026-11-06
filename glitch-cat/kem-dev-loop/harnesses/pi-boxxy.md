# 📟 Hooking Kem Doctrine into Pi Agent & Boxxy Claw (`pi-boxxy.md`)

> *"Code decides wherever it can; a model should only judge when it's absolutely necessary."*  
> — Kem Glitch, *Code Decides*

Pi Agent and Boxxy Claw are terminal-based, local agent harnesses running directly on the Linux workstation. They receive synchronized skill trees via `sync-skills` and interact directly with system shells, local model daemons, and workstation tools.

---

## 🏛️ Pi & Boxxy Host Invariants

1. **Rsync Propagation & Hot-Reload:** Skills in Pi Agent (`~/.pi/agent/skills/`) and Boxxy Claw (`~/.config/boxxy-terminal/boxxyclaw/skills/`) are synchronized views of `~/src/my-agent-skills`. Changes in upstream are pushed via `sync-skills` and hot-reloaded without restarting the host terminal.
2. **Direct CLI Tool Access:** Pi and Boxxy execute tools as standard system processes. All declared CLI executables (e.g. `jev`, `audiocpp`, `ocr`, `notes-index`, `cgate`) in `~/.local/bin` are directly invokable.
3. **Local GPU Daemon Access:** Zero network latency to local inference ports:
   - Genesis Coder: `http://127.0.0.1:8080`
   - Nemotron Audio: `http://127.0.0.1:8081`
   - Jev Decision: `http://127.0.0.1:8083`
   - OXR / CrispEmbed: `http://127.0.0.1:8084`
   - LightOnOCR: `http://127.0.0.1:8085`

---

## ⚙️ Implementing Kem's Moves in Pi & Boxxy

### 1. Terminal Step Ledgers
Run pipeline steps sequentially or partitioned, dumping intermediate states to local run folders:
```bash
mkdir -p .harness/runs/run_01
# Step 1: Deterministic classification
python3 scripts/classify.py > .harness/runs/run_01/step_01.json
# Step 2: Code modification
python3 scripts/build_slice.py > .harness/runs/run_01/step_02.diff
# Step 3: Test execution and assertion
pytest --json-report --json-report-file=.harness/runs/run_01/step_03.json
```

### 2. Fast Verification with JEV CLI
Use `jev` directly from the terminal for classification, gating, and visual scoring:
```bash
jev bool "Does this diff change database schema without a migration?" \
  --context "$(git diff HEAD~1)"
```

### 3. Guard-Hooks in Terminal
Prevent catastrophic deletions by wrapping command execution in `guard_check.py`:
```bash
guard_check.py --command "$COMMAND" && eval "$COMMAND"
```

---

## 🚫 Anti-Patterns to Avoid
- Editing files directly inside `~/.pi/agent/skills/` or `~/.config/boxxy-terminal/` (these are downstream rsync targets; edit `~/src/my-agent-skills` instead).
- Slurping raw logs into context when `notes-index` or `cgate` can slice the relevant spans.
