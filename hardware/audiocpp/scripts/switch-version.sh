#!/usr/bin/env bash
# switch-version.sh — point audio.cpp at a different install and restart :8081.
#
#   switch-version.sh /home/rodri/audio-v0.9.5-bin-ubuntu-x64-vulkan
#   switch-version.sh --status
#   switch-version.sh --rollback
#
# The install is reached through the symlink /run/media/rodri/AI/audio.cpp, so a
# version change is one link flip. This script exists because a flip that is not
# gated is how a build that cannot load its own shared libraries ends up on the
# port: it validates the candidate before touching anything, and restores the
# previous install if the new one fails its health check.
set -uo pipefail

DRIVE="${AUDIOCPP_DRIVE:-/run/media/rodri/AI}"
LINK="$DRIVE/audio.cpp"
LAUNCHER="$DRIVE/sh/run-audiocpp.sh"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REF_CONFIG="$REPO_DIR/references/server.json"
PORT="${PORT:-8081}"
PREV_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/audiocpp/last-switch"

die() { echo "❌ $*" >&2; exit 1; }

health() { curl -fsS -m 2 "http://127.0.0.1:${PORT}/health" 2>/dev/null; }

status() {
  local target
  target="$(readlink -f "$LINK" 2>/dev/null || true)"
  echo "link   : $LINK"
  echo "target : ${target:-<missing>}"
  if [ -x "$LINK/audiocpp_cli" ]; then
    echo "version: $("$LINK/audiocpp_cli" --version 2>&1 | head -1)"
  fi
  echo "config : $([ -f "$LINK/server.json" ] && echo present || echo MISSING)"
  local h
  h="$(health)"
  echo "server : ${h:-🔴 not answering on :$PORT}"
}

# A candidate is usable when its own binaries load and it has a config.
# --version is the gate: the HIP/ROCm builds die on libhipblas.so.3 without the
# ROCm runtime, and that failure has to stop the switch here, not on the port.
validate() {
  local dir="$1"
  [ -d "$dir" ] || die "not a directory: $dir"
  [ -x "$dir/audiocpp_server" ] || die "no audiocpp_server in $dir"
  [ -x "$dir/audiocpp_cli" ] || die "no audiocpp_cli in $dir"
  local v
  v="$("$dir/audiocpp_cli" --version 2>&1 | head -1)"
  case "$v" in
    audio.cpp*) : ;;
    *) die "candidate will not run: ${v:-<no output>}" ;;
  esac
  echo "$v"
}

stop_server() {
  local pids
  pids="$(pgrep -f 'audiocpp_server .*--config' || true)"
  [ -n "$pids" ] || return 0
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  for _ in $(seq 1 20); do
    health >/dev/null || return 0
    sleep 0.2
  done
  pids="$(pgrep -f 'audiocpp_server .*--config' || true)"
  [ -n "$pids" ] || return 0
  # shellcheck disable=SC2086
  kill -9 $pids 2>/dev/null || true
  sleep 0.3
}

start_server() {
  # Fully detached: the server inherits no fd from the caller, so a switch inside
  # a captured shell does not hang waiting for the child's output to close.
  ( cd "$DRIVE/sh" && setsid nohup "$LAUNCHER" >/tmp/audiocpp-switch.log 2>&1 </dev/null & ) >/dev/null 2>&1
  for _ in $(seq 1 25); do
    if health >/dev/null; then return 0; fi
    sleep 0.8
  done
  echo "--- last 15 lines of /tmp/audiocpp-switch.log ---" >&2
  tail -15 /tmp/audiocpp-switch.log >&2 || true
  return 1
}

pin_config() {
  # The install owns its config; the repo copy is the seed when a fresh
  # extraction ships none (v0.9.4 does not ship server.json).
  local dir="$1"
  if [ -f "$dir/server.json" ]; then
    echo "config : kept $dir/server.json"
    return 0
  fi
  [ -f "$REF_CONFIG" ] || die "no server.json in $dir and no seed at $REF_CONFIG"
  cp "$REF_CONFIG" "$dir/server.json"
  echo "config : seeded from $REF_CONFIG"
}

case "${1:-}" in
  ""|-h|--help)
    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  --status) status; exit 0 ;;
  --rollback)
    [ -f "$PREV_FILE" ] || die "no previous install recorded at $PREV_FILE"
    PREV="$(cat "$PREV_FILE")"
    if [ ! -d "$PREV" ]; then
      # A moved or deleted install leaves the record lying. Say which, and list
      # what is actually installed so the next command is obvious.
      echo "❌ previous install is gone: $PREV" >&2
      echo "   installs found:" >&2
      ls -d /home/rodri/audio-v*/ 2>/dev/null | sed 's/^/     /' >&2
      ls -d "${DRIVE}"/audio-v*/ 2>/dev/null | sed 's/^/     /' >&2
      exit 1
    fi
    set -- "$PREV"
    ;;
esac

CANDIDATE="$(readlink -f "$1" 2>/dev/null || true)"
[ -n "$CANDIDATE" ] || die "no such install: $1"
[ "$CANDIDATE" != "$(readlink -f "$LINK" 2>/dev/null || true)" ] || { echo "already on $CANDIDATE"; status; exit 0; }

VERSION="$(validate "$CANDIDATE")" || exit 1
PREVIOUS="$(readlink -f "$LINK" 2>/dev/null || true)"

echo "candidate: $CANDIDATE"
echo "version  : $VERSION"
pin_config "$CANDIDATE"

if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$CANDIDATE" ]; then
  mkdir -p "$(dirname "$PREV_FILE")"
  echo "$PREVIOUS" > "$PREV_FILE"
fi

stop_server
ln -sfn "$CANDIDATE" "$LINK"
echo "link     : $LINK -> $CANDIDATE"

if start_server; then
  echo "server   : $(health)"
  echo "✅ switched. Roll back with: $(basename "${BASH_SOURCE[0]}") --rollback"
  exit 0
fi

echo "❌ new install did not answer on :$PORT — restoring previous" >&2
if [ -n "$PREVIOUS" ]; then
  ln -sfn "$PREVIOUS" "$LINK"
  stop_server
  if start_server; then
    echo "↩️  rolled back to $PREVIOUS — $(health)" >&2
  else
    echo "⚠️  rollback also failed to start; run the launcher by hand" >&2
  fi
fi
exit 1
