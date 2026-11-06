# Sources — `frontend-uat`

**Capture verified. Reel identity unresolved.**

## The source

| | |
| :--- | :--- |
| Creator | Kem Glitch (`kem_glitch`, Glitch Cat Club) |
| Capture | `2026-10-16_unmatched_fast_frontend_uat_jev_capture` |
| Mined | 2026-10-16 |
| Instagram reel | **unidentified** |
| Media | `source.mp4`, `transcript.md`, 46 frames in `visuals/` |

The capture was previously attributed to Reel `DeKBMCQNRXU`. That was wrong: the URL
resolves to the Glitch Orchestra alignment reel. The attribution was retracted on
2026-11-02, and the capture is now vaulted without a reel claim.

## Shown in the capture

Excerpts from `transcript.md`; ellipses mark omitted words. The ASR spells JEV as
"Jeff" in places, and the quotes are left exactly as transcribed.

| Claim | Quote | Time |
| :--- | :--- | :---: |
| UAT is slow and expensive per run | "in reality it's just too slow it can also get quite expensive" | 00:10 |
| JEV is a decision model, not a generator | "it doesn't actually generate text it just returns a tight answer with a probability but it does it really quickly like in half a second" | 00:34 |
| The page is handed over as a clickable list | "in this example the page gets handed to Jeff as a list of everything that user can click" | 00:34 |
| Code clicks; JEV reads the screen back | "Jeff's then able to make a decision and the code can do the clicking Jev then reads the screen back and says whether it did what the test asked" | 00:58 |
| Speed comes from not generating | "It's faster because Jeff never needs to write anything" | 01:26 |
| Cost is one lab observation, hedged | "seven dollars ... against what zero point zero two four cents or whatever it is ... this is a lab experiment I'm not selling you anything" | 01:26 |

## Modeled by this skill

| Choice | Why it is not attributed to the capture |
| :--- | :--- |
| CLI surface (`doctor`, `candidates`, `plan`, `run`) and exit codes | Implementation shape for agents; the capture shows a demo, not a CLI. |
| `--min-p` refusal on a weak pick | Our guard; the capture shows the pick, not a threshold policy. |
| `--workdir` step ledger | Our evidence requirement (`eval-pipeline`), not shown in the capture. |
| Integration with the local `h2o-lightning-4b` server on `:8083` | Workstation binding; the capture uses Kem's own JEV instance. |
| The `playwright-rs uat` comparison | Our composition with the installed browser tooling. |

## Unverified

- The "over 25,000×" multiplier is arithmetic on the capture's own hedged figures
  ($7.00 vs $0.00024), not a published benchmark.
- The capture's reel ID. The ledger lists it as an unmatched capture.

## Rule

If a claim about Kem's method is not in the "Shown" table, it is modeled. Do not present
it as his.
