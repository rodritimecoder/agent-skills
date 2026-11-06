# Architecture — Fast Frontend UAT with a Decision Model

Source: Kem Glitch (`kem_glitch`), *Fast Frontend UAT with JEV* capture, mined
2026-10-16. The Instagram reel is unidentified. The earlier `DeKBMCQNRXU` attribution
was retracted on 2026-11-02: that URL resolves to the Glitch Orchestra alignment reel.
Vault: `kem_glitch/2026-10-16_unmatched_fast_frontend_uat_jev_capture/`.

---

## The two lanes

```
   Generative multimodal UAT (Claude + Chrome)
   ┌──────────────────────────────────────────────────────────────┐
   │ capture viewport ─► multimodal LLM (3–8 s) ─► stream thoughts│
   │ and plan ─► CDP click ─► repeat for every button             │
   │                         total: minutes · ~$7.00              │
   └──────────────────────────────────────────────────────────────┘

   Decision-model UAT (this skill)
   ┌──────────────────────────────────────────────────────────────┐
   │ [D] extract the clickable targets as an indexed array        │
   │ [P] decision model returns the target index + probability    │
   │ [D] code performs the click over CDP                         │
   │ [P] model reads the screen back: did the assertion hold?     │
   │                    total: seconds · ~$0.00024                │
   └──────────────────────────────────────────────────────────────┘
```

## Why it is faster — the actual reason

Not a smaller model. **Nothing is generated.** A generative agent must emit the
reasoning and the coordinates as text tokens before anything happens; a decision
model returns a distribution over a closed set of candidates and stops. The
transcript puts it plainly: *"Jev is then able to make a decision and the code can
do the clicking. Jev then reads the screen back and says whether it did what the
test asked."*

That is why the page is handed over as a **list of everything the user can click**
rather than as pixels: the candidate set *is* the question, and indexing it makes
the answer a one-token choice instead of a coordinate prediction.

## Where the two model turns go

1. **Choose the target.** `[P]` — `choice` over `uat-1: button 'Complete purchase'`,
   `uat-2: button 'Apply coupon'`, … The selected ref is executed by deterministic code.
2. **Verify the outcome.** `[P]`, opt-in — `bool` over the post-action screenshot:
   *did the confirmation appear?* ([YES/NO, Prob 0.99] in the capture's framing.)

Everything between them — extraction, navigation, the click, text and URL assertions —
is `[D]`. Deterministic work stays deterministic; only the two genuinely perceptual
steps spend a model turn.

## Benchmark economics

| | Latency | Cost per suite |
| :--- | :--- | :--- |
| Multimodal generative agent | minutes | ~$7.00 |
| This loop | seconds | ~$0.00024 |

The capture frames it as over 25,000× cheaper, as a lab experiment rather than a
product claim; Kem hedges the figure in the transcript (*"or whatever it is"*).

## Boundaries

- **Not a replacement for a real browser test runner.** It does not manage fixtures,
  parallelism across machines, or reporting — it is one journey, fast.
- **Deterministic first.** When the element's label contains the intent's words,
  `fast-cdp uat --goal` needs no model at all. This skill exists for the cases where
  vocabulary does not match, where the target is identified visually, or where the
  assertion itself is a question about what is on screen.
- **The decision model judges; it does not plan.** Multi-step journeys are expressed
  as repeated calls (or a plan file per step), not by asking the model for a sequence.
