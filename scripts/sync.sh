#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_FILE="${MCP_SECRETS_ENV:-/etc/multica/mcp-secrets.env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

python3 "$SCRIPT_DIR/sync.py" "$@"
rc=$?

if [ $rc -eq 0 ]; then
  workspace=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --workspace) workspace="$2"; shift 2 ;;
      --workspace=*) workspace="${1#*=}"; shift ;;
      *) shift ;;
    esac
  done

  if [ -n "$workspace" ]; then
    case "$workspace" in
      Chainlayer) md="claude-config/chainlayer/CLAUDE.md" ;;
      Private)    md="claude-config/private/CLAUDE.md" ;;
      *)          md="" ;;
    esac
    if [ -n "$md" ] && [ -f "$REPO_ROOT/$md" ]; then
      mkdir -p "$HOME/.claude"
      ln -sf "$REPO_ROOT/$md" "$HOME/.claude/CLAUDE.md"
      echo "  → symlinked ~/.claude/CLAUDE.md → $REPO_ROOT/$md"
    fi
  fi
fi

exit $rc
