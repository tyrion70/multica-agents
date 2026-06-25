#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Drop injected env vars so multica CLI calls fall back to the host's local
# config (~/.multica/config.json) and its user login.  Agent/autopilot tasks
# inherit MULTICA_TOKEN, MULTICA_WORKSPACE_ID etc from the runtime — these
# override the local config and scope the CLI to the task's workspace, which
# may not be the one the operator intended (e.g. a Chainlayer-dispatched
# task trying to sync the Private workspace).
# 
# Unsetting them means every `multica` call in this script uses the host's
# local login (peter@tyrion.nl) and whatever workspace is active in
# config.json.  sync.sh is always executed, never sourced, so the parent
# process keeps its original env.
for var in MULTICA_AGENT_ID MULTICA_AGENT_NAME MULTICA_DAEMON_PORT \
           MULTICA_SERVER_URL MULTICA_TASK_ID MULTICA_TASK_SLOT \
           MULTICA_TOKEN MULTICA_WORKSPACE_ID; do
  unset "$var"
done

# Resolve MCP secrets from Bitwarden (runs under the host local login
# after the unset above, so bw unlock authenticates as peter@tyrion.nl).
BOOTSTRAP="${BW_BOOTSTRAP:-$HOME/.claude/secrets/bw-bootstrap.env}"
if [ -f "$BOOTSTRAP" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$BOOTSTRAP"
  set +a
  export NODE_TLS_REJECT_UNAUTHORIZED=0
  if BW_SESSION="$(bw unlock --passwordenv BW_PASSWORD --raw 2>/dev/null)"; then
    export BW_SESSION
  else
    echo "  WARNING: bw unlock failed — mcp placeholders will not be resolved" >&2
  fi
fi

# Parse --workspace without consuming positional args (sync.py needs them all).
workspace=""
prev=""
for arg in "$@"; do
  case "$arg" in
    --workspace=*) workspace="${arg#*=}" ;;
    *) if [ "$prev" = "--workspace" ]; then workspace="$arg"; fi ;;
  esac
  prev="$arg"
done

# Pre-flight guard: verify the host's active workspace matches --workspace.
# After the unset above, multica workspace get reflects the local config.
if [ -n "$workspace" ]; then
  active="$(multica workspace get --output json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('name',''))" 2>/dev/null || true)"
  if [ -n "$active" ] && [ "$active" != "$workspace" ]; then
    echo "ERROR: --workspace is '$workspace' but the host's active workspace is '$active'." >&2
    echo "       Run 'multica workspace switch $workspace' first, or set your" >&2
    echo "       MULTICA_WORKSPACE_ID (not recommended — the unset block drops it)." >&2
    exit 1
  fi
fi

python3 "$SCRIPT_DIR/sync.py" "$@"
rc=$?

if [ $rc -eq 0 ] && [ -n "$workspace" ]; then
    case "$workspace" in
      Chainlayer) md="claude-config/chainlayer/CLAUDE.md" ;;
      Private)    md="claude-config/private/CLAUDE.md" ;;
      *)          md="" ;;
    esac
    if [ -n "$md" ] && [ -f "$REPO_ROOT/$md" ]; then
      mkdir -p "$HOME/.claude"
      # Copy, don't symlink: the repo checkout lives in an ephemeral Multica
      # workdir, so a symlink into it dangles once that workdir is reaped.
      # rm -f first so we replace any pre-existing symlink (from older runs)
      # with a regular file — otherwise cp would follow it and write through to
      # the symlink's (now-stale) target instead. Last sync wins.
      rm -f "$HOME/.claude/CLAUDE.md"
      cp "$REPO_ROOT/$md" "$HOME/.claude/CLAUDE.md"
      echo "  → copied ~/.claude/CLAUDE.md ← $REPO_ROOT/$md"
    fi
fi

exit $rc
