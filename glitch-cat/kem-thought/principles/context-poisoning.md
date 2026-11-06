# Context Poisoning Is Not Context Rot

**Rule:** Rot degrades. Poisoning corrupts. A superseded fact retrieved into the window is not noise — it is a permanent, compounding lie.

**Why:** It lands in the session, it stays there, it shapes every answer after that, and it compounds because every answer gets built on it. This is the symptom people describe as the model going stupid.

**In practice:**
- Retrieved context is untrusted input. Gate it; do not trust it.
- Supersede stale facts at the source instead of explaining them in the prompt.
- When the same fact is stated twice, one of them has to die in code.
- Separate it from rot explicitly in your notes: rot is degradation, poisoning is corruption.

**Kem:** *"It lands in the session, it stays there and it shapes every answer after that. That's called context poisoning. The worst part is that it compounds because every answer gets built on it."* — Memory Context Management [01:12]
