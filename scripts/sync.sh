#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MULTICA="${MULTICA:-multica}"

echo "==> Syncing agents from $REPO_ROOT"

find "$REPO_ROOT" -name 'agent.json' -not -path '*/schemas/*' | while read -r agent_file; do
  rel="$(realpath --relative-to="$REPO_ROOT" "$agent_file")"
  workspace="$(echo "$rel" | cut -d/ -f1)"
  squad="$(echo "$rel" | cut -d/ -f2)"
  agent_slug="$(echo "$rel" | cut -d/ -f3)"

  echo "  -> $workspace / $squad / $agent_slug"

  name="$(jq -r '.name' "$agent_file")"
  instructions="$(jq -r '.instructions // ""' "$agent_file")"
  description="$(jq -r '.description // ""' "$agent_file")"
  runtime_id="$(jq -r '.runtime_id' "$agent_file")"
  model="$(jq -r '.model // ""' "$agent_file")"
  visibility="$(jq -r '.visibility // "private"' "$agent_file")"

  echo "     name=$name runtime=$runtime_id"
done

echo "==> Sync complete"
