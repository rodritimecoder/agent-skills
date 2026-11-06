# Architecture — the verification gate

Source: Reel [`DfAIPrAtteM`](https://www.instagram.com/reel/DfAIPrAtteM/), 02:37.
Vault entry: `2026-10-28_verification_hands_and_eyes`.

---

## 1. The trust ladder

The reel's claim is causal, not motivational:

```
   check the work ──► trust ──► longer jobs ──► more autonomy
        ▲                                            │
        └────────────── more work to check ◄──────────┘
```

> *"That's what moves you up the trust ladder so it can run on its own for longer and hand
> back verified work."* — [00:20]

Autonomy is spent against verification, the way CPU time is spent against a benchmark. An
agent that cannot check its own work forces a person into the loop at the end of every job,
which caps the job length at "the size a person will review". An agent that checks the way
a person checks returns verified work, and the review becomes a read instead of a hunt.

This is why verification belongs in the harness rather than in the prompt: the trust has to
survive the next session, the next model, and the next agent on the same repo.

---

## 2. Why "without tools" fails, mechanically

The reel's demo is a button cut off in mobile view. Two failure modes, both real:

1. **Intent is not the artifact.** Reading the source tells you the author's model of the
   layout. The rendered box depends on viewport, `box-sizing`, padding, the viewport meta
   tag, and the font. A model reviewing its own diff is checking intent against intent.
2. **The click never reaches the target.** A cut-off button is still in the DOM, still has a
   bounding box, and still answers `querySelector`. A DOM assertion passes; a person gets
   nothing. Only input dispatched at real coordinates, or a geometric check against the
   declared viewport, catches it.

The gate therefore dispatches trusted input through CDP `Input.dispatchMouseEvent` and
checks the element's box against the declared viewport *before* the click lands. That
finding is `kind: "viewport"` and reads like this against the fixture:

```
#pay is cut off on this viewport: centre (470, 144) in 390x844, 230px hidden
```

No model involved. Geometry.

The same page can also fail the other way round: the element is exactly where it should be
and something else is painted over it. `elementFromPoint` at the target's centre answers
that before the click is dispatched, and the report names the covering element. A button
that is visible, sized, and inside the viewport can still be unreachable.

---

## 3. Layer contract

Each layer is `[D]` deterministic — no generative step, so a failure is attributable.

| Layer | Input | Observable | Fails when |
| :--- | :--- | :--- | :--- |
| `hands` | `api.url`, `journey[]`, `api.viewport` | trusted input log with per-step ms | element missing, zero-size, cut off, or covered by another element; journey step throws |
| `eyes` | same session | `Runtime.consoleAPICalled`, `Runtime.exceptionThrown`, `Log.entryAdded`, `Network.responseReceived`, `Network.loadingFailed`, `window.innerWidth` vs `document.scrollWidth` | any console/exception/log error, any response ≥ 400, any expectation unmet, layout wider than the declared viewport |
| `pixels` | baseline PNG + after PNG | changed count, ratio, bounding box, diff PNG | size changed, or ratio > `max_changed` |
| `states` | `<storybook>/index.json` | one render per story, per-story problems | any story mounts with an error |
| `errors` | Sentry API | unresolved issues in the window | count > `max_issues` |

`[H]` human turns are exactly two: approving a new baseline, and reading `verify.json` when
a layer fails for a reason the report cannot name.

### Observation substrate

CDP events are collected on a hand-rolled WebSocket (`scripts/cdp_lite.py`), not through a
JS shim, for one reason: **a shim only sees what happens after it is installed.** Console
output, uncaught exceptions and network failures that occur during the load — the ones that
matter — happen before any shim could run. Protocol events arrive from the first frame.

The client is ~230 lines of stdlib: HTTP upgrade, masked frames, ping/pong, fragment
reassembly, request/response correlation. No `websockets`, no `playwright-python`.

---

## 4. Evidence format

`run` writes `<artifacts>/verify.json` and prints one line:

```json
{
  "name": "cart-mobile",
  "url": "http://localhost:3000/cart",
  "viewport": "390x844",
  "verdict": "fail",
  "gate": "full",
  "exit": 1,
  "failed": ["eyes", "pixels"],
  "skipped": ["errors"],
  "unanswered": [],
  "layers": {
    "eyes": {"status": "fail", "detail": "2 request(s), 3 problem(s)", "problems": [...]},
    "pixels": {"status": "fail", "detail": "18943 px changed (5.7550%)", "box": {...}, "diff": "..."},
    "states": {"status": "pass", "detail": "1/1 states clean"},
    "errors": {"status": "skip", "detail": "no sentry project configured"}
  }
}
```

Rules the format enforces:

- **`verdict` never absorbs a skip.** A layer that did not run is `skip`, and the gate says
  so. `pass` with three skips is a smoke test, and `gate: "partial"` names it.
- **`gate` is separate from `verdict`.** `full` means all five questions were answered;
  `partial` lists the open ones. Both can be `pass`.
- **`failed` names the layers, not the symptoms.** The symptom is inside the layer report.
- **`exit` is in the file as well as the process.** A CI job that captures only the artifact
  still gets the verdict.

---

## 5. Why a CLI and not a prompt

> *"It answers them and those answers become a skill with its own CLI, which is just a
> simple command your agent runs to check your app instead of making it up each time."*
> — [02:01]

A prose instruction ("check the UI after changes") is re-interpreted every session: which
URL, which viewport, which assertion, whether a warning counts. That drift is invisible
until a bug ships through a gate that had quietly loosened. `pass.json` freezes the answers;
`verify.py run` replays them; the exit code is the same question answered the same way.

The five questions are the schema, one per layer:

1. Which journey does a person actually perform, and on which viewport? → `api`, `journey`
2. What must be on screen at the end, in the exact words that prove it? → `expect.text`
3. What must be true behind the screen — which request, status, or record? → `expect.requests`
4. What did it look like before, and which pixels must not move? → `pixels`
5. Which real-user error already happened, and how do we see the next one first? → `errors`

The reel does not enumerate these five; they are derived from its five layers, and the
vault note marks them as derived rather than quoted.

---

## 6. Boundaries

- **`frontend-uat`** — decision model picks the target by intent, sub-second, one journey.
  Use it when the *path* is ambiguous. This skill is the gate around a path you already know.
- **`playwright`** (multimodal) — the driver: locators, AI-mode refs, headed browser for a
  human, Playwright Codegen for recording a journey once. This skill consumes the same CDP
  endpoint and does not reimplement it.
- **`parallel-test-lane`** — parallelism and blast radius for test suites. Orthogonal: it can
  run `verify.py run` per lane.
- **`guard-hooks`** — refusals before execution. Orthogonal.

---

## 7. Forge — the gate is constructed, not distributed

Reel `DfCsHxbtV3J` refuses the obvious sequel to this skill. The demand after the first reel
was for a downloadable gate; the reel answers *"there isn't one skill I can hand you because
verification only works when it's built for your own project."* So the portable artifact is
the **interview**, and the gate is built per repo.

The five questions become answers read from the codebase, not from the user:

| Question | Evidence `forge` accepts | If missing |
| :--- | :--- | :--- |
| **Surface** | framework markers, `bin`, `[[bin]]`, `android/`/`ios/`, server deps | `unknown` + open question |
| **Run** | `package.json` scripts (`dev`→`start`→`serve`), Makefile targets, `[project.scripts]`, compose, `manage.py` | open question |
| **Drive** | existing Playwright/Cypress config, `pytest`, `vitest` | proposal, marked *not installed* |
| **Observe** | route files, route decorators, command entry points | empty feature map + open question |
| **Isolate** | `.env.example`, compose file | open question about shared state |

The rule is the same as the runtime's: **a question that cannot be answered is a layer the
gate does not have, and it says so.** `forge` exits `4` with the gaps at the top of the
generated `SKILL.md`; it never fills them with a plausible guess.

The generated skill is deliberately thin and **harness-agnostic**. It is written to
`.agents/skills/verify-<app>/` by default — a path OpenCode discovers and any harness that
reads `SKILL.md` can follow — with `--harness opencode`/`--harness claude`/`--out` as
opt-ins. It carries the six headings from the artifact's section 2 (`Launch`, `Doctor`,
`Drive`, `Evidence`, `Cleanup`, `Helpers`), a feature map of `README.md` plus one page per
detected entry point (top 3–5), and a `scripts/verify` shim that `exec`s the global
`verify-app`, so the runtime has exactly one implementation and each repo carries only its
own answers.

The artifact's contract is followed literally where it is checkable:

| Artifact requirement | How the generator satisfies it |
| :--- | :--- |
| Launch reaches usable from an empty data dir, incl. migrations and seed; ready means usable, not just answering | `Launch` states the requirement and the detected command, and says the command was not executed |
| Doctor: process up, right build, port owned by us, auth valid | `Doctor` lists all four and requires the run's own port/data dir |
| Drive: existing harness first; stable handles over coordinates | `Drive` orders existing harnesses before generic recipes and names ARIA/prompt/route handles |
| Evidence: real user path, side effects, mocks only at a production boundary, dry-runs verified by observation | `Evidence` carries each standard verbatim in substance |
| Cleanup: never kill by name, never remove proof | `Cleanup` states both |
| Helpers: executable, invocation shown | `scripts/verify` is mode `0755` and every command is listed |
| Feature map: `README.md` + 3–5 pages, four H2 ending in `Gotchas` | Rendered exactly that way; seeded pages declare themselves unproven |
| Prove before hand-over: one mapped feature end to end, evidence survives cleanup | `Helpers` carries the run order, and the base-not-executed caveat is in `Launch` |

`--adopt` closes the loop where skill discovery does not exist: one line under
`## Verification` in `AGENTS.md`, idempotent and extended in place, so an agent that reads
the project's instruction file finds the gate even if its harness never learned about
skills. Nothing in the generated body names a harness, and nothing depends on Claude Code.

---

## 8. Control — the gate must be seen failing

> *"It breaks one feature on purpose to make sure it can catch it and then puts it back
> exactly as it was, because a check you've never seen fail doesn't prove anything."*
> — [01:21]

This is `always-run-the-control` applied to the verification skill itself. The mechanism is
three assertions in one command:

```
unique --find  →  mutate  →  gate must fail  →  restore bytes  →  gate must pass
                                   │                  │                 │
                              the red is the      SHA-256 must      the baseline is
                              whole point         match exactly     green again
```

Without the third step a "self-test" can leave the repo broken. Without the first, a find
string that appears twice mutates a code path the gate never touched, and the green result is
meaningless. Without the middle step the command is a smoke test that proves the gate runs,
not that it can fail — which is the failure mode the reel names.

`control` writes `verify.json`'s sibling, `control.json`, and exits `0` only when all three
hold. It refuses paths outside the repo, `.env*`, and key material, because a control run
that mutates a credential is a worse bug than the one it was testing for.

---

## 9. Verification of this skill

`tests/test_verification.py`, 29 tests, stdlib `unittest`:

| Test | Proves |
| :--- | :--- |
| 01–04 | pixel arithmetic: identical, one pixel, tolerance, size change |
| 05–07 | viewport parsing, five questions, partial-gate rule |
| 08 | `doctor` runs with no app and no browser |
| 10 | a cut-off button is caught on `390x844` |
| 11 | the fixed page passes the text + request assertions |
| 12 | a 500 behind a healthy screen is named |
| 13 | the Storybook walker isolates the one broken story |
| 14 | full gate: pass case green, buggy case red, artifact written |
| 15 | `text-transform` is matched case-insensitively, and `case_sensitive` still fails it |
| 16 | shrink-to-fit is named as a layout problem |
| 17 | `expect.eval` passes and fails on the right expressions |
| 18 | a covered button is reported as `occluded`, naming the overlay |
| 20 | `forge` reads a repo: surface, run command, harness, routes, and the open questions |
| 20c | static `.html` pages become features, with `404.html` skipped |
| 21 | `--apply` writes a six-heading skill, the feature contract, an executable shim, and a pass skeleton |
| 22 | an empty repo names every open question and exits `4` instead of guessing |
| 23 | regenerating never overwrites a hand-edited `SKILL.md` |
| 24 | `control` passes when the gate is seen red and the restore is byte-identical |
| 25 | `control` fails when the gate stays green on a broken feature |
| 26 | `control` fails when the gate never goes green again |
| 27 | `control` refuses ambiguous finds, credential files, and paths outside the repo |

Live tests skip — not fail — when nothing answers on `:9222`, because a stopped daemon is
not a broken gate.

Run it:

```bash
python3 tests/test_verification.py
```
