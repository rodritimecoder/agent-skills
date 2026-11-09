# Foundations Over Shiny Objects

**Rule:** The tooling changes every quarter; the mechanism does not. Learn under the hood.

**Why:** Models change, things improve, and the shiny objects will never stop — but understanding how it really works under the hood is what gives you the hugest value.

**In practice:**
- Reverse-engineer the harness before you adopt it: read the transcript, measure the token footprint, find the invariants, rebuild it in your own stack.
- It is not about the tooling and the harness. It is about the foundations.
- Climb the retrieval ladder only when the rung below fails: folders and keyword search, then a per-folder index file, then semantic search, then a graph. A graph can be the fastest and cheapest to run and still be the wrong place to start, because the modelling cost is real and maintenance, not setup, is the work.
- Measure the lever before you buy it. In Kem's own RAG build a 67 MB local embedding model beat the standard 640 MB one, and query rewriting and the reranker were dropped because they added nothing. Index the question someone would ask, and let no entry in without one exact quote from its source.
- Watch out for the ones that arrive with three thousand stars and no numbers.

**Kem:** *"models change, things improve, and the shiny objects will never stop, but fundamentally, understanding how it really works under the hood is what gives you the huggest value"* — Memory In AI Context [04:04]

*"They've all come to the same conclusion, guys. Simple folders and rip-grep."* — Do You Need a Graph? [01:05]

*"The biggest lever, a little sixty-seven megabit local embedding model, which beat the standard six forty megabit one that everyone always suggests."* — Free Cerberus RAG System [00:57]
