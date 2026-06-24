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
    agent-ids.json       # identity anchor: agent-dir → Multica UUID (Chainlayer)
    <squad>/<agent>/agent.json
  Private/               # Private workspace (9627be94-0c29-49f7-a104-dff19d11a089)
    skills.json          # skill names owned by Private
    agent-ids.json       # identity anchor: agent-dir → Multica UUID (Private)
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

## Agent identity (why syncs no longer churn UUIDs)

Agents are upserted **by UUID**, never by display name. Each workspace has an
`agent-ids.json` sidecar mapping the agent's directory path (e.g.
`_shared/maintainer`) to its Multica UUID. On every run sync:

1. uses the stored UUID if it still resolves to a live agent → `agent update <id>`;
2. else falls back to a one-time **name match** and adopts that UUID into the
   sidecar (this re-anchors an identity that previously churned, on the first run
   after the fix);
3. else treats the agent as genuinely new and **refuses to create** unless
   `--allow-create` is given.

Consequences:

- Renaming an agent's `name` updates the **same** agent (the directory key, not the
  name, is the anchor) — no orphaned squad rosters, mentions, or assignments.
- A transient or mis-scoped `agent list` can no longer silently re-create an agent
  with a fresh UUID. Steady-state autopilot runs pass **no** `--allow-create`, so
  they can only update — never mint.
- A run is hard-capped at `--max-creates` creates (default 2) even with
  `--allow-create`, so a mistake can never mass-mint the whole roster.

Commit `agent-ids.json` along with `.sync-state.json` after any run that changes it.

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
scripts/sync.sh --workspace Private --allow-create   # permit creating new agents (off by default)
```

Creating agents is **off by default**. A steady-state sync only updates existing
agents; if a repo agent has no identity anchor and no name match, the run reports an
error rather than minting a UUID. To add a genuinely new agent, run once with
`--allow-create` (and raise `--max-creates` only for a deliberate bulk bootstrap).

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

Each workspace directory is scoped to its own UUID (from the script's
`WORKSPACE_IDS` map) for the duration of its sync — `agent list`/`create`/`update`
always target that workspace, never the host default. A run still **refuses** to
sync agents for a directory whose name isn't a known workspace. The two production
autopilots each pass `--workspace <slug>` explicitly anyway (one per workspace).

## Autopilots

The sync autopilots run on schedule and on merges to `main`. Each:
1. Clones (or pulls) the `multica-agents` repo via SSH
2. Runs `sync.sh --workspace <slug>`
3. Commits any pull-back files and the updated `.sync-state.json`
4. Files conflict issues to the relevant squad on divergence

multica-02 runs Chainlayer sync; multica-01 runs Private sync.

## Cross-workspace maintainers

Every squad in both workspaces has two maintainer agents as members:

| Workspace | Local maintainer | Cross-workspace bridge |
|---|---|---|
| Chainlayer | DeepSeek / ChatGPT / Claude Maintainer (per-squad, runs on multica-02) | **Private Maintainer** (`_shared/maintainer-private`, runs on multica-01) |
| Private | Per-squad Maintainer (runs on multica-01) | **Chainlayer Maintainer** (`_shared/maintainer-chainlayer`, runs on multica-02) |

- The **local maintainer** handles workspace help and sync for its own workspace.
- The **cross-workspace bridge** exists in the opposite workspace so squads can route work across. If a Chainlayer issue needs something done in Private, assign the **Private Maintainer**. If a Private issue needs something in Chainlayer, assign the **Chainlayer Maintainer**.

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
3. Open a PR. After merge, create it with one deliberate run:
   `scripts/sync.sh --workspace <ws> --allow-create`. The run writes the new UUID
   into `<workspace>/agent-ids.json`; commit that file so later steady-state syncs
   upsert the agent by id. (The scheduled autopilot does **not** pass
   `--allow-create`, so it will not create the agent on its own.)

## SSH access

The repo requires SSH auth to GitHub. The correct key and any needed SSH config are documented in the `ssh` skill. Identity: `git@github.com:tyrion70/multica-agents.git`.
