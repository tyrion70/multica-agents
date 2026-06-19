# multica-agents

Version-controlled agent configuration for Multica workspaces.

## Folder structure

```
multica-agents/
  <workspace-slug>/           # "Chainlayer", "Private", etc.
    <squad>/                  # e.g. "chainlayer-squad-deepseek"
      squad.json              # optional squad-level config
      <agent-slug>/           # e.g. "tech-lead"
        agent.json            # agent definition (JSON Schema: schemas/agent.json)
    _shared/                  # cross-squad agents (not tied to any one squad)
      <agent-slug>/
        agent.json
  schemas/
    agent.json                # JSON Schema for agent config
    squad.json                # JSON Schema for squad config (optional)
  scripts/
    sync.sh                   # sync agents to Multica via API
```

## Placeholder format

Secrets must **never** be committed in plaintext. Use these placeholders, which the sync script resolves at runtime:

| Placeholder | Source |
|---|---|
| `{{VAULT:folder/item-name}}` | Bitwarden / Vaultwarden secret |
| `{{SECRET:name}}` | Generic secret reference |

Example:

```json
{
  "custom_env": {
    "GITHUB_TOKEN": "{{VAULT:shared/github-token}}"
  }
}
```

## Usage

### Adding a new agent

1. Create the folder: `<workspace>/<squad-or-_shared>/<agent-slug>/`
2. Add `agent.json` conforming to `schemas/agent.json`
3. Open a PR to this repo
4. Merge triggers the sync autopilot (or run `scripts/sync.sh` manually)

### Adding a new squad

1. Create the folder: `<workspace>/<squad>/`
2. Optionally add `squad.json` conforming to `schemas/squad.json`
3. Add agent subfolders as above

### Updating agent configuration

When an agent's configuration changes in Multica (new skills, env, MCP servers), the agent is instructed to open an MR to this repo to persist the change. The sync autopilot keeps the repo regularly synced with live Multica state.

## Workspaces

### Chainlayer

Company workspace — ChainLayer infrastructure and operations agents. Managed by the Chainlayer Squad DeepSeek.

### Private

Personal workspace. This folder requires manual population — current workspace actors cannot access the private workspace. Add agent configurations here for personal projects.
