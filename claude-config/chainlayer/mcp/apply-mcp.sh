#!/usr/bin/env bash
# Apply the ChainLayer company MCP servers to a Multica agent's mcp_config.
#
# Why per-agent: the Multica daemon runs agents with --strict-mcp-config, so an
# agent's only MCP comes from its own mcp_config. Re-run anytime — idempotent,
# it rebuilds and replaces the whole config.
#
# Prereqs:
#   - `multica` CLI authed as the workspace owner on this host
#   - Bitwarden unlocked: $BW_SESSION set (see the `bitwarden` skill)
#   - node/npx on the host (for the Slack stdio server)
# Secrets pulled from the Bitwarden *company* folder: linear, incident.io,
#   jira key, slack bot. Nothing is hardcoded.
#
# Usage: ./apply-mcp.sh <agent-id> [atlassian-email]
set -euo pipefail

AGENT_ID="${1:?usage: apply-mcp.sh <agent-id> [atlassian-email]}"
ATLASSIAN_EMAIL="${2:-peter@chainlayer.io}"
SLACK_TEAM_ID="${SLACK_TEAM_ID:-TL8TVRYF8}"
: "${BW_SESSION:?unlock Bitwarden first and export BW_SESSION (see the bitwarden skill)}"

note() { bw get item "$1" --session "$BW_SESSION" \
  | python3 -c 'import json,sys;print((json.load(sys.stdin).get("notes") or "").strip())'; }

LINEAR_KEY="$(note linear)"
INCIDENT_KEY="$(note "incident.io")"
JIRA_KEY="$(note "jira key")"
SLACK_XOXB="$(note "slack bot")"
for v in LINEAR_KEY INCIDENT_KEY JIRA_KEY SLACK_XOXB; do
  [ -n "${!v}" ] || { echo "ERROR: empty secret $v (check the Bitwarden company folder)" >&2; exit 1; }
done
ATLAS_BASIC="Basic $(printf '%s' "${ATLASSIAN_EMAIL}:${JIRA_KEY}" | base64 | tr -d '\n')"

MCP_JSON="$(python3 - "$LINEAR_KEY" "$INCIDENT_KEY" "$ATLAS_BASIC" "$SLACK_XOXB" "$SLACK_TEAM_ID" <<'PY'
import json,sys
lin,inc,atl,xoxb,team=sys.argv[1:6]
print(json.dumps({"mcpServers":{
 "linear":{"type":"http","url":"https://mcp.linear.app/mcp","headers":{"Authorization":f"Bearer {lin}"}},
 "incidentio":{"type":"http","url":"https://mcp.incident.io/mcp","headers":{"Authorization":f"Bearer {inc}"}},
 "atlassian":{"type":"http","url":"https://mcp.atlassian.com/v1/mcp","headers":{"Authorization":atl}},
 "slack":{"command":"npx","args":["-y","@modelcontextprotocol/server-slack"],
          "env":{"SLACK_BOT_TOKEN":xoxb,"SLACK_TEAM_ID":team}}
}}))
PY
)"

printf '%s' "$MCP_JSON" | multica agent update "$AGENT_ID" --mcp-config-stdin --output json >/dev/null
echo "Applied company MCP config to agent ${AGENT_ID}: linear, incidentio, atlassian, slack."
echo "Verify on the host: a fresh task on that agent should expose mcp__linear__*, mcp__incidentio__*, mcp__atlassian__*, mcp__slack__* tools."
