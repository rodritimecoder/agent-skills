# Kem Contract — five moves, three fields

The five moves from Kem Glitch's `/kem-mode`, expressed as things a folder can hold.
Run them once when you write the workspace; do not recite them per task.

| Move | Where it lives |
| :--- | :--- |
| Name the job and the actor | `One job:` plus `**Actor:**` in every stage `CONTEXT.md` |
| Tag the step D / P / H | `**Step type:**` — D deterministic code, P probabilistic model, H human |
| Decide what good looks like first | `## Human check` plus the Proof artifact |
| Fix the harness first | `AGENTS.md` routing, numbered stages, `_shared/` rules |
| State the done-check | `**Proof:**` — the file or command that proves the stage ran |

## The three fields

- **Actor** — `code`, `agent`, or `human`. One owns the step; the others are helpers.
- **Step type** — `D` if code decides, `P` if a model judges, `H` if a person does.
  A `P` step needs its output checked by something that is not the model that wrote it.
  An `H` step needs a file to sign.
- **Proof** — the artifact that proves it ran: `output/x.md`, `pytest -q`, a URL.
  A stage that cannot name one is a note, not a stage.
  UI work proves itself hands and eyes: `verify-app` → `output/verify.json`
  (skill `verification`, Reel `DfAIPrAtteM`). "It said it was done" is a claim, not a proof.

`icm-architect validate . --kem` fails when any of the three is missing.

## Rules that come with it

- A gate that cannot fail is not a gate. Run the check before claiming the stage passed.
- A claim is not a proof. Verification buys autonomy: the gate checks the work the way a
  person would — open it, use it, look behind the screen (`verify-app`, skill
  `verification`) — before the judge or the human is asked to trust it.
- A classifier that is unsure routes to the human. Ambiguity never grants autonomy.
- One state machine per repo. Stage `output/` mtimes are the state; a second ledger must
  agree with them or not exist.
- The human gate writes a file (`approved: true`, a verdict per non-goal). Approval that
  exists only in the conversation is not approval.

Source: `kem-thought` (principles), `kem-dev-loop` (the six-phase loop), and `verification` (the hands-and-eyes gate, Reel `DfAIPrAtteM`).
