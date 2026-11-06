# Start With a Workflow

**Rule:** If you know the steps, write the workflow. Add autonomy only where the workflow breaks.

**Why:** Explicit control (the route is set in code) versus emergent control (the model picks the route) is a spectrum. Autonomy is the fallback for genuine uncertainty, not an architecture you choose because it sounds agentic.

**In practice:**
- Known route → sequential, parallel, or conditional, written in code.
- Unknown route → plan-based, handoff, or group chat, and only then.
- Group chat is the expensive one: the thread grows every turn, cost climbs, details get lost as it eats attention, and it becomes a hot bed of conflicting decisions.
- Plan-based orchestration is a single point of failure — the planner's bad plan is the run.

**Kem:** *"If you know the steps, use a workflow. If the answer only shows up by trying things, that's autonomy. But even then, start with a workflow and add autonomy only where it breaks."* — Demystifying Orchestration [01:54]
