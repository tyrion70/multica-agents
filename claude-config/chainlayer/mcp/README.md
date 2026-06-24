# Company MCP servers for agents

How the ChainLayer (company) agents get their MCP tools. Lives under `chainlayer/`
because these connectors are **company-only** — the `private/` profile does not get
them (mirror the privacy split). Origin: TRE-66.

## The one thing to know

MCP is **per-agent, not per-workspace**. The Multica daemon launches every agent's
Claude with `--strict-mcp-config`, so agents ignore *all* ambient/account/claude.ai
MCP. The only MCP an agent sees is its own `mcp_config` field. There is nothing to
configure once at the workspace or host level — you set `mcp_config` on each agent
that should have the tools.

So: on a company host (e.g. `multica-02`), pick the **dedicated company agent** and
apply the config to it. Don't spray it across every agent.

## Connectors (all verified working headless)

| Connector | Transport | Auth |
|---|---|---|
| Linear | http `https://mcp.linear.app/mcp` | `Authorization: Bearer <key>` |
| incident.io | http `https://mcp.incident.io/mcp` | `Authorization: Bearer <key>` |
| Atlassian | http `https://mcp.atlassian.com/v1/mcp` | `Authorization: Basic base64(email:token)` — Teamwork Graph toolset |
| Slack | stdio `npx @modelcontextprotocol/server-slack` | env `SLACK_BOT_TOKEN=<xoxb>`, `SLACK_TEAM_ID` |

Secrets come from the Bitwarden **company** folder (never hardcode):
`linear`, `incident.io`, `jira key`, `slack bot`. Host also needs `node`/`npx`
(for the Slack stdio server) and outbound HTTPS.

## Apply

```bash
# 1. unlock Bitwarden (see the `bitwarden` skill) so $BW_SESSION is set, e.g.:
#    set -a; . ~/.claude/secrets/bw-bootstrap.env; set +a
#    export NODE_TLS_REJECT_UNAUTHORIZED=0
#    export BW_SESSION=$(bw unlock --raw --passwordenv BW_PASSWORD)
# 2. apply to the company agent (find its id via `multica agent list`)
./apply-mcp.sh <agent-id> [atlassian-email]   # email defaults to peter@chainlayer.io
```

Idempotent — re-run anytime; it rebuilds and replaces the whole `mcp_config`.
`mcp_config` is stored per-agent and redacted on read.

## Sync (repo → Multica, one-way)

`scripts/sync.py` in the `multica-agents` repo now pushes `mcp_config` from
agent.json files to Multica automatically. This is **one-way** (repo → Multica)
— MCP config is never read back from Multica because it is redacted on read.

To update MCP servers for an agent:
1. Edit the agent's `agent.json` in the `multica-agents` repo.
2. Commit and push.
3. Run `scripts/sync.py` (or let the sync autopilot pick it up).

The `apply-mcp.sh` script above is still the authoritative way to **build** the
config (it resolves Bitwarden placeholders to real secrets), but once the
resulting JSON is in the repo, the sync keeps Multica in line.

## Gotchas (these cost real time on TRE-66)

- **Slack bot token:** the `korotovsky/slack-mcp-server` crashes on boot with a bot
  token (it enumerates DMs, needs `im:read`/`mpim:read` scopes a bot won't have).
  Use `@modelcontextprotocol/server-slack` with the bot token instead (what this does).
- **"Forces OAuth" despite a valid key:** clear the connector's entry in
  `~/.claude/mcp-needs-auth-cache.json` on the host. A stale needs-auth entry from a
  prior OAuth attempt poisons header auth and the agent only sees `authenticate` tools.
- **Not feasible headless:** Circleback and Google are OAuth-only (no API-key path).
  Atlassian works but currently only exposes Teamwork Graph tools (needs a `cloudId`),
  not full Jira/Confluence search/create.
