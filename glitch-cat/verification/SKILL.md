---
name: verification

description: >
  Hands-and-eyes verification gate (Glitch Cat Club / Kem Glitch; Reel DfAIPrAtteM).
  Opens the app like a person on a real viewport, watches what the browser actually did
  behind the screen (console, exceptions, failed requests), compares before/after pixels,
  walks every Storybook state, and reports what real users are hitting — then emits one
  PASS/FAIL artifact instead of a claim. Use when an agent says a UI change is done, when a
  button or layout must be proven on mobile, when a flow looks fine but an order or action
  silently fails, when a change must not move a single pixel, or when you need a repeatable
  check the next agent can run instead of re-improvising. Also forges a project-local,
  harness-agnostic `verify-<app>` from the five-question repo interview (`forge`), and proves
  the gate can fail by breaking one feature on purpose (`control`). Complements frontend-uat
  (single sub-second journey) and playwright (the driver underneath).

metadata:
  bins: verify-app
compatibility: "Needs a Chromium CDP endpoint on :9222 (playwright-rs daemon start) for the hands and eyes layers, ffmpeg for the pixel layer, and optionally a running Storybook plus SENTRY_AUTH_TOKEN. Python 3.10+; no third-party Python packages."
allowed-tools: "Bash(verify-app:*) Bash(python3:*) Bash(playwright-rs:*) Bash(ffmpeg:*) Read Write"
---

# Verification Gate (`verification`)

Reel [`DfAIPrAtteM`](https://www.instagram.com/reel/DfAIPrAtteM/): *"Verification means your agents check their own work the way you would by actually using it. That's what moves you up the trust ladder so it can run on its own for longer and hand back verified work."*

Autonomous verification turns claims into evidence. Instead of checking intent against intent in a code diff, the gate dispatches trusted input at real pixel coordinates over CDP and observes the actual browser behavior.

---

## 📚 Documentation & References (Late-Binding)

Read the specific reference card when needed for details:

| Topic | Reference Document | Contents |
| :--- | :--- | :--- |
| **Architecture** | [references/architecture.md](references/architecture.md) | Trust ladder, 5 layers, CDP substrate, evidence schema |
| **Pass Contract** | [references/pass-schema.md](references/pass-schema.md) | The 5 questions, `pass.json` schema, Journey & Expectation DSL |
| **Forge & Control** | [references/forge.md](references/forge.md) | Repo scaffolding (`forge`), adoption (`--adopt`), fault injection (`control`) |
| **Gotchas** | [references/gotchas.md](references/gotchas.md) | Viewports, occluded clicks, text-transform, canvas eval, traps |

---

## 🖐️👁️ The Five Layers

1. **`hands`**: CDP trusted mouse & keyboard input at real coordinates (`elementFromPoint` geometry).
2. **`eyes`**: CDP `Runtime`, `Log`, `Network` protocol events (status codes, exceptions, console errors).
3. **`pixels`**: FFmpeg byte-exact decode & visual regression against committed baselines.
4. **`states`**: Storybook crawler testing component mount states against `/index.json`.
5. **`errors`**: Production Sentry unresolved issues API check.

---

## 🛠️ Quick Commands

```bash
# 0. Check layer availability (CDP on :9222, ffmpeg, Storybook, Sentry)
verify-app doctor --json

# 1. Ask the 5 questions & initialize .verify/pass.json skeleton
verify-app ask --out .verify

# 2. Prove a journey on a real mobile viewport with expectations
verify-app eyes --url http://localhost:3000/cart --viewport 390x844 \
        --click "#pay" \
        --expect-text "Order confirmed" \
        --expect-request "/api/checkout:200" \
        --screenshot /tmp/cart.png

# 3. Visual regression check (0 changed pixels = identical)
verify-app pixels --before baseline/cart.png --after /tmp/cart.png --diff-out /tmp/diff.png

# 4. Run full gate from pass.json artifact
verify-app run --pass .verify/pass.json

# 5. Scaffold project-local verify-<app> harness
verify-app forge . --apply --adopt

# 6. Fault injection: prove the gate actually fails when broken
verify-app control --file src/app.js --find "Order confirmed" --replace "Order failed" --pass .verify/pass.json
```

**Exit codes:** `0` pass · `1` fail · `2` usage · `3` dependency down · `4` unconfigured/partial.

---

## 🚦 Tool Comparison

| Need | Use |
| :--- | :--- |
| Prove a journey with evidence and a gate | **this skill** (`run`) |
| Build a repo-local `verify-<app>` from code markers | **this skill** (`forge`) |
| Prove the gate can actually fail on a mutation | **this skill** (`control`) |
| Sub-second, high-volume journeys, target picked by intent | `frontend-uat` |
| Low-level locators, ARIA refs, Rust test authoring, headed browser | `playwright` |

---

## AGENTS.md Rule

```markdown
## Verify, don't claim
When an agent says a UI change is done, prove it:
verify-app run --pass .verify/pass.json
- "Done" without a tool call is a claim. Open the app on the real viewport first.
- Assert the text AND the request behind it: a healthy screen can hide a failed order.
- A skipped layer is not a pass. Report which questions are still open.
- A check you have never seen fail is not a check: run `verify-app control` against the feature.
- Keep the check as a command, so the next agent replays it instead of re-improving it.
```
