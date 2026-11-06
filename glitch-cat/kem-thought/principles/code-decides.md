# Code Decides Wherever It Can

**Rule:** Every decision in the system belongs to exactly one of three actors — you, the agent, or code — and code wins wherever it can hold the verdict.

**Why:** The agent is brilliant, but it is probabilistic and unreliable. Code does the same thing every time, and it is cheap and fast. You are the best verifier because you know what you want, but you are also a bottleneck. So the whole game is putting the verdict in the right actor's hands.

**In practice:**
- Ask "could a script answer this?" before you ask a model.
- Where code truly cannot check something, bring in a judge — a second agent in a fresh context.
- Mark the residue explicitly so it does not creep back into the spine.

**Kem:** *"Your goal in designing this is always that code decides wherever it can. A model should only judge when it's absolutely necessary."* — 5 Agents Writing the Same File [01:30]
