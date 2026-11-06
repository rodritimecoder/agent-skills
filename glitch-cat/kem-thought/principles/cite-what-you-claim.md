# Cite What You Claim

**Rule:** Every claim that comes from a file names the file, and every quotation is verbatim. An editorial correction goes in `[brackets]`, an omission goes in an ellipsis. Never a silent rewrite.

**Why:** It was the cheapest accuracy win measured in the whole LLM-wiki benchmark. Plain Claude Code verified 70% of its answers on a 200-file test; told to cite a source for every claim before answering, it verified 92.5%. One instruction, no ingest step, no graph, no new index. And the benchmark's own table shows why the metric is "verified" rather than "correct": one citation-first tool scored 77.5% correct but only 60% verified — being right and being provable are different outcomes.

**In practice:**
- Cite before answering, not after. A citation added in review is a justification; a citation written with the claim is a trace.
- Quote verbatim, warts included. If the transcript said "Cloud Code", the quote says "Cloud Code" and the correction lives in `[Claude Code]` or in a separate corrections table. Silent fixes turn a citation into a paraphrase wearing a citation's clothes.
- The instruction produces the behaviour; the hook only enforces it. A gate that refuses an uncited answer does not make a model cite — it stops a model that didn't.
- What the gate can prove is narrow: the file exists, the line exists, the quoted words are in it. Whether the quote *supports* the claim needs a judge with fresh context. Don't ask a substring check to do an argument's job.
- Prefer a structural citation the machine can check (`path:line`, `[MM:SS]` against the transcript) over a bare URL. If it cannot be resolved, it cannot be refused.
- Run the gate on the answer, not on the plan. The claim is the thing that ships.

**Kem:** *"Look, if it was me, I'd keep plain [Claude Code], give it a structure like ICM, add a hook that makes it cited sources, keep it simple, stupid."* — LLM Wikis vs Plain Claude Code [01:59]

**The number:** 70% → 92.5% verified answers, 200-file test, plain Claude Code with one cite-your-source instruction. `nvk/llm-wiki` reached 100% correct at ×2.06 tokens; folders plus grep reached 100% at 0.97×.
