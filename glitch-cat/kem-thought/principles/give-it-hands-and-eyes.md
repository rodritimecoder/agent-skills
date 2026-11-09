# Give It Hands and Eyes

**Rule:** An agent that cannot act on the artifact cannot verify the artifact. Give it a way to perform the journey and a way to watch the result, then make the check a command.

**Why:** Reading the code tells you what the author intended; only the rendered artifact tells you what shipped. On the same job with the same model, the agent without tools said it was done and admitted it never looked. The agent with tools opened the app, saw the problem, fixed it, and showed the before and after in one shot. The difference was not model quality — it was hands and eyes.

**In practice:**
- **Hands**: drive the real thing on the real viewport — tap, type, navigate, on the device the user has. Trusted input at real coordinates, not `element.click()` on a node that is present but cut off.
- **Eyes**: observe the run, not your reasoning about it — console errors, uncaught exceptions, failed requests and their statuses. A screen that looks fine can hide an order that never went through.
- Separate the two capabilities. Hands without eyes produces confident wrong fixes; eyes without hands can describe the bug forever.
- Add the layers that move you past your own machine: pixel diff against a baseline, every component state rendered on its own, and production reports from real users.
- Then freeze the answers into a skill with its own CLI. A verification step that lives in prose is re-improvised every run and drifts; a command is the same question answered the same way, and its exit code is the answer.
- A verification skill generalises by construction, not by distribution. There is no one skill to hand out, because verification only works when it is built for your own project: have a generator read the project, show you the tools it wants and why, wait for approval, then write the skill inside the project with its own CLI.
- Before it hands the skill over, the generator must break one feature on purpose, confirm the check catches it, and put it back exactly. A check you have never seen fail proves nothing (`mutate-the-test`).
- A skipped layer is not a pass. Report which layer did not run.

**Kem:** *"To check like you, it needs hands and eyes, which means tools."* — Verification: Hands and Eyes [00:49]

*"It answers them and those answers become a skill with its own CLI, which is just a simple command your agent runs to check your app instead of making it up each time."* — same reel [02:01]

*"There isn't one skill I can hand you because verification only works when it's built for your own project. So I've made you a skill that builds your skill."* — Build Your Own Verification Skill [00:21]

*"It breaks one feature on purpose to make sure it can catch it and then puts it back exactly as it was because a check you've never seen fail doesn't prove anything."* — same reel [01:19]
