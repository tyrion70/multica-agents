#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ -f "${HOME}/.claude/secrets/bw-bootstrap.env" ]] && [[ -z "${BW_SESSION:-}" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "${HOME}/.claude/secrets/bw-bootstrap.env"
  set +a
  export NODE_TLS_REJECT_UNAUTHORIZED=0
  BW_SESSION="$(bw unlock --raw --passwordenv BW_PASSWORD 2>/dev/null)" || true
  if [[ -n "${BW_SESSION:-}" ]]; then
    export BW_SESSION
  fi
fi

exec python3 "$SCRIPT_DIR/sync.py" "$@"
