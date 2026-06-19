#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MULTICA="${MULTICA:-multica}"

STDOUT=false
DRY_RUN=false
QUIET=false

usage() {
  cat <<'EOF'
Usage: dump-mcp-configs.sh [--stdout] [--dry-run] [--quiet]

Iterates all agents in the workspace, extracts mcp_config via the Multica API,
and writes each config to <agent-folder>/mcp-config.dump.json in the repo.

Options:
  --stdout    Write all configs to stdout (one JSON object per agent) instead of files
  --dry-run   Print what would be dumped without writing
  --quiet     Suppress progress output (errors and summary still printed)
  --help      Show this help message
EOF
}

for arg in "$@"; do
  case "$arg" in
    --stdout)  STDOUT=true ;;
    --dry-run) DRY_RUN=true ;;
    --quiet)   QUIET=true ;;
    --help)    usage; exit 0 ;;
    *)         echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

check_deps() {
  local missing=()
  for cmd in jq "$MULTICA"; do
    if ! command -v "$cmd" &>/dev/null; then
      missing+=("$cmd")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Missing required commands: ${missing[*]}" >&2
    exit 1
  fi
}

slugify() {
  local input
  if [[ $# -ge 1 ]]; then
    input="$1"
  else
    input="$(cat)"
  fi
  echo "$input" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/-\+/-/g' | sed 's/^-//;s/-$//'
}

check_deps

AGENT_COUNT=0
WRITTEN_COUNT=0
SKIPPED_COUNT=0
ERROR_COUNT=0
declare -a ERROR_MSGS=()

if ! $QUIET; then
  echo "==> Building workspace map"
fi
WORKSPACE_JSON="$("$MULTICA" workspace list --output json 2>/dev/null)" || {
  echo "ERROR: Failed to list workspaces" >&2
  exit 1
}
declare -A WORKSPACE_SLUG_MAP
while IFS=$'\t' read -r wid slug; do
  WORKSPACE_SLUG_MAP["$wid"]="$slug"
done < <(echo "$WORKSPACE_JSON" | jq -r '.[] | "\(.id)\t\(.slug)"')

if ! $QUIET; then
  echo "==> Building squad/agent map"
fi
declare -A AGENT_SQUAD_MAP
SQUAD_JSON="$("$MULTICA" squad list --output json 2>/dev/null)" || {
  echo "ERROR: Failed to list squads" >&2
  exit 1
}
SQUAD_IDS="$(echo "$SQUAD_JSON" | jq -r '.[].id')"
while IFS= read -r sid; do
  squad_slug="$(echo "$SQUAD_JSON" | jq -r --arg id "$sid" '.[] | select(.id == $id) | .name' | slugify)"
  MEMBERS_JSON="$("$MULTICA" squad member list "$sid" --output json 2>/dev/null)" || {
    ERROR_MSGS+=("Failed to list members for squad $sid")
    ((ERROR_COUNT++)) || true
    continue
  }
  while IFS=$'\t' read -r agent_id; do
    AGENT_SQUAD_MAP["$agent_id"]="$squad_slug"
  done < <(echo "$MEMBERS_JSON" | jq -r '.[].member_id')
done <<< "$SQUAD_IDS"

if ! $QUIET; then
  echo "==> Scanning repo for existing agent folders"
fi
declare -A REPO_AGENT_FOLDER_MAP
while IFS= read -r agent_file; do
  agent_name="$(jq -r '.name // ""' "$agent_file" 2>/dev/null)"
  if [[ -n "$agent_name" && "$agent_name" != "null" ]]; then
    rel="$(realpath --relative-to="$REPO_ROOT" "$agent_file")"
    agent_dir="$(dirname "$rel")"
    REPO_AGENT_FOLDER_MAP["$agent_name"]="$agent_dir"
  fi
done < <(find "$REPO_ROOT" -name 'agent.json' -not -path '*/schemas/*' 2>/dev/null || true)

if ! $QUIET; then
  echo "==> Fetching agents"
fi
AGENT_LIST_JSON="$("$MULTICA" agent list --output json 2>/dev/null)" || {
  echo "ERROR: Failed to list agents" >&2
  exit 1
}

AGENT_COUNT="$(echo "$AGENT_LIST_JSON" | jq '. | length')"

while IFS=$'\t' read -r agent_id agent_name agent_workspace_id; do
  agent_slug="$(slugify "$agent_name")"

  WORKSPACE_SLUG="${WORKSPACE_SLUG_MAP[$agent_workspace_id]:-}"
  if [[ -z "$WORKSPACE_SLUG" ]]; then
    if ! $QUIET; then
      echo "  [WARN] Unknown workspace $agent_workspace_id for agent $agent_name — skipping" >&2
    fi
    ((SKIPPED_COUNT++)) || true
    continue
  fi

  SQUAD_SLUG="${AGENT_SQUAD_MAP[$agent_id]:-_shared}"

  TARGET_DIR="${REPO_AGENT_FOLDER_MAP[$agent_name]:-}"
  if [[ -z "$TARGET_DIR" ]]; then
    TARGET_DIR="$WORKSPACE_SLUG/$SQUAD_SLUG/$agent_slug"
  fi

  AGENT_JSON="$("$MULTICA" agent get "$agent_id" --output json 2>/dev/null)" || {
    ERROR_MSGS+=("Failed to get agent $agent_name ($agent_id)")
    ((ERROR_COUNT++)) || true
    continue
  }

  MCP_CONFIG="$(echo "$AGENT_JSON" | jq -c '.mcp_config')"
  if [[ "$MCP_CONFIG" == "null" || -z "$MCP_CONFIG" ]]; then
    if ! $QUIET; then
      echo "  -> $agent_name: no mcp_config, skipping"
    fi
    ((SKIPPED_COUNT++)) || true
    continue
  fi

  if $DRY_RUN; then
    echo "  -> $agent_name → $TARGET_DIR/mcp-config.dump.json (dry-run)"
    ((WRITTEN_COUNT++)) || true
    continue
  fi

  if $STDOUT; then
    printf '{"agent_id":"%s","agent_name":"%s","workspace":"%s","squad":"%s","folder":"%s","mcp_config":%s}\n' \
      "$agent_id" "$agent_name" "$WORKSPACE_SLUG" "$SQUAD_SLUG" "$TARGET_DIR" "$MCP_CONFIG"
    ((WRITTEN_COUNT++)) || true
    continue
  fi

  ABS_DIR="$REPO_ROOT/$TARGET_DIR"
  mkdir -p "$ABS_DIR"
  echo "$MCP_CONFIG" | jq '.' > "$ABS_DIR/mcp-config.dump.json"
  if ! $QUIET; then
    echo "  -> $agent_name → $TARGET_DIR/mcp-config.dump.json"
  fi
  ((WRITTEN_COUNT++)) || true

done < <(echo "$AGENT_LIST_JSON" | jq -r '.[] | "\(.id)\t\(.name)\t\(.workspace_id)"')

SUMMARY_FILE="$(mktemp)"
cat > "$SUMMARY_FILE" <<SUMMARY_EOF
==> Done
  Agents found:   $AGENT_COUNT
  Configs dumped: $WRITTEN_COUNT
  Skipped:        $SKIPPED_COUNT
  Errors:         $ERROR_COUNT
SUMMARY_EOF

if [[ ${#ERROR_MSGS[@]} -gt 0 ]]; then
  {
    echo "  Error details:"
    for msg in "${ERROR_MSGS[@]}"; do
      echo "    - $msg"
    done
  } >> "$SUMMARY_FILE"
fi

if $DRY_RUN; then
  echo "  (dry-run — no files written)" >> "$SUMMARY_FILE"
fi

cat "$SUMMARY_FILE"
rm -f "$SUMMARY_FILE"
