#!/usr/bin/env bash
# jev-cli wrapper — typed decisions you can edit and re-run from the Desktop.
#
# Pick a backend with MOD= and a question type with TYPE= in the block below.
#   MOD   imajev (4B vision+text, :8083) | jev (2B, :8085) | jpt (4B, :8084)
#   TYPE  choice | score | noul
#
# Servers start automatically on first use.

set -uo pipefail

MOD="${MOD:-imajev}"
TYPE="${TYPE:-choice}"

STATE="${STATE:-the pull request changes the payment retry logic from 3 to 7 attempts}"
QUESTION="${QUESTION:-what is the risk of this change}"
OPTIONS="${OPTIONS:-keep,draft,discard}"

SCRIPT="/home/rodri/.gemini/config/skills/jev-cli/scripts/decide.py"

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
    # comma list -> JSON object of labels, which is what jpt expects
    json=$(python3 - "$OPTIONS" <<'PY'
import sys, json
labels=[p.strip() for p in sys.argv[1].split(",") if p.strip()]
print(json.dumps({l: l for l in labels}))
PY
)
    exec python3 "$SCRIPT" --model "$MOD" "$STATE" "$QUESTION" "$json" --type choice
    ;;
esac