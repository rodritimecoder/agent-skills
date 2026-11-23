# `omnicli` Discovery Architecture (exec-only)

How `omnicli` finds a skill and invokes its tool: one `omnicli exec` plan that
reads local files, asks for one exact contract, and emits one bounded result.
There is no ranking step, no relevance score, and no discovery tool verb.
For the hands-on ladder and proof, see [skill-discovery.md](skill-discovery.md).

---

## One plan, one turn

```
omnicli exec plan.mjs  (node:vm inside bubblewrap, strict by default)
   │
   ├── omnicli_skills  lsSkills()            -> [{ name, description }, …]
   │                   readSkill(name)       -> full SKILL.md, path-confined
   │                   readResource(name,rel)-> one references/assets/scripts file
   │
   ├── omnicli_tools   describe(toolId)      -> contract.inputSchema (exact)
   │                   invoke(toolId, args) -> bounded, projected output
   │
   └── result({ ok, tool, proof, data })     -> one ~8 KB bounded reply
```

Window reads are ordinary local filesystem reads against the canonical skills
tree bound into the sandbox — no ranking call, no bridge round-trip, no
network. The plan picks the skill by its `description`, reads only the level it
needs, then stops. Nothing is preloaded at turn 0.

---

## The Description Field Is the Cheapest Lever

`description` in frontmatter is what the plan matches on at L1, so it is the
highest-leverage text a skill author writes. Following the Agent Skills spec
(*"when to use it"* + *"specific keywords that help agents identify relevant
tasks"*), write user vocabulary into it rather than implementation jargon.
This guidance holds regardless of discovery mechanism and is the one useful
survivor of the retired ranking research described below.

---

## One bounded result

Every intermediate — skill bodies, reference files, tool output — lives in a
JavaScript variable inside the VM. Only the synthesized `result()` object
leaves, and its fields should be sliced (`slice(0, BOUND)`) to stay under the
shared ~8 KB cap. Do not echo a whole `SKILL.md` into the prompt.

`omnicli invoke <tool_id>` applies the same bound outside a plan:
`--omni-project`, `--omni-jq`, `--omni-grep` and `--omni-buffer` shape the
output, and `--omni-max-bytes` is a hard ceiling at any cap size.

---

## Guards (the three hard legs)

`tests/routing_gate.py` treats three checks as hard:

| Leg | Script | Proves |
| :--- | :--- | :--- |
| `exec_only_flow` | `exec_only_flow.py` | discovery happens in one exec plan; no discovery tool verb |
| `skills_bridge_flow` | `skills_bridge_flow.py` | one strict plan reads all three levels and invokes exactly one tool |
| `doc_drift` | `doc_drift_check.py` | documented tool surface matches the live surface |

`tests/overfit_check.py` is a standalone diagnostic of the curated routing
metadata, not a gate leg.

`tests/discovery_mutant.py` and `tests/leg_mutants.py` splice a marked exit-1
into copies of these legs and require the real gate to go red while naming the
leg; the clean gate must stay green. A gate that cannot fail is not a gate.

---

## Historical note — retired ranking research (not current policy)

An earlier version of omnicli used a two-leg ranking pipeline over skill
bodies: a lexical leg over full bodies plus curated aliases, and a dense leg
embedding descriptions, fused by rank. Experiments covered margin-gated fusion,
distilled question snapshots, and chunk-length penalties. All of it is retired
and removed from the codebase. None of it describes current behavior, and none
of it is a recommended workflow. The research is noted here only so readers of
older notes can tell that it is history.

---

## Why This Exists & Provenance

Moving selection off the turn-0 prompt shelf onto local file reads inside a
sandbox keeps per-turn context cost flat as the skill collection grows: the
model sees one contract and one bounded result, never the whole shelf.

- **Architectural lineage:**
  1. [Uber's MCP Gateway](https://www.uber.com/au/en/blog/designing-mcp-gateway/): late-binding catalog discovery, single-contract `describe`, bounded `invoke`.
  2. [Cloudflare's Code Mode](https://blog.cloudflare.com/code-mode/): sandboxed JS plans (`omnicli exec`) keeping intermediates in variables rather than round-trip prompt turns.
  3. **Retired stdio MCP server:** Built, conformance-tested (28 checks), and retired to `archived/omnicli-mcp/` because JSON-RPC tool round-trips burn prompt tokens while JS variables in `node:vm` cost nothing.
