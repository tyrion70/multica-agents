#!/usr/bin/env bash
# Print the Home Assistant long-lived access token from the Bitwarden vault.
#
# Unlocking is NOT done here — do it per the `bitwarden` skill first:
#   set -a; . ~/.claude/secrets/bw-bootstrap.env; set +a
#   export NODE_TLS_REJECT_UNAUTHORIZED=0
#   export BW_SESSION=$(bw unlock --raw --passwordenv BW_PASSWORD)
#
# Usage:  TOKEN="$(~/.claude/skills/homeassistant/scripts/ha-token.sh)"
set -euo pipefail

ITEM="${HA_BW_ITEM:-Home Assistant — 252h.org (API + SSH)}"
: "${BW_SESSION:?Bitwarden vault not unlocked — unlock per the bitwarden skill (set BW_SESSION) first}"

bw get item "$ITEM" --session "$BW_SESSION" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print({f['name']:f['value'] for f in d.get('fields',[])}['HA_TOKEN'])"
