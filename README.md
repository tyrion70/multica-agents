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

## Shell script rules (`scripts/*.sh`)

**A command that reads state must have its failure checked, not absorbed.** This is
one rule with one reason, and it is enforced by
`ShellFailOpenLintTest` in `scripts/test_sync.py` — the only test file CI runs today,
which is why the rule lives there rather than in a linter nobody invokes.

Do not write:

```bash
value="$(git … 2>/dev/null || true)"       # a failed read becomes an empty value
if [ -n "$(git … 2>/dev/null)" ]; then     # "nothing found" and "could not look" are now the same
```

Write one of:

```bash
if ! value="$(git … 2>&1)"; then echo "$value" >&2; exit N; fi
value="$(git …)" || { echo "…" >&2; exit N; }
# …or ask the question of a status you already captured and checked
```

**Why.** In September 2026 the nightly sync deleted the bodies of 22 company skills
and committed them straight to `main` (CHA-1211). Investigating it turned up **nine
instances of the same defect** — a failed or changed read reported as a successful
state — across `sync.py`, `sync.sh`, `commit-sync-state.sh`,
`check-config-freshness.sh` and the autopilot descriptions:

| where | what it claimed | what was true |
|---|---|---|
| `multica skill get` without `--with-content` | "the workspace copy is empty" | the body was not requested |
| the same, for `files` | "this skill has no supporting files" | the list was not served |
| `agent list` with no `custom_env` | "the live env was emptied" | the field is never returned |
| `agent list` with `mcp_config: null` | "no MCP config" | it lives behind `mcp_config_redacted` |
| step 1's `git pull --ff-only` | "the checkout is current" | it was three weeks stale |
| `sync.sh`'s scope guard | "nothing out of scope" | `git status` failed |
| `commit-sync-state.sh` | "nothing to commit" | `git status` failed |
| `update-checkout.sh`'s fetch | "HEAD matches the remote" | it matched a cached ref |
| `sync.sh`'s workspace pre-flight | "the workspace matches" | the check itself failed |
| `check-config-freshness.sh` | "the baseline is current" | `git log` failed |

Each was individually reproduced and fixed. The point of the rule is that the tenth
one gets caught by a test instead of by an incident.

**Deliberate exceptions** are declared in the script, on or just above the line:

```bash
# lint:fail-open-ok best-effort teardown; nothing downstream reads the result
bw logout >/dev/null 2>&1 || true
```

The reason is required (three words or more). A waiver in a diff is something a
reviewer can argue with; a swallowed error is not.

**Until the CI wiring lands** (adding `test_shell_guards.py` and
`test_config_freshness.py` to `.github/workflows/test.yml` needs a token with
`workflow` scope, which no agent has), any change to `sync.sh`,
`commit-sync-state.sh` or `update-checkout.sh` must run
`python3 -m pytest scripts/test_shell_guards.py` by hand.

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
