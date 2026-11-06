# Move Jobs from the Model to Code

**Rule:** Treat every agent task as a job in transit. Each pass, push one job down the stack: model → harness → script → code.

**Why:** The goal is always moving away from probabilism to determinism, from the model to code. A job that runs in code runs ten thousand times for the price of one.

**In practice:**
- Write the job list down. For each job, name the actor that currently owns it.
- "Can this be a script?" is a question with a yes answer most of the time.
- Do not add a second agent to fix a problem the first agent's code could have caught.

**Kem:** *"The goal is moving jobs from the model to code."* — Software Factory Reaction [01:09]
