#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

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
fi

exit $rc
