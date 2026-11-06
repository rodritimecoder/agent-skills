# A Gate Is Code That Can Fail the Work

**Rule:** A quality gate is not a rubric, a checklist, or a vibe. It is executable code that can fail the work and send it back around.

**Why:** A rubric is an opinion. A gate is a fact. If the gate cannot fail, the work was never gated.

**In practice:**
- Every gate needs an input, a pass condition, and a loop-back edge.
- A gate that always passes is decoration — cut it or make it real.
- A gate that cannot decide fails closed: ambiguity routes to the human, never past the gate.
- Sequence the gates by cost: design review first, then code, then security — so a one-line fix does not send the security review round again.

**Kem:** *"That's what we call a quality gate, meaning that there's code that can fail the work and when it fails that piece goes back around."* — 5 Agents Writing the Same File [01:18]
