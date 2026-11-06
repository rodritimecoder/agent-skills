# 05_gates — Deterministic Quality Gates

One job: Enforce automated test suites and hands-and-eyes verification ('Code Decides').

**Actor:** code
**Step type:** D
**Proof:** output/gate_results.json and output/verify.json

## Inputs
- Working: Worker branch changes from `../04_sandboxes/`
- Reference: ../_shared/rules.md
- Tool: `verify-app` (skill `verification`, Reel `DfAIPrAtteM`) for the hands-and-eyes layers

## Process
1. Run linters, type checks, and test runner.
2. Run sub-second UI checks via `playwright-rs` / `fast-cdp`.
3. Hands and eyes via `verify-app` — check the work the way a person would:
   - `verify-app doctor --json` first: a gate whose layers are missing cannot pass.
   - open the app on a real viewport (CDP `:9222`) and dispatch trusted input.
   - watch what the browser did behind the screen: console errors, exceptions, failed response statuses.
   - diff pixels against the baseline (ffmpeg) and keep the diff PNG.
   - where present, walk every Storybook state; where `SENTRY_AUTH_TOKEN` is set, read unresolved Sentry issues.
4. Emit pass/fail status per layer into `output/`; the gate fails closed.

## Outputs
- `output/gate_results.json`
- `output/verify.json` — one PASS/FAIL verdict with per-layer evidence (screenshots, diff PNG)

## Human check
Review the test summary and the `verify.json` evidence if failures occur. "It said it was done" is a claim, not evidence; the gate reports only what it observed.
