# multica-agents

Version-controlled agent configuration for Multica workspaces.

## Folder structure

```
multica-agents/
  <workspace-slug>/           # "Chainlayer", "Private", etc.
    skills.json               # list of skill names owned by this workspace
    <squad>/                  # e.g. "chainlayer-squad-deepseek"
      squad.json              # optional squad-level config
      <agent-slug>/           # e.g. "tech-lead"
        agent.json            # agent definition (JSON Schema: schemas/agent.json)
  skills/
    <skill-name>/
      SKILL.md                # frontmatter (name, description) + body content
      <subdir>/...            # optional supporting files
  schemas/
    agent.json                # JSON Schema for agent config
    squad.json                # JSON Schema for squad config (optional)
  scripts/
    sync.sh                   # sync agents + skills (thin wrapper around sync.py)
    sync.py                   # bidirectional sync engine
  .sync-state.json            # last-synced snapshot — committed after each run
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

1. Create the folder: `<workspace>/<squad>/<agent-slug>/`
2. Add `agent.json` conforming to `schemas/agent.json`
3. Open a PR to this repo
4. Merge triggers the sync autopilot (or run `scripts/sync.sh` manually)

### Adding a new squad

1. Create the folder: `<workspace>/<squad>/`
2. Optionally add `squad.json` conforming to `schemas/squad.json`
3. Add agent subfolders as above

### Sync behaviour (bidirectional)

`scripts/sync.py` compares both sides against a `.sync-state.json` snapshot committed after each run. Works for both agents and skills:

| Situation | Action |
|---|---|
| repo changed, Multica unchanged | push repo → Multica (create or update) |
| Multica changed, repo unchanged | pull Multica → repo (write files) |
| both changed | conflict — exit 2, JSON on stdout for the autopilot to file an issue |
| neither changed | unchanged |

On the **first sync** (no state file), repo wins.

After a pull-to-repo run, the autopilot must commit and push the updated files and `.sync-state.json`.

**Flags:**
```
scripts/sync.sh --type agents|skills|all   # default: all
scripts/sync.sh --workspace Chainlayer     # one workspace only
scripts/sync.sh --dry-run                  # print what would happen
```

### Adding a skill

1. Add `skills/<name>/SKILL.md` with frontmatter: `name:` and `description:`, then the body.
2. Add the skill name to the relevant `<workspace>/skills.json`.
3. Open a PR. Merge triggers the Skill Sync autopilot.

### Updating agent configuration

When an agent's configuration changes in Multica, the next autopilot run detects the Multica-side change and writes it back automatically (unless the repo also changed, in which case a conflict issue is filed).

## Workspaces

### Chainlayer

Company workspace — ChainLayer infrastructure and operations agents. Managed by the Chainlayer Squad DeepSeek.

### Private

Personal workspace. This folder requires manual population — current workspace actors cannot access the private workspace. Add agent configurations here for personal projects.
