#!/usr/bin/env bash
# jev-cli wrapper — typed decisions you can edit and re-run from the Desktop.
#
# Pick a backend with MOD= and a question type with TYPE= in the block below.
#   MOD   imajev (:8089) | vllm (:8083) | jev (local GGUF, no server)
#   TYPE  choice | score | noul
#
# Servers start automatically on first use.

set -uo pipefail

case "${1:-}" in
  -h|--help)
    cat <<'EOF'
Usage: decide.sh
Environment variables:
  MOD      imajev (:8089, default) | vllm (:8083) | jev (local, no port)
  TYPE     choice (default) | score | noul
  STATE    text state to evaluate
  QUESTION question to answer
  OPTIONS  comma-separated labels (for choice/score)
Exit codes: 0 success; 1 request/model error; 2 invalid arguments.
EOF
    exit 0
    ;;
esac

MOD="${MOD:-imajev}"
TYPE="${TYPE:-choice}"

STATE="${STATE:-the pull request changes the payment retry logic from 3 to 7 attempts}"
QUESTION="${QUESTION:-what is the risk of this change}"
OPTIONS="${OPTIONS:-keep,draft,discard}"

SCRIPT="$(dirname "$0")/decide.py"

echo "model : $MOD"
echo "type  : $TYPE"
echo "state : $STATE"
echo "q     : $QUESTION"
echo "opts  : $OPTIONS"
echo

case "$TYPE" in
  noul)
    exec python3 "$SCRIPT" --model "$MOD" "$STATE" "$QUESTION" --type noul
    ;;
  score)
    exec python3 "$SCRIPT" --model "$MOD" "$STATE" "$QUESTION" "$OPTIONS" --type score
    ;;
  *)
    # comma list -> JSON object of labels, which is what the choice primitive expects
    json=$(python3 - "$OPTIONS" <<'PY'
import sys, json
labels=[p.strip() for p in sys.argv[1].split(",") if p.strip()]
print(json.dumps({l: l for l in labels}))
PY
)
    exec python3 "$SCRIPT" --model "$MOD" "$STATE" "$QUESTION" "$json" --type choice
    ;;
esac