#!/usr/bin/env bash
# run-diarization — Nemotron 3 Diarization via `audiocpp diarize`.
#
# Compatibility wrapper kept for existing callers and AI/sh/ symlinks;
# the implementation now lives in audiocpp_cli.py (`audiocpp diarize`).
#
#   ./run-diarization.sh talk.mp4
#   ./run-diarization.sh talk.mp4 --vtt talk.vtt --names Kem,Chase,Vince
#   ./run-diarization.sh *.mp4 --out /tmp/diar

set -euo pipefail

case "${1:-}" in
  -h|--help)
    printf 'Usage: %s <file...> [flags] ...\n' "$(basename "$0")"
    printf '  e.g. run-diarization.sh talk.mp4 --vtt talk.vtt --names Kem,Chase,Vince\n'
    echo 'Exit codes: 0 success; 1 runtime/validation error; 2 invalid arguments (usage error); other non-zero values are script-specific.'
    exit 0
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
exec python3 "$SCRIPT_DIR/audiocpp_cli.py" diarize "$@"
