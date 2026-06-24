#!/usr/bin/env bash
set -euo pipefail

# Google Drive MCP — one-time OAuth setup
# Run once on each runtime after the agent config has been synced.
#
# Usage:
#   scripts/setup-gdrive.sh              # prompts for workspace
#   scripts/setup-gdrive.sh chainlayer   # explicit (multica-02)
#   scripts/setup-gdrive.sh private      # explicit (multica-01)

CONFIG_DIR="${HOME}/.config/google-drive-mcp"
OAUTH_KEYS="${CONFIG_DIR}/gcp-oauth.keys.json"
TOKEN_PATH="${CONFIG_DIR}/tokens.json"

# --- helpers -----------------------------------------------------------
die() { echo >&2 "error: $*"; exit 1; }
info() { echo "==> $*"; }

unlock_bw() {
  if ! bw status --session "${BW_SESSION:-}" 2>/dev/null \
    | python3 -c "import json,sys; exit(0 if json.load(sys.stdin)['status']=='unlocked' else 1)"; then
    set -a; . ~/.claude/secrets/bw-bootstrap.env; set +a
    export NODE_TLS_REJECT_UNAUTHORIZED=0
    BW_SESSION=$(bw unlock --raw --passwordenv BW_PASSWORD 2>/dev/null)
    export BW_SESSION
  fi
}

# --- main --------------------------------------------------------------
info "Google Drive MCP — one-time setup"

case "${1:-}" in
  chainlayer|Chainlayer) WS="chainlayer" ;;
  private|Private)       WS="private" ;;
  "")
    echo "Which workspace are you setting up?"
    echo "  1) chainlayer (multica-02)"
    echo "  2) private   (multica-01)"
    read -rp "Choice [1/2]: " choice
    case "$choice" in 1) WS="chainlayer" ;; 2) WS="private" ;; *) die "invalid choice" ;; esac
    ;;
  *) die "usage: $0 [chainlayer|private]" ;;
esac

info "Target workspace: ${WS}"
mkdir -p "$CONFIG_DIR"

# Pick the right OAuth client credentials from Bitwarden
case "$WS" in
  chainlayer)
    BW_ITEM="mailtriage — Google OAuth client (chainlayer / peter@chainlayer.io)"
    ;;
  private)
    BW_ITEM="mailtriage — Google OAuth client (tyrion / pvmourik@tyrion.eu)"
    ;;
esac

# Fetch OAuth client credentials from Bitwarden
info "Fetching Google OAuth client credentials from Bitwarden …"
unlock_bw

bw get item "$BW_ITEM" --session "$BW_SESSION" \
  | python3 -c "
import json,sys
d = json.load(sys.stdin)
fields = {f['name']: f['value'] for f in d.get('fields', [])}
raw = fields.get('RAW_JSON', '{}')
parsed = json.loads(raw)
print(json.dumps(parsed, indent=2))
" > "$OAUTH_KEYS"

echo "  wrote ${OAUTH_KEYS}"

# Run OAuth flow
info "Starting OAuth authentication flow …"
echo ""
echo "  Your browser will open (or you'll get a URL to visit)."
echo "  Authenticate with a Google account that can access the"
echo "  Drive files you want agents to reach."
echo ""

export GOOGLE_DRIVE_OAUTH_CREDENTIALS="$OAUTH_KEYS"
export GOOGLE_DRIVE_MCP_TOKEN_PATH="$TOKEN_PATH"

npx @piotr-agier/google-drive-mcp auth

# Verify
echo ""
if [ -f "$TOKEN_PATH" ]; then
  info "Authentication successful! Tokens saved to ${TOKEN_PATH}"
  echo ""
  echo "Google Drive MCP is now ready. After the next agent sync,"
  echo "all agents on this runtime will have gdrive tools available."
else
  die "authentication failed — token file not found at ${TOKEN_PATH}"
fi
