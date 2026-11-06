---
name: subagent-spaces

description: "Isolated CPU-pinned containerized sandbox environments for autonomous subagents using rootless Podman. Partitions 16 CPU threads into dedicated worker slots, mounts disposable workspaces, isolates untrusted builds and scripts, and connects directly to local inference endpoints. Use when a build, a test suite, or an untrusted script must run locally without touching the host, or when parallel workers need pinned CPU and memory — for a throwaway cloud VM instead, use gh-action-subagent."

compatibility: "Requires the Podman container runtime, configured for rootless operation."
allowed-tools: "Bash(subagent-spaces:*) Bash(podman:*) Bash(python3:*) Read Write"
---

# Subagent Spaces (`subagent-spaces`)

Isolated, CPU-pinned containerized sandbox environments for autonomous subagents running locally via rootless Podman.

Instead of running builds, tests, or untrusted code directly on the host or incurring cloud VM latency, `subagent-spaces` partitions your CPU threads into dedicated worker spaces with strict memory quotas, disposable workspace mounts, and zero blast-radius.

---

## 🖥️ CPU Core Topology (16-Thread Ryzen Substrate)

* **Host Desktop Reserve (`0–3`)**: Cores 0, 1, 2, 3 (4 threads) reserved exclusively for Host OS, Desktop, Display Server, and GPU drivers.
* **Worker Pool (`4–15`)**: 12 dedicated threads that can be allocated as:
  * **1-Thread Micro-Spaces**: Up to **12 parallel subagents** running concurrently (`--cpus 1` or `--cores 4` through `15`).
  * **Coarse Worker Slots**: 3 quad-core worker slots (`Slot 1: 4–7`, `Slot 2: 8–11`, `Slot 3: 12–15`).
  * **Full Throttle (`all`)**: All 12 worker threads (`4–15`) and 12 GB RAM for heavy compiles.

---

## 🚀 Quick Usage

### 1. View Real-Time Thread Grid & Slots
Displays real-time status of all 16 threads (HOST, IDLE, BUSY) and worker slot occupancy:
```bash
subagent-spaces slots
```

### 2. Run 1-Thread Micro-Spaces
Give a subagent exactly 1 core/thread and 1GB RAM:
```bash
# Auto-allocate 1 idle core from worker pool (4-15)
subagent-spaces run --cpus 1 -- pytest

# Pinned to specific core (e.g. Core 4 only)
subagent-spaces run --cores 4 -m 512m -- python3 script.py

# Spawn multiple parallel 1-thread subagents concurrently
subagent-spaces run --cores 4 -d -w ./ws1 -- npm test
subagent-spaces run --cores 5 -d -w ./ws2 -- pytest
subagent-spaces run --cores 6 -d -w ./ws3 -- make
```

### 3. Run Predefined Slots or High-Throttle Mode
```bash
# Quad-core Slot 1 (Cores 4-7, 4 GB RAM)
subagent-spaces run --slot 1 -w ~/projects/app --ro -- cargo check

# High-Throttle 12-thread compilation
subagent-spaces run --slot all -- make -j12
```

### 4. Interactive Shell into a Space
```bash
# Attach interactive bash to Core 4, Slot 1, or container name
subagent-spaces enter 4
```

### 5. Inspect Running Spaces
```bash
subagent-spaces ps
```

### 6. Stop or Prune Spaces
```bash
# Stop a specific space by core or container ID
subagent-spaces stop 4

# Clean up all active spaces
subagent-spaces prune
```

### 7. Diagnostics & Diagnostics
```bash
subagent-spaces doctor
```

---

## 🌐 Local Inference Connectivity
By default, spaces use `--network host`, enabling sandboxed subagents to seamlessly query your workstation's local LLM and speech servers:
* `http://127.0.0.1:8080` — Primary LLM (Qwen 35B)
* `http://127.0.0.1:8081` — Nemotron 3.5 ASR (`audiocpp-asr`)
* `http://127.0.0.1:8083` — h2o-lightning-4b Decision (`jev`), vision via `mmproj`
* `http://127.0.0.1:8085` — LightOnOCR-3-0.8B (`ocr-cli`)
