# Context Is a Budget

**Rule:** Every token you load spends attention you needed. Treat the window as a budget with a price per token, and know when to clear it.

**Why:** Loosely, every token in the window is weighed against every other one, and the fact you actually care about gets a thinner slice. That is context rot. More stuff, less accuracy.

**In practice:**
- Put critical instructions at the attention sinks — the start or the end of the window, never the middle.
- Know when to clear. Your failed attempts and your angry corrections are in the window too, and they get re-read on every call.
- Caching is not memory. It is a cheaper re-read of the same tokens, and the tokens still count.
- Structure folders so grep works; good folder structure works because grep works.

**Kem:** *"Loosely, every token in the window is weighed against every other one. And the model has to pick the next word, right? So more tokens pulling on that probability and the fact you actually care about gets a thinner slice... that's what causes this idea of context rot."* — Memory Context Management [01:31]
