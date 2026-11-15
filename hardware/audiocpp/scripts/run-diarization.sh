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

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
exec python3 "$SCRIPT_DIR/audiocpp_cli.py" diarize "$@"
