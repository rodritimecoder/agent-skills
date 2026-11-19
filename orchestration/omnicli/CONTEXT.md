# omnicli — Context

SKILL.md is the entry → *tools*; this file maps *files and gates* + machine-local facts. Port/model facts: root [CONTEXT.md](../../CONTEXT.md) — link, never copy.

## Layout

```
orchestration/omnicli/  canonical
|- SKILL.md  entry/catalog
|- CONTEXT.md  map/catalog
|- catalog/  [catalog] aliases.json
|- references/  [factory] retrieval-architecture, code-mode-sdk,
|   skill-stack-architecture, agent-skills-checklist
|- examples/  [shelf]
|- harnesses/  [adapters]
|- tests/  [gates] skillcheck.py
\- scripts/  [tools]
~/.local/share/omnicli/  [state] catalog.db, bindings/, sessions/, trace.jsonl

surface/omnicli -> ../omnicli -> orchestration/omnicli
```

## Routing

| Intent | Read first | Then call | Proof |
|---|---|---|---|
| discover a capability | SKILL.md § discovery | omnicli search | omnicli eval |
| read one contract | SKILL.md § describe | describe --section | skillcheck.py all |
| batch/chain intents | skill-stack §4 + code-mode-sdk | omnicli exec + parallel() | a live plan |
| understand ranking | retrieval-architecture.md | index --rebuild | benchmark table |
| author/lint a skill | agent-skills-checklist.md | verify_agent_skills.py --strict | exit 0 |
| harness drift | harnesses/index.md | harness detect/verify | sync-skills verify |
| ports/models | root CONTEXT.md | omnicli status | ports.py check |

## Facts

- State in ~/.local/share/omnicli/: catalog.db, bindings/, sessions/, trace.jsonl; counts from omnicli status (never hardcode).
- index_body: false in catalog/aliases.json keeps omnicli docs out of catalog: reach this file by link/path, not omnicli search.
- Canonical edit orchestration/omnicli/ (surface/bare symlinks); propagate, publish when verified. Root CONTEXT links: ../../CONTEXT.md (SKILL.md), ../../../CONTEXT.md (references/).
- Doc-drift gate: `python3 tests/doc_drift_check.py --json` proves the plugin registers exactly search/invoke/exec, the MCP face mirrors it (`omni_exec` behind `OMNICLI_MCP_ALLOW_EXEC=1`), live docs carry no stale tool-count claims, and documented commands resolve; exit 0 clean, 1 drift.

Walk test: past ~500 tokens, payload → references/, leave a pointer.
