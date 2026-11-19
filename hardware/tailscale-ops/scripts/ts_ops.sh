#!/usr/bin/env bash
# ts_ops.sh — Runtime Tailscale Network Operations for AI Agents

set -euo pipefail

# Typed contract: one MCP JSON Schema for the command surface. Zero side effects.
if [ "${1:-}" = "--omni-schema" ]; then
  python3 - <<'PY'
import json
print(json.dumps({
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ts_ops",
  "description": "Runtime Tailscale Network Operations for AI Agents",
  "type": "object",
  "properties": {
    "command": {"type": "string", "enum": ["peers", "check-port", "sync", "status", "reset-tunnels", "send-file", "doctor"], "x-positional": 0},
    "host": {"type": "string", "x-positional": 1},
    "port": {"type": "integer", "x-positional": 2},
    "file": {"type": "string", "x-positional": 1},
    "target": {"type": "string", "x-positional": 2},
    "dry-run": {"type": "boolean", "x-flag": "--dry-run"},
    "json": {"type": "boolean", "x-flag": "--json"},
    "help": {"type": "boolean", "x-flag": "--help"}
  },
  "additionalProperties": False
}, indent=2))
PY
  exit 0
fi

CMD="${1:-peers}"
shift || true

# Optional contract flags: --dry-run prints the planned action and exits before
# any tailnet mutation; --json emits that plan as JSON.
DRY_RUN=0
AS_JSON=0
_POSITIONAL=()
for _arg in "$@"; do
  case "$_arg" in
    --dry-run) DRY_RUN=1 ;;
    --json) AS_JSON=1 ;;
    *) _POSITIONAL+=("$_arg") ;;
  esac
done
set -- "${_POSITIONAL[@]+"${_POSITIONAL[@]}"}"

emit_plan() {
  local label="$1" commands="$2"
  if [ "$AS_JSON" = 1 ]; then
    python3 -c 'import json,sys; print(json.dumps({"action":sys.argv[1],"dry_run":True,"commands":sys.argv[2].split("|")},indent=2))' "$label" "$commands"
  else
    echo "[dry-run] would execute: $commands"
  fi
}

# Helper: Check if tailscale CLI is available
check_tailscale() {
  if ! command -v tailscale >/dev/null 2>&1; then
    echo "❌ Error: tailscale CLI not found in PATH." >&2
    echo "   Ensure Tailscale is installed and running." >&2
    exit 1
  fi
}

usage() {
  echo "Usage: $0 {peers|check-port|sync|status|reset-tunnels|send-file|doctor}"
  echo "  peers                  # List online tailnet peers"
  echo "  doctor                 # Diagnostic check of tailscale status and active tunnels"
  echo "  check-port <host> <p>  # Probe reachable port on peer"
  echo "  sync                   # Reconcile the tailnet surface to ports.json"
  echo "  status                 # Show the declared surface and live serve state"
  echo "  reset-tunnels          # Tear down all serve and funnel tunnels"
  echo "  send-file <file> <tgt> # Transfer file to peer via tailscale file cp"
}

# --------------------------------------------------------------------------- #
# The declared tailnet surface, rendered from ports.json by
# `ports.py render --write`. What may leave this machine is decided by the
# manifest, not by this script: `sync` applies exactly this block and turns
# off every other serve frontend it finds.
# --------------------------------------------------------------------------- #
# ports:begin
TS_ROOT=3773
TS_PATHS=("/chat:7778" "/omni:8790")
SERVED=(
  "3010:kasmvnc — KasmVNC (podman)"
  "9222:cdp — Chromium DevTools"
)
# ports:end

case "$CMD" in
  peers)
    check_tailscale
    tailscale status --json | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    peers = []
    # Include self
    self_node = data.get("Self", {})
    if self_node:
        peers.append({
            "hostname": self_node.get("HostName"),
            "dns_name": self_node.get("DNSName", "").rstrip("."),
            "tailscale_ip": (self_node.get("TailscaleIPs") or [""])[0],
            "os": self_node.get("OS"),
            "online": True,
            "self": True
        })
    # Include other peers
    for p in (data.get("Peer") or {}).values():
        if p.get("Online", False):
            peers.append({
                "hostname": p.get("HostName"),
                "dns_name": p.get("DNSName", "").rstrip("."),
                "tailscale_ip": (p.get("TailscaleIPs") or [""])[0],
                "os": p.get("OS"),
                "online": True,
                "self": False
            })
    print(json.dumps(peers, indent=2))
except Exception as e:
    sys.stderr.write(f"Error parsing tailscale status: {e}\n")
    sys.exit(1)
'
    ;;

  check-port)
    HOST="${1:?Target hostname or Tailscale IP required}"
    PORT="${2:?Target port required}"
    
    python3 -c "
import socket, sys
host = sys.argv[1]
port = int(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2.5)
try:
    s.connect((host, port))
    s.close()
    print(f'✅ ONLINE: {host}:{port} is reachable.')
    sys.exit(0)
except Exception as e:
    print(f'❌ OFFLINE: {host}:{port} is unreachable ({e}).')
    sys.exit(1)
" "$HOST" "$PORT"
    ;;

  reset-tunnels)
    if [ "$DRY_RUN" = 1 ]; then
      emit_plan "reset-tunnels" "tailscale serve reset|tailscale funnel reset"
      exit 0
    fi
    check_tailscale
    echo "🧹 Resetting all active Tailscale serve and funnel tunnels..."
    tailscale serve reset 2>/dev/null || true
    tailscale funnel reset 2>/dev/null || true
    echo "✅ All Tailscale serve and funnel configurations cleared."
    ;;

  sync)
    if [ "$DRY_RUN" = 1 ]; then
      _PLAN="tailscale serve reset|tailscale funnel reset"
      if [ -n "${TS_ROOT:-}" ]; then
        _PLAN="${_PLAN}|tailscale serve --bg --https=443 http://127.0.0.1:${TS_ROOT}"
      fi
      for _item in ${TS_PATHS[@]+"${TS_PATHS[@]}"}; do
        _PLAN="${_PLAN}|tailscale serve --bg --https=443 --set-path=${_item%%:*} http://127.0.0.1:${_item##*:}"
      done
      emit_plan "sync" "$_PLAN"
      exit 0
    fi
    check_tailscale
    DNS_NAME=$(tailscale status --json | python3 -c 'import json, sys; print(json.load(sys.stdin).get("Self", {}).get("DNSName", "").rstrip("."))')
    echo "🔁 Reconciling the tailnet surface to ports.json (${DNS_NAME})..."

    DECLARED=()
    if [ -n "${TS_ROOT:-}" ]; then
      tailscale serve --bg --https=443 "http://127.0.0.1:${TS_ROOT}" >/dev/null
      echo "  • /       -> :${TS_ROOT}"
      DECLARED+=("443:/")
    fi
    for item in ${TS_PATHS[@]+"${TS_PATHS[@]}"}; do
      P="${item%%:*}"
      PORT="${item##*:}"
      tailscale serve --bg --https=443 --set-path="$P" "http://127.0.0.1:${PORT}" >/dev/null
      echo "  • ${P} -> :${PORT}"
      DECLARED+=("443:${P}")
    done

    for item in ${SERVED[@]+"${SERVED[@]}"}; do
      PORT="${item%%:*}"
      NAME="${item#*:}"
      DECLARED+=("${PORT}:/")
      tailscale serve --bg --https="$PORT" "http://127.0.0.1:${PORT}" >/dev/null
      echo "  • :${PORT} -> ${NAME}"
    done

    # Reconcile, don't pile on: every handler the manifest does not name is
    # turned off. A hand-run `tailscale serve` survives only until this runs.
    EXTRA=$(tailscale serve status --json | python3 -c '
import json, sys
cfg = json.load(sys.stdin)
want = set(sys.argv[1:])
for key, web in (cfg.get("Web") or {}).items():
    front = str(key).rsplit(":", 1)[-1]
    for path in (web.get("Handlers") or {}):
        token = f"{front}:{path}"
        if token not in want:
            print(token)
declared_fronts = {t.split(":", 1)[0] for t in want}
for key in (cfg.get("TCP") or {}):
    front = str(key).rsplit(":", 1)[-1]
    if front not in declared_fronts:
        print(f"{front}:")
' "${DECLARED[@]}")
    while IFS=: read -r FRONT PATH_PART; do
      [ -z "$FRONT" ] && continue
      if [ -n "$PATH_PART" ]; then
        echo "  ✕ :${FRONT}${PATH_PART} (not in ports.json)"
        tailscale serve --https="$FRONT" --set-path="$PATH_PART" off >/dev/null 2>&1 || true
      else
        echo "  ✕ :${FRONT} (not in ports.json)"
        tailscale serve --https="$FRONT" off >/dev/null 2>&1 \
          || tailscale serve --tcp="$FRONT" off >/dev/null 2>&1 \
          || true
      fi
    done <<< "$EXTRA"

    echo ""
    echo "✅ Tailnet surface in sync:"
    tailscale serve status
    ;;

  status)
    check_tailscale
    DNS_NAME=$(tailscale status --json | python3 -c 'import json, sys; print(json.load(sys.stdin).get("Self", {}).get("DNSName", "").rstrip("."))')
    echo "📊 Declared tailnet surface (${DNS_NAME}):"
    if [ -n "${TS_ROOT:-}" ]; then
      printf "  %-8s %s\n" "/" "https://${DNS_NAME}/ -> :${TS_ROOT}"
    fi
    for item in ${TS_PATHS[@]+"${TS_PATHS[@]}"}; do
      P="${item%%:*}"
      PORT="${item##*:}"
      printf "  %-8s %s\n" "$P" "https://${DNS_NAME}${P} -> :${PORT}"
    done
    for item in ${SERVED[@]+"${SERVED[@]}"}; do
      PORT="${item%%:*}"
      NAME="${item#*:}"
      printf "  %-8s %s\n" ":${PORT}" "https://${DNS_NAME}:${PORT} -> :${PORT} (${NAME})"
    done
    echo ""
    echo "  Live serve state:"
    tailscale serve status 2>/dev/null || echo "    none"
    ;;

  doctor)
    check_tailscale
    echo "🩺 [tailscale-ops] Diagnostic Health Check:"
    python3 -c '
import json, subprocess, sys
try:
    res = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, check=True)
    data = json.loads(res.stdout)
    self_node = data.get("Self", {})
    hostname = self_node.get("HostName", "unknown")
    dns = self_node.get("DNSName", "").rstrip(".")
    ip = (self_node.get("TailscaleIPs") or ["unknown"])[0]
    backend = data.get("BackendState", "unknown")
    print(f"  • Backend State:    {backend}")
    print(f"  • Self Hostname:    {hostname}")
    print(f"  • Tailscale IP:     {ip}")
    print(f"  • Tailnet DNS:      {dns}")

    peers = data.get("Peer") or {}
    online_peers = [p for p in peers.values() if p.get("Online", False)]
    print(f"  • Online Peers:     {len(online_peers)} detected")
    for p in online_peers:
        p_name = p.get("HostName")
        p_ip = (p.get("TailscaleIPs") or [""])[0]
        p_os = p.get("OS")
        print(f"    - {p_name} ({p_os}) @ {p_ip}")
except Exception as e:
    print(f"  ❌ Error querying tailscale status: {e}")
'
    echo ""
    echo "  • Active Serve Tunnels:"
    tailscale serve status 2>/dev/null || echo "    None active."
    ;;

  send-file)
    check_tailscale
    FILE_PATH="${1:?File path required}"
    TARGET="${2:?Target node required (e.g. gaming-pc:)}"
    [[ "$TARGET" != *: ]] && TARGET="${TARGET}:"
    tailscale file cp "$FILE_PATH" "$TARGET"
    echo "✅ Sent ${FILE_PATH} to ${TARGET}"
    ;;

  -h|--help|help)
    usage
    exit 0
    ;;

  *)
    usage >&2
    exit 1
    ;;
esac
