#!/usr/bin/env bash
# memory cycle — one pass, in order, stopping at the first failure.
#
#   observe  transcripts -> notes
#   dream    notes -> wiki + injected header (crossref, gaps, promote)
#   gate     links + budget; a red gate fails the unit, so a cron cannot
#            report success over a broken memory
#
# Called by memory-dream.service. Safe to run by hand.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${MEMORY_ROOT:-$HOME/.memory}"
PY="${PYTHON:-python3}"

"$PY" "$HERE/mem.py" --root "$ROOT" init >/dev/null

if [ -f "$HERE/agy_ingest.py" ]; then
  "$PY" "$HERE/agy_ingest.py" --root "$ROOT" 2>&1 | sed 's/^/  /' || true
fi

"$PY" "$HERE/observer.py" --root "$ROOT" 2>&1 | sed 's/^/  /'
"$PY" "$HERE/dreamer.py" --root "$ROOT" 2>&1 | sed 's/^/  /'
"$PY" "$HERE/links.py" --root "$ROOT"

exit 0
