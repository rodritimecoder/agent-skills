# DE-RISK — `academic/academic-pipeline-v2` — 2026-10-25

Phase 1 of the audit de-risk plan. Each command below was run in the checkout and
the output is recorded verbatim (stderr/stdout merged).

## Command 1

```bash
python3 academic/zoom-recorder/scripts/zoom_download.py --help
```

```
Traceback (most recent call last):
  File "/home/runner/work/my-agent-skills/my-agent-skills/academic/zoom-recorder/scripts/zoom_download.py", line 24, in <module>
    import requests
ModuleNotFoundError: No module named 'requests'
```

## Command 2

```bash
python3 glitch-cat/eval-router/eval_router.py --help
```

```
usage: eval_router.py [-h] {route,exec,stats,harvest} ...

Kem Glitch Self-Calibrating Eval Router CLI

positional arguments:
  {route,exec,stats,harvest}
    route               Route prompt and show tier classification without
                        executing
    exec                Execute prompt with routing, speculative eval, and
                        automatic fallback
    stats               Display performance, accuracy, and dollar savings
                        metrics
    harvest             Inspect harvested evaluation failures for calibration

options:
  -h, --help            show this help message and exit
```

## Command 3

```bash
head -30 glitch-cat/semantic-cache/scripts/cache_engine.py
```

```
#!/usr/bin/env python3
import datetime
import hashlib
import json
import math
import re
import sqlite3
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class LocalEmbedder:
    """Embed against the embedding slot, with a labelled offline fallback.

    The slot at :8087 hosts exactly two candidates -- bge-small-en-v1.5 (384d)
    and EmbeddingGemma-2 (768d) -- and the offline fallback is a third, 128d
    hash space. Vectors from different spaces are not comparable, so every
    embedded row records which space it came from and `get` skips the rest
    instead of silently scoring them 0.0.
    """

    def __init__(self, endpoint: str = "http://127.0.0.1:8087/v1/embeddings", timeout: float = 0.5):
        self.endpoint = endpoint
        self.timeout = timeout
        self.last_source = "unknown"

    def embed(self, text: str) -> List[float]:
        clean_text = text.strip()
        try:
```

## Command 4

```bash
python3 ports.py list
```

```
PORT   SLOT             CARD         DEFAULT                    ROLE
8080   llm              many (7)     Qwen3.6-35B-A3B-Uncensore  Primary generative LLM — chat, code, long-form writing, prose projection
8081   audio            many (3)     nemotron-asr               Speech-to-text, text-to-speech, forced alignment, voice cloning
8083   decision         one-of-many (5) h2o-lightning-4b           The JEV decision engine slot - bool / choice / score primitives
8082   decision-engine  single (1)   StartLux-Decision-v1.1-4B  Internal engine of the :8083 decision slot - prompts in one micro-batch, not a client-facing API
8089   decision-fallback single (1)   Imajev-4B                  Secondary decision engine — Imajev-4B chat path, or letter/readout with READOUT=1
8084   ocr-crispembed   single (1)   CrispEmbed (PP-OCRv6 smal  Scene text — 2D bounding boxes and structured markdown
8085   ocr-lighton      single (1)   LightOnOCR-3-0.8B            Documents, PDFs and slides — fast prefill, high-throughput markdown
8086   reranker         single (1)   jina-reranker-v2-base-mul  Cross-encoder reranking for RAG
8087   embed            one-of-many (2) bge-small-en-v1.5          Vector embeddings for RAG and semantic caching
8088   grounding        single (1)   WeVisOne-VL-4B             Word-level OCR boxes, open-vocab detection, referring localization, pointing, counting
4000   litellm          infra        LiteLLM gateway            OpenAI-compatible failover gateway; routes to llama-swap
8000   llama-swap       infra        llama-swap                 Model multiplexer behind LiteLLM; swaps models in/out of VRAM
3010   kasmvnc          infra        KasmVNC (podman)           Live interactive web desktop for browser inspection
9222   cdp              infra        Chromium DevTools          CDP endpoint used by fast-cdp and Playwright
9223   cdp-internal     infra        labwc forwarder            Container-internal forwarder 0.0.0.0:9222 -> 127.0.0.1:9223
8761   clip-box         infra        h2o-lightning shim         Box grounding and typed decisions; Python shim, box questions need LIGHTNING_BOX_ENABLED=1
8621   clip-box-backend infra        llama-server (private bac  Pinned stock llama.cpp the h2o-lightning shim drives; one full-context slot, loopback only
```

## What a CI runner with no credentials and no GPUs cannot verify

- **`zoom_download.py --help` did not even reach its argument parser.** It fails
  at `import requests` with `ModuleNotFoundError`. That is a dependency problem,
  not an invocation contract. A bare CI runner can confirm the failure mode, but
  it cannot verify whether the script's actual CLI supports transcript/keyframe
  fetching until `requests` (and its other imports) are installed and the script
  executes. The transcript/keyframe mode is therefore still **unverified**.
- **`eval_router.py --help` is verifiable** without credentials or GPUs: it
  printed its real subcommand set (`route`, `exec`, `stats`, `harvest`). What a
  no-credential runner **cannot** verify is any `exec`/`route` run that actually
  dispatches to local models (ports 8080/8083) or OpenRouter, because those need
  the GPUs/live services and an API key respectively.
- **`cache_engine.py` can be opened and read** (it is a library, not a CLI). A
  no-GPU runner cannot verify the semantic cache behavior, because its
  `LocalEmbedder` targets `:8087/v1/embeddings` and only the labelled offline
  fallback path would run without that embedding slot.
- **`ports.py list` describes the GPU box**, including the Qwen3.6-35B-A3B local
  model on port 8080 and the decision slot on port 8083, but a CI runner with no
  GPUs cannot verify any of those cards are actually loaded or responsive.
