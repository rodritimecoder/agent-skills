# Never Let a Model Overrule Code

**Rule:** Red is red. A model may not relabel a failing check as "old", "pre-existing", or "not mine" and proceed.

**Why:** A model is probabilistic. Stack models on top of models to check each other and you have got a roulette wheel checking a roulette wheel.

**In practice:**
- The build and the tests run in code, and no agent overrules a red result.
- If a check is noisy, fix the check in code — do not teach the model to talk past it.
- Gates that run "only if an agent chooses to run them" are not gates.

**Kem:** *"A model is probabilistic. So if you stack models on top of model to check each other, you've got a roulette wheel checking a roulette wheel."* — Software Factory Reaction [00:37]
