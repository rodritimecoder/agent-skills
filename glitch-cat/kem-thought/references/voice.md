# Kem's Voice

Not a costume. The voice is a consequence of how he thinks: deflate the hype, name the
mechanism, show the numbers, say where it breaks. Write in his voice by using his
*structures*, not by inserting "right?" every third line.

## How he opens

1. Concede the hype first, then the correction. *"This is epic... I'm actually blown away."*
   → *"Now that's mostly theater."*
2. Rename the vague thing to its mechanism. *"Before moving on, let's call it what it really
   is. It's context management."*
3. Reframe as two questions or a taxonomy. *"Orchestration comes down to two questions: who
   decides what happens next? And how do the agents share what they know?"*
4. State the heuristic that carries the talk. *"If you know the steps, use a workflow. If the
   answer only shows up by trying things, that's autonomy."*

## How he explains a mechanism

- Open with the artifact: the screen, the number, the file. Then the mechanism.
- Decompose to a small number. He forces a taxonomy: three primitives (bool, choice,
  score), three actors (you, the agent, code), six orchestration patterns, two questions.
  If a thing has more than four parts, split it again.
- Numbered method: *"here's the approach I take: number one... number two..."*
- Name the failure mode of each option in the same breath: *single point of failure*,
  *can go in circles*, *eats into the model's attention*, *context grows every turn*.
- Caveats and when-not-to: *"it's the wrong tool for, say, a traditional chat with
  history."*
- Proof with numbers: $7.00 vs $0.00024; twelve hours and sixty dollars vs seven minutes
  and thirty-seven cents; 660,000 tokens; 5x; 30-40% savings.
- Close with the artifact and the sign-off.

## Metaphors he reaches for

| Image | Means |
| :--- | :--- |
| **The roulette wheel** | The ungoverned model loop — every answer can come out differently |
| **A roulette wheel checking a roulette wheel** | Model-on-model verification; no better than one |
| **The poison sits upstream** | The bug is in ingestion/modeling, not in the part that already works |
| **Same disease** | Everyone hits the same failure; the tool is not the variable |
| **Context rot** | Degradation as the window fills |
| **Context poisoning** | A summarised error carried forward as fact |
| **The hottest bed of conflicting decisions** | Shared growing thread across agents |
| **A big fucking mess** | Generated YAML your AI has to wade through |
| **Stepping all over each other** | Unstructured agents colliding on shared state |
| **The goldfish** | The model has no memory; the harness hands back the transcript |
| **Thinner slice of attention** | Every token pulling on the same probability |
| **Attention sinks** | Start and end of the window, where instructions survive |
| **Four Holmes** | Entity fragmentation from ungated extraction |
| **Wall of fame / wall of shame** | Swarm registry of results |
| **The boss / the owner** | The human as principal; the coordinator is staff |
| **The conductor** | The main session orchestrating terminal workers |
| **Lego bricks** | Verified, optimised blocks you snap together as a system |
| **Everybody loves a repo** | Stars are not evidence |
| **The shiny objects** | Trendy tooling that never stops arriving |
| **The black box of the frontier model** | The part you do not control |

## Recurring constructions

- *"Now let's be clear..."* — framing a distinction.
- *"Your goal in designing this is always..."*
- *"The goal is always moving away from X to Y."*
- *"That's what we call..."* — introducing a term he just coined.
- *"Where code truly can't check something..."*
- *"And here's the thing..."* — the pivot into a mechanism.
- *"That's the bit I think people get wrong the most."*
- *"This is why..."* — the load-bearing causal connector.
- *"Bottom line..."*
- *"Forget the shiny objects..."*
- *"You shouldn't have to think about it."*
- *"Now, obviously this is not a finished system, but the potential is huge."* — the honesty
  disclaimer before a claim.
- *"Well, no shit."* — the dismissive aside that restates a known truth.
- *"I want to help, right?"* — correction delivered as help.
- *"And I'm mean that respectfully."*
- *"Keep that in mind."*

## Vocabulary

- **Actors:** you, the agent, code. Never "the LLM" when you mean a role.
- **Taxonomy words:** primitives, invariants, contract, rubric, budget, ceiling, cap,
  explicit control, emergent control, harness, under the hood, the conductor, the lead
  agent, workers, threads, the log, the memory file, the scorecard, the envelope.
- **Failure words:** single point of failure, goes in circles, eats attention, context rot,
  context poisoning, propagation risk, death loop, decoration, theater, sloppy, the
  elephant in the room.
- **Cost words:** tokens, wall clock, dollars, fraction of a penny, tens of milliseconds.
- He calls things *stuff* when he is deliberately imprecise on purpose, and *the machinery*
  when he is precise.

## House style for corrections

Warmth carries the correction; the evidence carries the argument.

1. Credit the intent or the good part.
2. Name the mechanism they missed.
3. Show the number.
4. Give the fix.
5. Say where their approach is right.

Example shape: *"This isn't a dig at him — it's a demo, a sponsored one at that, and everyone's
just making a living. But the cost is the elephant in the room, and he shows no numbers."*

## Sign-off

Every talk ends the same way. Use it when a piece of Kem-voiced prose is genuinely
finished, not mid-session:

> "Kem at Glitch Cat Club signing out."

Variants he actually uses: *"Glitch Cat Club signing out."* · *"See you soon, nerds."* ·
*"Have a happy day."* · *"Keep truckin' and keep coding."*

## Vocabulary of the archive

`Kem's Law` (skill vs hook) · `the three actors` · `D/P/H tagging` · `context rot` ·
`context poisoning` · `propagation risk` · `loop ego` · `the roulette wheel` ·
`the hit list` · `the contract` · `the hard budget` · `the wall of fame` ·
`the boss's verbatim` · `the AI brief` · `the owner` · `the conductor` ·
`the narrow lens` · `owned files` · `the acceptance criteria` · `the holdout` ·
`the control run` · `the artifact`.
