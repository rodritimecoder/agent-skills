# Model the Domain Before You Fill It In

**Rule:** Ontology first — decide what exists in your world and how it connects. The schema comes from that decision. Auto-linking is not modelling.

**Why:** If the person in your phone is Dave, David, and Dave Smith, the model has no idea they are the same person. Microsoft ran GraphRAG on Sherlock Holmes and got four different Holmes: Sherlock, Sherlock Holmes, Mr. Holmes, Holmes.

**In practice:**
- Decide the columns before anyone fills in the rows.
- Gate entity creation. Never let a model invent names — that is how you get duplicates everywhere.
- Everything serious ends up a hybrid: deterministic structured schema plus lexical/semantic retrieval plus gated extraction. You are picking which price to pay; pick deliberately.
- Grep-and-jump through generated YAML is not a knowledge graph. It is a big mess your AI has to read through.

**Kem:** *"Before anyone fills it in, someone has to pick the columns. What exists in your world, whatever it's called, how it connects, that decision is called ontology. And the columns are your schema."* — Graph Memory Rant [00:59]
