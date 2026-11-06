#!/usr/bin/env bash
# subagent_ctl.sh — Dispatch, monitor, and inspect GitHub Actions cloud subagents

set -euo pipefail

usage() {
  echo "Usage: $0 {dispatch|status|logs|help} [options]"
  echo "  dispatch --task <string> [--branch <string>] [--model <string>]"
  echo "  status"
  echo "  logs <run_id>"
}

ACTION="${1:-status}"
shift || true

# Help must not require a token or a repository: answer it before any of that.
case "$ACTION" in
  -h|--help|help) usage; exit 0 ;;
esac

# 1. Resolve Auth Token (environment variable or gh CLI)
TOKEN="${GITHUB_TOKEN:-}"
if [[ -z "$TOKEN" ]]; then
  if command -v gh >/dev/null 2>&1; then
    TOKEN=$(gh auth token 2>/dev/null || true)
  fi
fi

if [[ -z "$TOKEN" ]]; then
  echo "❌ Error: Neither GITHUB_TOKEN is set nor 'gh' CLI authenticated." >&2
  echo "   Please run: gh auth login or export GITHUB_TOKEN" >&2
  exit 1
fi

# 2. Resolve Repository (owner/repo)
REPO="${GITHUB_REPO:-}"
if [[ -z "$REPO" ]]; then
  if command -v gh >/dev/null 2>&1; then
    REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)
  fi
fi

if [[ -z "$REPO" ]]; then
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    ORIGIN_URL=$(git remote get-url origin 2>/dev/null || true)
    REPO=$(echo "$ORIGIN_URL" | sed -E 's#.*github\.com[:/]([^/]+/[^/.]+)(\.git)?#\1#' | sed 's/\.git$//')
  fi
fi

if [[ -z "$REPO" ]]; then
  echo "❌ Error: Could not detect GitHub repository. Set GITHUB_REPO=owner/repo" >&2
  exit 1
fi

WORKFLOW_FILE="subagent.yml"

case "$ACTION" in
  dispatch)
    TASK=""
    BRANCH="agent/task-$(date +%s)"
    MODEL="openrouter/free"

    while [[ $# -gt 0 ]]; do
      case "$1" in
        --task) TASK="$2"; shift 2 ;;
        --branch) BRANCH="$2"; shift 2 ;;
        --model) MODEL="$2"; shift 2 ;;
        *) shift ;;
      esac
    done

    if [[ -z "$TASK" ]]; then
      echo "❌ Error: --task argument is required." >&2
      exit 1
    fi

    echo "🚀 Dispatching subagent on repo '$REPO'..."
    echo "   • Branch: $BRANCH"
    echo "   • Model:  $MODEL"
    echo "   • Task:   $TASK"

    PAYLOAD=$(python3 -c "
import json, sys
data = {
    'ref': 'main',
    'inputs': {
        'task': sys.argv[1],
        'target_branch': sys.argv[2],
        'model': sys.argv[3]
    }
}
print(json.dumps(data))
" "$TASK" "$BRANCH" "$MODEL")

    HTTP_CODE=$(curl -sS -o /dev/null -w "%{http_code}" -X POST \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches" \
      -d "$PAYLOAD")

    if [[ "$HTTP_CODE" == "204" ]]; then
      echo "✅ Successfully dispatched cloud subagent!"
      echo "   Run '$0 status' to monitor workflow progress."
    else
      echo "❌ Dispatch failed with HTTP status: $HTTP_CODE" >&2
      exit 1
    fi
    ;;

  status)
    echo "📊 Recent subagent runs for $REPO:"
    RESPONSE=$(curl -sS \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW_FILE}/runs?per_page=5")

    python3 -c "
import json, sys
data = json.loads(sys.argv[1])
runs = data.get('workflow_runs', [])
if not runs:
    print('  (No workflow runs found)')
for r in runs:
    run_id = r.get('id')
    status = r.get('status')
    concl = r.get('conclusion') or 'in-progress'
    created = r.get('created_at', '')[:19]
    html_url = r.get('html_url')
    print(f'  • ID: {run_id} | Status: {status} ({concl}) | Started: {created}')
    print(f'    URL: {html_url}')
" "$RESPONSE"
    ;;

  logs)
    RUN_ID="${1:-}"
    if [[ -z "$RUN_ID" ]]; then
      echo "❌ Error: Run ID required. Usage: $0 logs <run_id>" >&2
      exit 1
    fi
    if command -v gh >/dev/null 2>&1; then
      gh run view "$RUN_ID" --repo "$REPO" --log
    else
      echo "View logs directly at: https://github.com/${REPO}/actions/runs/${RUN_ID}"
    fi
    ;;

  *)
    usage >&2
    exit 1
    ;;
esac
