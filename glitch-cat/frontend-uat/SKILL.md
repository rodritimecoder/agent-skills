---
name: frontend-uat

description: >
  Sub-second, model-backed frontend UAT loop (Glitch Cat Club / Kem Glitch). Mined from
  the vault's *Fast Frontend UAT with JEV* capture on 2026-10-16; the source reel is
  unidentified.
  Hands the page to the decision model as an indexed array of clickable targets, clicks
  deterministically over CDP, then reads the screen back to confirm the assertion — no
  open-ended text is ever generated, so a journey costs seconds and fractions of a cent
  instead of minutes and dollars. Use when running browser acceptance tests, driving a
  checkout or login flow, clicking a target by intent rather than by selector, or verifying
  a screen state after an action.

compatibility: "Requires the playwright skill's Playwright Rust-backed CLI (playwright-rs, alias fast-cdp) with a Chromium CDP endpoint on :9222 and the h2o-lightning-4b JEV decision server on :8083. Python 3.10+."
allowed-tools: "Bash(frontend-uat:*) Bash(fast-cdp:*) Bash(python3:*) Read Write"
---

# Frontend UAT (`frontend-uat`)

Runs a browser acceptance test the way Kem Glitch's *Fast Frontend UAT with JEV* capture
does: **perception is a decision, not a generation.**

> **Provenance:** the capture is vaulted at
> `kem_glitch/2026-10-16_unmatched_fast_frontend_uat_jev_capture/`; its Instagram reel is
> unidentified. The earlier `DeKBMCQNRXU` attribution was retracted on 2026-11-02 — that
> reel is the Glitch Orchestra alignment workflow. `SOURCES.md` separates what the capture
> shows from what this skill modeled.

```
   [D] DOM candidate extraction  ──►  [P] decision model picks the target index
                                              │
        [D] CDP click on the chosen ref  ◄────┘
                    │
                    ▼
   [D] assert text/URL   ──or──  [P] model reads the screenshot back and answers
```

Each step is tagged `[D]` deterministic or `[P]` probabilistic, so a failure is
attributable to code or to a model turn.

| Path | Cost in the benchmark | Latency |
| :--- | :--- | :--- |
| Generative vision agent (multimodal LLM turn per click) | ~$7.00 per suite | minutes |
| This loop (decision model, no generated tokens) | ~$0.00024 per suite | seconds |

---

## 🛠️ CLI

Run from this skill's directory (the harness resolves paths from the skill root).

```bash
UAT="python3 scripts/frontend_uat.py"

# Is everything alive? (CDP browser on :9222, decision server on :8083)
$UAT doctor

# What can be clicked right now? (refs are what the model picks from)
$UAT candidates http://localhost:3000

# Decide before acting — writes a plan you can review or replay
$UAT plan --url http://localhost:3000 --intent "proceed to checkout" --out /tmp/checkout-plan.json

# The full loop: choose, click, verify
$UAT run --url http://localhost:3000 --intent "finish the payment and place the order" \
         --expect-text "Order confirmed" --screenshot /tmp/order.png

# Replay a reviewed plan (no second decision)
$UAT run --url http://localhost:3000 --intent "finish the payment and place the order" \
         --plan /tmp/checkout-plan.json --workdir .uat-ledger
```

`--json` prints the full report; `--out FILE` writes it to disk and keeps stdout to
one line, so a suite of runs costs a few tokens each. `--workdir DIR` serializes every
step (`step_01_candidates.json` … `step_04_verification.json`) for post-mortems.

**Exit codes:** `0` pass · `1` failed verification · `2` usage error · `3` a dependency is down.

---

## 🚦 This or `playwright-rs uat`?

Both end in the same deterministic click; they differ in **who judges**.

- **One call, one judge** → `playwright-rs uat "<url>" --goal "…"`. It extracts the
  candidates through Padamson's Playwright Rust API and asks its own decision model
  (`jpt` or `imajev`) which one to click.
- **Your judge, plus a report** → this skill. JEV (`:8083`) makes the choice, the click
  is passed back as `--ref`, and you get expectations, a screenshot and a verdict.

Use this loop when the choice has to be the same judge as the rest of your pipeline, or
when the run has to produce evidence rather than a click. Use `uat --goal` when one call
with a built-in judge is enough.

## 🧾 This or `verification`?

This loop is the fast click: one journey, one decision, one assertion. When the
claim has to survive review — a real mobile viewport, console errors and failed
requests, a pixel diff, every Storybook state, Sentry — hand the same journey to
`verification` and keep its artifact:

```bash
verify-app run --pass .verify/pass.json
```

`frontend-uat` drives the journey; `verification` proves it.

---

## ⚠️ Gotchas

- **Extraction and action must see the same page.** The refs (`uat-1`, `uat-2`, …) are DOM
  order. A page that re-renders between `plan` and `run` shifts them — `run` re-validates
  the plan's URL and intent and refuses a mismatched plan, but a live SPA can still move
  under it. Re-plan if the page changed.
- **The ref must belong to the candidate set.** The loop fails loudly rather than clicking
  a ref the model invented.
- **`--assert-image` costs a model turn; `--expect-text`/`--expect-url` cost nothing.**
  Prefer an assertion the DOM can answer, and use the image gate only for outcomes that
  are visual (a toast, a chart, a modal that renders).
- **`--min-p` is the guard on a weak pick.** `confidence` from the engine is an entropy
  concentration, not a probability — the loop reports `p_selected`, the model's actual
  probability for the chosen target, and refuses to click below `--min-p`.
- **The decision server has 4 slots.** A UAT suite is dominated by clicks, not decisions;
  if you parallelise runs, more than four concurrent decisions will queue on :8083.

---

## 📚 Reference

`references/architecture.md` — the capture's architecture, benchmark economics, and why a
decision model beats a generative one for this job.

---

## 📁 Layout

- `scripts/frontend_uat.py` — the loop (`doctor`, `candidates`, `plan`, `run`).
- `references/architecture.md` — why the decision model wins, and the benchmark.
- `SOURCES.md` — what the capture shows, and what this skill modeled.
- `tests/` — the contract the CLI has to keep.

Runtime state belongs to the project being tested (`--workdir .uat-ledger`), not to this
folder.

---

## AGENTS.md rule

## Frontend UAT
When a UI change must be proven, drive it:
frontend-uat run --url <url> --intent "<goal>" --expect-text "<assertion>"
- The decision model picks the target from the DOM's indexed clickables; it never guesses coordinates.
- A run without an assertion is not a result. Assert the text or the URL.
