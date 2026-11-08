#!/usr/bin/env bash
# ts_ops.sh — Runtime Tailscale Network Operations for AI Agents

set -euo pipefail

CMD="${1:-peers}"
shift || true

# Helper: Check if tailscale CLI is available
check_tailscale() {
  if ! command -v tailscale >/dev/null 2>&1; then
    echo "❌ Error: tailscale CLI not found in PATH." >&2
    echo "   Ensure Tailscale is installed and running." >&2
    exit 1
  fi
}

usage() {
  echo "Usage: $0 {peers|check-port|serve-mesh|mesh-status|serve-on|funnel-on|reset-tunnels|send-file|doctor}"
  echo "  peers                  # List online tailnet peers"
  echo "  doctor                 # Diagnostic check of tailscale status and active tunnels"
  echo "  check-port <host> <p>  # Probe reachable port on peer"
  echo "  serve-mesh             # Expose every inference and CDP slot over Tailscale HTTPS"
  echo "  mesh-status            # View active Tailscale serve configurations"
  echo "  serve-on <port>        # Expose single port privately on tailnet"
  echo "  funnel-on <port>       # Expose single port publicly via funnel"
  echo "  reset-tunnels          # Tear down all serve and funnel tunnels"
  echo "  send-file <file> <tgt> # Transfer file to peer via tailscale file cp"
}

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

  serve-on)
    check_tailscale
    PORT="${1:?Local port required}"
    echo "🔒 Exposing localhost:$PORT over private Tailscale HTTPS..."
    tailscale serve --bg "$PORT"
    tailscale serve status
    ;;

  funnel-on)
    check_tailscale
    PORT="${1:?Local port required}"
    echo "🌐 Opening public Tailscale Funnel on port 443 -> localhost:$PORT..."
    tailscale funnel --bg --https=443 "http://127.0.0.1:${PORT}"
    tailscale funnel status
    ;;

  reset-tunnels)
    check_tailscale
    echo "🧹 Resetting all active Tailscale serve and funnel tunnels..."
    tailscale serve reset 2>/dev/null || true
    tailscale funnel reset 2>/dev/null || true
    echo "✅ All Tailscale serve and funnel configurations cleared."
    ;;

  serve-mesh)
    check_tailscale
    DNS_NAME=$(tailscale status --json | python3 -c 'import json, sys; print(json.load(sys.stdin).get("Self", {}).get("DNSName", "").rstrip("."))')
    echo "⚡ Exposing Workstation AI Inference Matrix over Private Tailscale HTTPS (${DNS_NAME})..."
    
# ports:begin
SERVICES=(
  "8080:llm — Qwen3.6-35B-A3B-Uncensored-Genesis-Hermes-MTP"
  "8081:audio — nemotron-asr"
  "8083:decision — h2o-lightning-4b"
  "8082:decision-engine — StartLux-Decision-v1.1-4B-Instant"
  "8089:decision-fallback — Imajev-4B"
  "8084:ocr-crispembed — CrispEmbed (PP-OCRv6 small: DB++ det + CTC rec)"
  "8085:ocr-lighton — LightOnOCR-3-0.8B"
  "8086:reranker — jina-reranker-v2-base-multilingual"
  "8087:embed — bge-small-en-v1.5"
  "8088:grounding — WeVisOne-VL-4B"
  "8090:ocr-jev — MiniCPM-OCR-Jev"
  "8091:llm-rp — LFM3-1.7B-Uncensored-AD"
  "8000:llama-swap — llama-swap"
  "3010:kasmvnc — KasmVNC (podman)"
  "9222:cdp — Chromium DevTools"
  "9224:cdp-desktop — Chromium DevTools (headed agent profile)"
  "9223:cdp-internal — labwc forwarder"
  "8761:clip-box — h2o-lightning shim"
  "8621:clip-box-backend — llama-server (private backend)"
)
# ports:end

    for item in "${SERVICES[@]}"; do
      PORT="${item%%:*}"
      NAME="${item##*:}"
      # Never advertise a port with nothing behind it: the tailscale listener
      # outlives the service, so a dead port looks healthy from the tailnet.
      if ! ss -ltn 2>/dev/null | grep -q ":$PORT "; then
        echo "  ○ Skipping $NAME on :$PORT (nothing listening locally)"
        continue
      fi
      echo "  • Serving $NAME on :$PORT..."
      tailscale serve --bg --https "$PORT" "http://127.0.0.1:$PORT" >/dev/null 2>&1 || true
    done

    echo ""
    echo "✅ Workstation Inference Mesh Online across Tailnet:"
    printf "  %-38s %s\n" "SERVICE" "TAILSCALE HTTPS URL"
    echo "  ────────────────────────────────────────────────────────────────────────────────"
    for item in "${SERVICES[@]}"; do
      PORT="${item%%:*}"
      NAME="${item##*:}"
      printf "  %-38s https://%s:%s\n" "$NAME" "$DNS_NAME" "$PORT"
    done
    ;;

  mesh-status)
    check_tailscale
    DNS_NAME=$(tailscale status --json | python3 -c 'import json, sys; print(json.load(sys.stdin).get("Self", {}).get("DNSName", "").rstrip("."))')
    echo "📊 Workstation Tailscale Mesh Status (${DNS_NAME}):"
    tailscale serve status
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
