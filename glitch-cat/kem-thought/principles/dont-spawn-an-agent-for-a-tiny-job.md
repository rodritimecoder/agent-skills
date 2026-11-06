# Don't Spawn an Agent for a Tiny Job

**Rule:** Agents are expensive at rest. A tiny job gets a script, a regex, or a small local model.

**Why:** Each agent started with nearly fifty thousand tokens of instructions and tools, and every step re-reads them. Almost all of it is cached and cheap, but it is still a floor you pay for every time you spawn.

**In practice:**
- Under a minute of deterministic work → do not spawn. Write the script.
- The main session conducts; it dispatches rather than executes everything itself.
- The model has no memory — every call starts from nothing. The illusion of memory is the harness handing back the whole conversation.

**Kem:** *"Each agent I measured started with nearly fifty thousand tokens of instructions and tools, and every step rereads them. Almost all of it cached and cheap, but it's why you shouldn't spawn an agent for a tiny job."* — Claude Projects Beta [01:25]
