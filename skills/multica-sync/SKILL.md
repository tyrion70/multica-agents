---
name: multica-sync
description: How agent and skill configuration is managed in both workspaces via the multica-agents repo and bidirectional sync.
---

# Multica Agent & Skill Sync

All Multica agent and skill configuration is version-controlled in the **`multica-agents` repository** (`github.com/tyrion70/multica-agents`, private). Changes to agents and skills must go through that repo — the sync autopilot pushes repo changes to the workspace and pulls any workspace-side edits back to the repo.

## Repository layout

```
multica-agents/
  Chainlayer/            # Chainlayer workspace (0014efc5-f6fb-42bf-9616-4aaeb07ce237)
    skills.json          # skill names owned by Chainlayer
    <squad>/<agent>/agent.json
  Private/               # Private workspace (9627be94-0c29-49f7-a104-dff19d11a089)
    skills.json          # skill names owned by Private
    <squad>/<agent>/agent.json
  skills/
    <name>/SKILL.md      # frontmatter (name, description) + body
    <name>/<subdir>/...  # optional supporting files
  scripts/
    sync.sh              # entry point (thin wrapper)
    sync.py              # bidirectional sync engine
  .sync-state.json       # committed snapshot used for direction detection
```

## Making a change

**To update an agent or skill**, edit the repo and open a pull request against `main`. The sync autopilot triggers on merge and applies the change. Never edit agents or skills directly in the Multica UI as the permanent state — the next sync will detect a conflict.

If you make an emergency edit directly in the workspace, the next sync writes it back to the repo automatically (pull direction).

## Sync direction logic

`sync.py` compares the current repo state and live Multica state against the last-committed `.sync-state.json` snapshot:

| Repo changed | Multica changed | Action |
|---|---|---|
| yes | no | push repo → Multica (create or update) |
| no | yes | pull Multica → repo (write files back, then commit) |
| yes | yes | **conflict** — exit 2, file an issue, do not overwrite either side |
| no | no | unchanged |

On first sync (no state file), repo wins.

## Running the sync manually

```bash
git clone git@github.com:tyrion70/multica-agents.git multica-agents
# or refresh: git -C multica-agents pull --ff-only

cd multica-agents
scripts/sync.sh                             # agents + skills, all workspaces
scripts/sync.sh --type skills               # skills only
scripts/sync.sh --type agents               # agents only
scripts/sync.sh --workspace Chainlayer      # Chainlayer workspace only
scripts/sync.sh --workspace Private         # Private workspace only
scripts/sync.sh --dry-run                   # preview without changes
```

Always use SSH for cloning (consult the `ssh` skill). Never fall back to HTTPS.

## Workspace IDs

Both workspaces live on the same Multica instance (`multica.252h.org`):

| Workspace slug | UUID |
|---|---|
| Chainlayer | `0014efc5-f6fb-42bf-9616-4aaeb07ce237` |
| Private | `9627be94-0c29-49f7-a104-dff19d11a089` |

Passing `--workspace Chainlayer` or `--workspace Private` automatically sets `MULTICA_WORKSPACE_ID` to the correct UUID so all CLI calls target the right workspace.

## Machine defaults

| Host | Default workspace |
|---|---|
| multica-01 | Private |
| multica-02 | Chainlayer |

Running `sync.sh` without `--workspace` targets all workspace directories in the repo but uses the host's default workspace ID for CLI calls. Always pass `--workspace` explicitly in autopilots and agents.

## Autopilots

The sync autopilots run on schedule and on merges to `main`. Each:
1. Clones (or pulls) the `multica-agents` repo via SSH
2. Runs `sync.sh --workspace <slug>`
3. Commits any pull-back files and the updated `.sync-state.json`
4. Files conflict issues to the relevant squad on divergence

multica-02 runs Chainlayer sync; multica-01 runs Private sync.

## Conflict handling

When both sides change independently, the script exits 2 and prints a JSON conflict report on stdout. The calling agent or autopilot must:
1. File one issue per conflicting item
2. For Chainlayer: assign to squad `610be128-4320-4ca1-8f1d-413c2657cd2c`
3. For Private: assign to Peter (`997b06ce-c4e1-4ca9-b5e8-bcc0325749c9`)
4. Leave both sides unchanged — do not pick a winner

## Adding a new skill

1. Create `skills/<name>/SKILL.md` with YAML frontmatter (`name:`, `description:`) and body.
2. Add any supporting files under `skills/<name>/`.
3. Add the skill name to `Chainlayer/skills.json` and/or `Private/skills.json`.
4. Open a PR. Merge triggers the skill sync autopilot.

## Adding a new agent

1. Create `<workspace>/<squad>/<agent-slug>/agent.json` (see `schemas/agent.json`).
2. Optionally add the agent to the squad's `squad.json` members list.
3. Open a PR. Merge triggers the agent sync autopilot.

## SSH access

The repo requires SSH auth to GitHub. The correct key and any needed SSH config are documented in the `ssh` skill. Identity: `git@github.com:tyrion70/multica-agents.git`.
