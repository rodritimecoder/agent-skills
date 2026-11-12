# Decision Backend Contract (`hardware/decision-model/CONTEXT.md`)

Operational contract for the `:8083` decision slot. `SKILL.md` says what the
primitives are; this file says how to add or swap a backend without a tangent.
Read it before touching a backend, a weight file, or a launcher.

## Inputs

| Input | Path |
|---|---|
| Client | `scripts/decision_model.py` |
| Tests | `tests/` |
| h2o shim | `scripts/h2o_serve.py` |
| Slot registry | `../../ports.json` (`id: decision`) |
| Launchers (authoritative) | `/run/media/rodri/AI/sh/` |
| Weights | `/run/media/rodri/AI/models/` |
| Vendor runtimes | `/run/media/rodri/AI/` (never under `AI/sh/`) |

## The slot

`:8083` is one-of-many. The client names the served model and shapes the
request from the model id, not from the port.

| Backend | Wire state | Box type | Answer shape |
|---|---|---|---|
| h2o-lightning-4b | `state.context` + `assets` map | `box` | `box{left,top,right,bottom}`, `present`, `confidence` |
| Valen-Decision-1.5 | `state.messages`, inline `data:image/...` URLs | `bbox` | `bbox[x1,y1,x2,y2]`, `point`, `confidence` (no presence) |
| GLiDE-0.4B | `state.context` | unsupported | text only |

The CLI primitive is always `box`. Only the wire type differs.

## Process: add or serve a backend

1. **Read the vendor guide and the runtime's startup log.** The log states
   version pins and accuracy flags; the guide states the supported quant set.
   *Check:* you can name the runtime version, the quantizer binary, and the
   image/context flags before downloading anything.
2. **Download the vendor files and verify their published hashes.**
   *Check:* `sha256sum -c` passes for every file you will serve.
3. **Quantize only with the vendor's own tool.** For Valen that is
   `build/bin/llama-quantize` from the runtime's source tree. A stock llama.cpp
   cannot load a custom architecture.
   *Check:* the quantized file loads in the vendor server, not just in
   `llama-quantize --dry-run`.
4. **Serve on a scratch port first** (`:809x`), with the exact flags the
   launcher will use.
   *Check:* `/health` is up and `/v1/models` names the file you just built.
5. **Run the acceptance pair:** one text question and one `box` on a real
   image (screenshot or photo). Use the primitive the skill will call.
   *Check:* text returns a probability, box returns four corners and a
   confidence you would accept, `--crop` writes a sensible region.
6. **Place the files.** Weights in `models/<org>/`, runtime in `AI/<name>/`,
   launcher in `AI/sh/` (authoritative). Never put a runtime tree under `AI/sh/`.
   *Check:* `ports.py drift` shows no new weight or launcher divergence.
7. **Register and publish.** Add the candidate in `ports.json`, update
   `SKILL.md` only if the contract changed, then `render --write`, propagate,
   commit only your files, push.
   *Check:* `ports.py check` reports nothing new; `sync-skills` was run after
   the launcher edit.

## Check: done means

- `decision_model doctor` shows `:8083` online.
- `decision_model caps` lists `bool, choice, score, box`.
- One text call and one real-image `box` call succeed, with a saved crop.
- `tests/` pass (`uv run --with pytest python3 -m pytest tests -q`).
- The launcher is executable from `AI/sh/` and restarts cleanly.

If any of these fail, the backend is not done. Nothing else is the task.

## Stop rules

- **Two diagnostic servers maximum.** If isolating a difference needs a third
  configuration, stop and report the difference. Do not build a quant matrix.
- **Synthetic fixtures never gate.** An anomaly on a drawn shape is a report
  line. Only a real screenshot or photo can fail acceptance.
- **Do not invent a stricter gate.** The vendor's published gate applies to the
  vendor's published files. Q5_K_M + Q8 vision is a local build; test it on the
  acceptance pair and report the numbers. Chasing parity with F32 across many
  inputs is a separate task the owner must ask for.
- **An anomaly outside the acceptance path is not investigated.** Write it in
  the final report and move on.
- **Read the startup log before the first test.** Accuracy flags such as
  `--image-min-tokens 1024` are printed there, once.

## Known traps

- Valen's wire type is `bbox`, not `box`. h2o's is `box`. The client maps both.
- Valen has no presence head: `present` is `null`, and only `confidence` gates.
- Small images lose the grounding target at the default token budget.
  `valen.sh` pins `--image-min-tokens 1024`; keep it.
- `sync-skills` rsyncs `AI/sh/` into `launchers/` with `--delete`. A runtime
  stored there is copied into the repo and can delete launchers on the next run.
- Launchers are edited in `AI/sh/`, then propagated; edits made only in
  `launchers/` are overwritten.
- `ports.py check` has a pre-existing `llama-router.sh :8080` violation. It is
  not yours. Use `SKIP_PORTS_CHECK=1` and say so; do not repair the router.

## Outputs

- A candidate entry in `ports.json` and the generated docs.
- A launcher in `AI/sh/` and its propagated copy.
- A client that answers all four primitives against the new occupant.
- This file updated when a trap is discovered, so the next run starts here.
