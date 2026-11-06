# Front Line: Shelf vs Gateway

Two ways to put a 45-skill library in front of a model. Both are measured on
this machine, with the same model doing the picking.

## The two modes

| | shelf | gateway |
|---|---|---|
| what the harness is given | every skill | the gateway skill only |
| what the model sees at turn 0 | 45 skill descriptions (44 frontmatters + virtual `local`) | 4 meta-tool schemas |
| tokens in context for selection | **8,208** | **691** |
| how a skill is found | the model reads the descriptions and picks | BM25 over every skill body, then one contract on demand |
| how a tool is learned | read the whole `SKILL.md` | one contract, then one section |
| how output is bounded | whatever the tool prints | 8 KB cap, field projection, disk buffer |

The **shelf** mode is the plain Agent Skills specification: progressive
disclosure, where the frontmatter is always in context and the body is read
on demand. It is the default, and the collection is built for it — every
active skill declares the full `agentskills.io` frontmatter so it stays
independently portable.

The **gateway** mode is the Uber OmniMCP shape: one proxy in front, four
meta-tools, and only what a task actually needs entering the context.

## The measurement

`orchestration/omnicli/tests/compare_pickers.py` runs the same 61 golden routing
queries two ways, with the same local model (Qwen3.6-35B Genesis) doing the
picking:

```
PICKER COMPARISON   61 golden queries   model=qwen3.6-35b
  shelf   (read 45 skill descriptions)  top1  54/61 ( 88.5%)    713 ms/query
  gateway (omnicli BM25 index)    top1  60/61 ( 98.4%)     23 ms/query
  delta                            top1  +6
```

The gateway number was 57/61 before the 2026-10-30 alias pass. The shelf
picker reads descriptions only, so its 54/61 is unchanged.

(The shelf prompt is 44 real frontmatters plus the virtual `local` skill that
owns the endpoint tools; a harness would see the 44.)

The seven cases where the shelf picker is wrong are the failure mode the
golden set was built to catch — a *neighbouring* skill wins on a shared word:

- `what rules should I follow before pushing code` → `github-architect`
  instead of `review-hub`
- `extract text from a scanned document` → `markitdown-cli` instead of `ocr`
- `how much gpu vram is free right now` → `deck` instead of
  `litellm-vram-switcher`
- `search my knowledge base …` → `notes-index` instead of `graph-memory`
- `batch several shell commands into one cloud request` → `nvidia-nim`
  instead of `openrouter-free`
- `split a task across subagents and judge the result` → `swarm-contract`
  instead of `agentic-engineering`
- `check which local inference servers are online` → `deck` instead of
  `local`

The gateway's single miss runs the other way: for `decide which model should
handle this prompt before answering`, the shelf picks `eval-router` (correct)
and the gateway picks `pplx-decider`, because the query's six generic tokens
all appear in the decision skill and the re-ranker does not separate them.
That is a lexical router's blind spot, not a capability gap — and it is
recorded rather than excluded.

## Why the gap grows with the library

At 45 skills the frontmatter still carries enough signal to route most
queries. The SkillRouter attention analysis puts the routing signal at:

| source | share |
|---|---|
| body (`SKILL.md` content) | **91.7%** |
| name | 7.3% |
| description | 1.0% |

Stripping bodies costs **37–44 points** of routing accuracy. So the shelf
mode is fine at 45 skills and degrades as the library grows — the Databricks
study measured correct selection falling from 88% to 52.6% between 52 and
202 skills, with two thirds of the failures coming from picking wrong or
picking nothing, not from token count.

The gateway searches bodies, so it keeps the 91.7% signal at any library size.
That is the whole argument for it: not speed, and not the 8,208 tokens, but
**access to the signal the frontmatter throws away.**

## The switch

There is no `skills-frontline` binary. The mode is a one-line state file read
by `sync-skills`, which already decides what each harness receives:

```bash
cat ~/.config/skills-frontline        # shelf (default) or gateway
echo gateway > ~/.config/skills-frontline && sync-skills --push
echo shelf   > ~/.config/skills-frontline && sync-skills --push
```

`SKILLS_FRONTIER=gateway` overrides the file for a single run, and
`SKILLS_GATEWAY_SKILLS` chooses which skill(s) the gateway harness keeps.
`sync-skills verify` checks the mode it actually applied.

**Nothing is destroyed by either mode.** The skills stay upstream, stay
published to the bundles, and stay byte-identical. The switch only changes
what a harness is told about up front. `shelf` restores the full front line
in one sync.

## Why it was archived, and why it came back

`omnicli` was retired on 2026-10-20, five hours into the day it was built,
in favour of the plain Agent Skills specification. The stated reasons:

> omnicli archived rather than deleted: it duplicated the per-skill CLIs and
> its catalog had drifted from them.

Both were real. The duplication is still there — `orchestration/omnicli/scripts/`
holds forks of the skills' own CLIs. The drift has since been fixed: the
catalog now derives its contracts from the real scripts, the `local/decide`
summary no longer names a model that stopped serving that port months ago,
and the four local endpoints have real extracted contracts instead of empty
ones.

An audit on 2026-10-23 fixed the rest of what the gateway claimed and did not
hold — a re-ranker mode that silently did nothing, a cap the elision banner
could exceed, two divergent invoke implementations, and discovery that
implied exposure. See `orchestration/omnicli/AUDIT.md`.

It returned to the surface on 2026-10-30 as `orchestration/omnicli`, for a
reason the retirement did not weigh: the executor. `omnicli exec` runs a whole
plan in one turn, so the gateway is now a skill that can *do* the job rather
than only name the tool. The duplication remains the open debt; what changed
is that its value is measured in round trips as well as routing accuracy.

The measurements above are what make the mode reversible instead of
permanent: `shelf` is still the default, and
`echo gateway > ~/.config/skills-frontline` is there when the library grows
past the point where frontmatter routing holds.
