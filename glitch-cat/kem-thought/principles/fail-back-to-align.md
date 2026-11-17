# Fail Back to Align

**Rule:** When verification finds something off, go back to align. Never patch the output in place.

**Why:** A failure after a build is usually a misalignment, not a bug. A corrective patch by the same builder retries the same intent it already misunderstood, so it can only converge on its own preconceptions. APIV treats the failure as intent that was never made explicit: restate what is being built and what is not, then run the loop again.

**In practice:**
- A failed gate is a signal to reopen intent, not a ticket for the builder to try harder.
- Keep the failed artefact as evidence of the mismatch; do not quietly amend it.
- Escalate to BMAD only for bigger builds or whole-team agreement, where unstated assumptions need a written record (brief, PRD, architecture). Not for small changes.
- This is the seam with `apiv-loop`: this principle names the rule, `apiv-loop` supplies the four phases and state layout.

**Kem:** *"Anything that's off goes back to the align. I never patch it. It's a loop"* — How I develop with AI and when I look for something more robust [01:47]
