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

compatibility: "Needs a Chromium CDP endpoint on :9222 (playwright-rs daemon start) for the hands and eyes layers, ffmpeg for the pixel layer, and optionally a running Storybook plus SENTRY_AUTH_TOKEN. Python 3.10+; no third-party Python packages."
allowed-tools: "Bash(verify-app:*) Bash(python3:*) Bash(playwright-rs:*) Bash(ffmpeg:*) Read Write"
---

# Verification (`verification`)

Reel [`DfAIPrAtteM`](https://www.instagram.com/reel/DfAIPrAtteM/): *"The single most important
skill in your AI toolkit is verification."* Not a step at the end — the thing that buys the
agent more autonomy.

> *"Verification means your agents check its own work the way you would by actually using
> it. That's what moves you up the trust ladder so it can run on its own for longer and hand
> back verified work."* — [00:10]

The reel's own controlled comparison is the whole argument. Same model, same job, a button
cut off in mobile view:

| | Without tools | With tools |
| :--- | :--- | :--- |
| What happened | *"it said it was done and admitted it never looked"* | *"it opened the app on the phone, saw the problem, fixed it, and showed me the before and after in one shot"* |
| What you got | a claim | evidence |

The difference is not model quality. It is **hands and eyes** — a way to act on the real
artifact and a way to see the real result.

```
   [D] open on a real viewport ──► [D] dispatch trusted input ──► [D] observe CDP
                                                                  console / exceptions
                                                                  response statuses
            ┌─────────────────────────────────────────────────────────┘
            ▼
   [D] assert text + request      [D] diff pixels vs baseline     [D] walk Storybook states
            └──────────────────────────────┬──────────────────────────────┘
                                           ▼
                          [H] read verify.json, or trust exit code
```

---

## 🖐️👁️ The five layers

| Layer | Reel's tool | What this skill runs | Failure class it owns |
| :--- | :--- | :--- | :--- |
| **hands** | Playwright | CDP trusted input + optional `playwright-rs` for locator work | cannot reproduce the journey at all |
| **eyes** | Chrome DevTools | CDP `Runtime`, `Log`, `Network` events | screen looks fine, the thing behind it failed |
| **pixels** | image diff | ffmpeg decode + byte-exact compare, diff PNG | the small visual change nobody looked at |
| **states** | Storybook | walk `index.json`, render each story, catch mount errors | one component in one state was never rendered |
| **errors** | Sentry | unresolved issues from the Sentry API | the error real users hit that fixtures never will |

The order is the point: **the gate walks from the agent's machine to the user's machine.**
Layers 1–2 verify before shipping, 3–4 verify the artifact, layer 5 verifies after shipping.
A gate that stops at layer 2 never learns what production knows.

---

## 🛠️ CLI

The gate installs as **`verify-app`** (see `cli-manifest.json`); `python3 scripts/verify.py`
is the same program when you are working inside the skill directory.

```bash
V="python3 scripts/verify.py"

# 0. Are the layers actually there? (CDP browser, playwright-rs, ffmpeg, Storybook, Sentry)
$V doctor --json

# 1. The five questions. Writes .verify/pass.json for this app.
$V ask --out .verify

# 2. Prove a mobile journey, with the assertion that has to be true afterwards
$V eyes --url http://localhost:3000/cart --viewport 390x844 \
        --click "#pay" \
        --expect-text "Order confirmed" \
        --expect-request "/api/checkout:200" \
        --expect-eval "document.querySelector('#nodeCount').textContent > 0" \
        --screenshot /tmp/cart.png

# 3. How far did the fix move the pixels? (0 changed pixels = identical)
$V pixels --before baseline/cart.png --after /tmp/cart.png \
          --diff-out /tmp/cart-diff.png

# 4. Every component state, each on its own
$V states --storybook http://localhost:6006 --filter "Cart" --limit 20

# 5. What real users are already hitting
$V errors --org my-org --project web --stats-period 24h --max-issues 0

# 6. The whole gate, from the five answers, as one command
$V run --pass .verify/pass.json
```

`--json` on any subcommand prints one machine-readable line. `--out FILE` writes the full
report to disk and keeps stdout small.

**Exit codes:** `0` pass · `1` fail · `2` usage · `3` a dependency is down · `4` nothing was
configured. A skipped layer is a skip, never a pass.

---

## 🏗️ `forge` — a skill that builds this project's skill

Reel [`DfCsHxbtV3J`](https://www.instagram.com/reel/DfCsHxbtV3J/): *"There isn't one skill I
can hand you because verification only works when it's built for your own project. So I've
made you a skill that builds your skill."*

```bash
# 1. Interview the repo. Writes nothing; prints the five answers and the tool card.
verify-app forge .

# 2. Approve the tools, then write it.
verify-app forge . --apply

# 3. Wire it into the project's instruction file (AGENTS.md by default).
verify-app forge . --apply --adopt
verify-app forge . --apply --adopt --instructions CLAUDE.md
```

`forge` answers the five questions **from the codebase**, not from the user: markers in
`package.json`/`pyproject.toml`/`Cargo.toml`, route files, route decorators, `bin` entries,
existing Playwright/Cypress/Storybook/Sentry configs, and the harness already in the repo.
It never guesses an answer it cannot observe — an unanswerable question is emitted as an
**open question**, and the whole run exits `4` rather than writing a gate that looks whole.

What `--apply` writes:

```
.agents/skills/verify-<app>/     ← default; portable Agent Skills location
├─ SKILL.md                      six H2: Launch · Doctor · Drive · Evidence · Cleanup · Helpers
├─ features/
│  ├─ README.md                  baseline, driving conventions, proof rules, entry contract
│  └─ <feature>.md               one page per detected route / endpoint / command (top 5)
└─ scripts/verify                a shim onto the global verify-app, refusing if it is absent

.verify/pass.json                the five-question skeleton, named for this app
```

`.agents/skills` is the portable choice: OpenCode discovers it, and any harness that reads
`SKILL.md` can use it. `--harness opencode` writes `.opencode/skills/`, `--harness claude`
writes `.claude/skills/`, and `--out DIR` puts it anywhere else. A repo that already has an
`.opencode/` or `.claude/` marker is detected automatically; with no marker the portable path
wins.

`--adopt` is the part that makes it harness-agnostic in practice: it appends one line under a
`## Verification` heading in `AGENTS.md` (or `--instructions CLAUDE.md`), idempotently, so any
agent that reads the project's instruction file finds the gate even if its harness has no
skill discovery. The skill body itself contains no harness-specific commands — load it by ID
where skills exist (OpenCode `@verify-<app>`, Claude Code `/verify-<app>`), or read the file.

An existing `SKILL.md` is never overwritten — hand edits win. Each generated feature page uses
exactly four H2 headings, in the artifact's order: `Sub-features`, `How to get to it (user
POV)`, `Driving it with verify-<app>`, and `Gotchas`. Pages are seeded from detected entry
points, so each one says it is unproven until its end state is written and driven.

Two things the generator deliberately does not do for you, because the artifact does not let
it pretend:

- **It does not run your app.** The `Launch` section names the command it detected and says
  plainly that it was not executed. A skill written against a base that never started teaches
  wrong steps, so prove the launch before trusting the gate.
- **It does not hand over an unproven gate.** `forge` writes the skill; the run that makes it
  a deliverable is launch → doctor → drive one mapped feature → evidence → cleanup → confirm
  the evidence still exists. A generated skill that was never executed is a draft.

---

## 🔴 `control` — prove the gate can fail

> *"It breaks one feature on purpose to make sure it can catch it and then puts it back
> exactly as it was, because a check you've never seen fail doesn't prove anything."*
> — [01:21]

```bash
verify-app control --file app.js \
  --find "Order confirmed" --replace "Order failed" \
  --pass .verify/pass.json
```

The sequence is the assertion:

1. `--find` must occur **exactly once** in the file; zero or two occurrences is a usage error,
   not a guess.
2. The file is mutated, the gate runs, and it must come back `fail` — **the red is the point**.
3. The original bytes are restored in a `finally` block and verified by SHA-256 — *"put back
   exactly as it was"*, not "roughly".
4. The gate runs again and must come back `pass`.

```
PASS  control  app.js
  red    fail (1)  expected a failing gate
  restore 74c4d2086c92  exact
  green  pass (0)
```

`control` refuses to touch a path outside the repo, anything under `.git`/`node_modules`/
`.venv`, `.env*`, and `*.pem`/`*.key`/`*.p12`/`*.keystore`. It writes
`.verify/artifacts/control.json` and exits `0` only when all three conditions held: red seen,
restore exact, green after. A gate that stays green on a broken feature is a failed control,
not a pass.

---

## 📋 `pass.json` — the five answers

`$V ask` writes the skeleton; unanswered questions come back as `unanswered` and the verdict
is reported as a **partial gate**. Three open questions and a green tick is exactly the
failure the reel describes.

```json
{
  "name": "cart-mobile",
  "api": {"url": "http://localhost:3000/cart", "viewport": "390x844", "settle_ms": 800},
  "journey": [
    {"fill": ["#email", "buyer@example.com"]},
    {"click": "#pay"},
    {"wait": 800}
  ],
  "expect": {
    "text": "Order confirmed",
    "case_sensitive": false,
    "requests": [{"contains": "/api/checkout", "status": 200}],
    "eval": [{"label": "graph rendered", "expression": "document.querySelectorAll('canvas').length > 0"}],
    "no_failed_requests": true
  },
  "pixels": {"baseline": "baseline/cart-mobile.png", "tolerance": 8, "max_changed": 0.0},
  "states": {"storybook": "http://localhost:6006", "filter": "Cart", "max_stories": 30},
  "errors": {"sentry": {"org": "my-org", "project": "web", "stats_period": "24h", "max_issues": 0}},
  "artifacts": ".verify/artifacts"
}
```

Journey steps: `{"click": sel}`, `{"fill": [sel, value]}`, `{"press": key}`,
`{"eval": "js"}`, `{"wait": ms}`. Clicks are real CDP mouse events at the element's centre,
not `element.click()`, so a target that is not reachable behaves the way it would for a
person.

---

## 🚦 This or `frontend-uat` or `playwright`?

Three skills, one browser, different jobs — do not fork a fourth, and do not fork a separate
"generator" skill either: `forge` lives here so the thing that builds the gate and the thing
that runs it share one contract.

| Need | Use |
| :--- | :--- |
| Prove a journey with evidence and a gate | **this skill** (`run`) |
| Build a repo-local `verify-<app>` from the five questions | **this skill** (`forge`) |
| Prove the gate can actually fail | **this skill** (`control`) |
| Sub-second, many journeys, decision model picks the target by intent | `frontend-uat` |
| Locators, AI-mode ARIA refs, Rust test authoring, headed browser for a human | `playwright` |

`playwright-rs` is the driver under all three. This skill adds the *observation* and the
*artifact*; it does not reimplement Playwright.

---

## ⚠️ Gotchas

- **`doctor` first, and read it.** `eyes` needs a live CDP target, `pixels` needs ffmpeg,
  `states` needs a Storybook that answers `/index.json`. Layer down = exit `3`, not a fail.
- **One viewport per answer.** `390x844` is the reel's bug; a desktop screenshot proves
  nothing about it. Chrome on a mobile viewport without `<meta name="viewport">` lays the
  page out at 980px and reports the button as on-screen while the screenshot shows it cut
  off — the gate compares against the viewport you declared, because that is the device you
  claimed to test.
- **A cut-off target is reported before the click lands.** The click is still dispatched;
  `viewport` in `problems` is the finding, and it is geometry, not an opinion.
- **A click can land on the wrong element.** Before dispatching, the gate asks
  `elementFromPoint` what is actually at the target's centre. If a banner, a chip bar or a
  loading overlay is on top, the finding is `occluded` and names the covering element —
  the button exists, the click never reaches it.
- **`innerText` is not your markup.** CSS `text-transform: uppercase` rewrites what a
  person reads, so `expect.text` matches case-insensitively by default. Set
  `case_sensitive: true` only when the casing itself is the contract.
- **A page with no breakpoints is not "fine on mobile", it is shrunk.** When content needs
  more width than the declared viewport, Chrome expands the layout viewport and scales it
  down: the report says `page needs 1150px but the viewport is 390px ... read at 34% size`.
  A plain narrow window instead reports `horizontal_overflow`. Same bug, two symptoms —
  read the `layout` block to know which one you have.
- **Canvas apps need `expect.eval`.** A D3 or WebGL page has almost no DOM text to assert.
  Assert the state the canvas is drawn from (`nodeCount`, a store, a class), not the pixels
  the canvas produced — the pixel layer covers that separately.
- **The baseline is a decision, not a formality.** `max_changed: 0.0` means "not one pixel
  moves" and is right for a bug fix. A redesign needs a new baseline — approve it
  deliberately, in a commit, or the pixel layer becomes a rubber stamp.
- **Sentry silence is not correctness.** Unresolved issues at zero means nobody reported,
  not that nothing broke. Layer 5 grades the reports, not reality.
- **Observations start when the gate attaches.** The CDP session sees the load and the
  journey; it cannot see what happened before it attached. Start the gate before the step
  you are testing.
- **Storybook `index.json` is the story list**, not the docs pages. `type: "docs"` entries
  are skipped by design.
- **Auth flows are yours.** The gate does not log in for you; point it at a page that is
  already authenticated (storage state, seeded session, or a test account in the URL).
- **`forge` is dry-run until `--apply`.** The interview writes nothing, so the tool card can
  be read and challenged first. Exit `4` means at least one question is still open — the
  files were still written, with the gap named at the top of `SKILL.md`. That is deliberate:
  a partial gate that says so beats a complete-looking gate that guessed.
- **The default is the portable path, not a vendor path.** `.agents/skills` is discovered by
  OpenCode and readable by any harness that understands `SKILL.md`; `--harness opencode` and
  `--harness claude` are opt-in, and `--out` covers the rest. Nothing in the generated skill
  depends on Claude Code.
- **`--adopt` is what survives a harness without skill discovery.** One line under
  `## Verification` in `AGENTS.md`; rerunning is a no-op, and an existing section is extended
  in place rather than duplicated. Use `--instructions CLAUDE.md` (or any path) if that is
  the file the agents in the repo actually read.
- **`forge` never overwrites an existing `SKILL.md`.** Regenerating writes the missing pieces
  and leaves hand edits alone; delete the file yourself if you want a clean rewrite.
- **`forge` reads routes, not intentions.** It finds Next/Remix/SvelteKit/Astro pages and
  FastAPI/Flask/Express decorators; it does not infer what a feature *should* do. A detected
  feature still needs a person to write the assertion.
- **The generated `scripts/verify` is a shim, not a second implementation.** It `exec`s the
  global `verify-app` and exits `3` when that is missing. Update the global skill, not the
  copy in each repo.
- **`control` will refuse a non-unique `--find`.** That is the safety property: a string that
  appears twice can break the wrong code path, or none. Make the mutation specific.
- **`control` mutates in place and restores in `finally`.** Do not run it against a tree
  another process is writing to, and do not point it at generated or vendored files.
- **A green `control` is not a strong gate.** It proves one assertion is wired. The feature
  map still has to be complete, or the untested features remain untested.

---

## 📚 Reference

`references/architecture.md` — the trust ladder, layer-by-layer contract, evidence format,
and why each layer is `[D]` code instead of a model turn.

---

## AGENTS.md rule

## Verify, don't claim
When an agent says a UI change is done, prove it:
verify-app run --pass .verify/pass.json
- "Done" without a tool call is a claim. Open the app on the real viewport first.
- Assert the text AND the request behind it: a healthy screen can hide a failed order.
- A skipped layer is not a pass. Report which questions are still open.
- A check you have never seen fail is not a check: run `verify-app control` against the
  feature the gate claims to own.
- Keep the check as a command, so the next agent replays it instead of re-improving it.
