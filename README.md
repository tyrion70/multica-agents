# multica-agents

Version-controlled agent configuration for Multica workspaces.

## Folder structure

```
multica-agents/
  <workspace-slug>/           # "Chainlayer", "Private", etc.
    skills.json               # list of skill names owned by this workspace
    agent-ids.json            # identity anchor: agent-dir → Multica UUID (per workspace)
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
4. Merge triggers the sync autopilot. Because creating agents is off by default,
   a brand-new agent must be created with one deliberate run:
   `scripts/sync.sh --workspace <ws> --allow-create`. The run records the new
   UUID into `<workspace>/agent-ids.json` — commit it so steady-state syncs
   upsert the agent by id from then on.

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

After a pull-to-repo run, the autopilot must commit and push the updated files, `.sync-state.json`, and any updated `<workspace>/agent-ids.json`.

### Agent identity is anchored, not name-matched

Each agent is upserted **by UUID**, never by display name. The UUID lives in a
per-workspace `<workspace>/agent-ids.json` sidecar keyed by the agent's directory
path (e.g. `_shared/maintainer`). On every run sync:

1. uses the stored UUID if it still resolves to a live agent (`agent update <id>`);
2. otherwise falls back to a one-time **name match** and adopts that UUID into the
   sidecar (re-anchoring an identity that previously churned);
3. otherwise treats the agent as genuinely new — and **refuses to create it**
   unless `--allow-create` is passed.

This is why renaming an agent's `name` updates the same agent instead of minting a
new UUID, and why a transient/mis-scoped `agent list` can no longer orphan squads,
mentions, and assignments by silently re-creating agents.

**Flags:**
```
scripts/sync.sh --type agents|skills|all   # default: all
scripts/sync.sh --workspace Chainlayer     # one workspace; scopes every CLI call to its UUID
scripts/sync.sh --workspace Private        # Private workspace (9627be94-...)
scripts/sync.sh --dry-run                  # print what would happen
scripts/sync.sh --allow-create             # permit creating new agents (off by default)
scripts/sync.sh --max-creates N            # abort if creates exceed N (default 2; mass-mint guard)
```

Always clone the repo via SSH — never use `multica repo checkout`:
```bash
git clone git@github.com:tyrion70/multica-agents.git multica-agents
# or refresh: git -C multica-agents pull --ff-only
```

### Adding a skill

1. Add `skills/<name>/SKILL.md` with frontmatter: `name:` and `description:`, then the body.
2. Add the skill name to the relevant `<workspace>/skills.json`.
3. Open a PR. Merge triggers the Skill Sync autopilot.

### Updating agent configuration

When an agent's configuration changes in Multica, the next autopilot run detects the Multica-side change and writes it back automatically (unless the repo also changed, in which case a conflict issue is filed).

## Workspaces

Both workspaces live on the same Multica instance (`multica.252h.org`). Passing `--workspace <slug>` to `sync.sh` sets `MULTICA_WORKSPACE_ID` automatically.

| Workspace | UUID | Host default |
|---|---|---|
| Chainlayer | `0014efc5-f6fb-42bf-9616-4aaeb07ce237` | multica-02 |
| Private | `9627be94-0c29-49f7-a104-dff19d11a089` | multica-01 |

### Chainlayer

Company workspace — ChainLayer infrastructure and operations agents.

### Private

Personal workspace — homelab, game dev, Eryndal creative projects, and personal tooling agents.
