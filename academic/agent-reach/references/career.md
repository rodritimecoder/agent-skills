# Career & Recruitment Research (`references/career.md`)

LinkedIn jobs and Boss Zhipin (Boss直聘) recruitment intelligence.

---

## 💼 LinkedIn Jobs

```bash
# Search job openings via OpenCLI
opencli linkedin search "Software Engineer" -f yaml

# Read specific job description
opencli linkedin job "JOB_ID" -f yaml
```

---

## 👔 Boss Zhipin (Boss直聘) via Chrome CDP

Boss Zhipin enforces strict anti-bot mechanisms. It operates exclusively through a dedicated Chrome instance running on port `:9222`.

### 1. Diagnosis & Connection Check
Never judge login state by `boss status` alone or by anti-bot verification challenge URLs (`security-check`).
Use `agent-reach doctor` cookie detection (`wt2` cookie):

```bash
# Check Boss Zhipin channel status
agent-reach doctor --json
```

### 2. Search Command
Always specify `--browser-source existing-browser` and `--cdp-url http://localhost:9222`:

```bash
boss --browser-source existing-browser --cdp-url http://localhost:9222 search "Rust Developer"
```

### 3. Safety Guard
If `ENVIRONMENT_RISK` is returned: **Immediately stop execution.** Do not refresh, do not retry automatically, and do not attempt re-login.
