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
value="$(git … || :)"                      # …and `|| :` is the same thing, shorter
value="$(git …)" || echo "oh well"         # …and so is reporting without stopping
if [ -n "$(git … 2>/dev/null)" ]; then     # "nothing found" and "could not look" are now the same
value="$(git … 2>&1)"                      # …and stderr in the value is its own trap, below
```

Write one of:

```bash
if ! value="$(git … 2>&1)"; then echo "$value" >&2; exit N; fi
value="$(git …)" || { echo "…" >&2; exit N; }
# …or ask the question of a status you already captured and checked
```

**And do not merge stderr into a captured value.** `git` and the `multica` CLI both
write warnings to stderr **on success**, so `2>&1` can contaminate a value that
arrived with rc=0:

```bash
# origin/main matching both a local branch and a remote-tracking ref:
ts="$(git log -1 --format=%ct origin/main -- f 2>&1)"
#   rc=0, ts="warning: refname 'origin/main' is ambiguous.\n1788442689"
[ "$ts" -gt 0 ]        # "integer expression expected" → else branch → wrong answer
```

Send diagnostics to their own file, keep the value clean, and assert its shape:

```bash
err="$(mktemp)"
if ! ts="$(git … 2>"$err")"; then sed 's/^/  /' "$err" >&2; exit 3; fi
[[ "$ts" =~ ^[0-9]*$ ]] || { echo "unexpected: $ts" >&2; exit 3; }
```

This one is worth its own paragraph because the fix for the ninth instance
introduced it as the tenth, through exactly this door.

**Why.** In September 2026 the nightly sync deleted the bodies of 22 company skills
and committed them straight to `main` (CHA-1211). Investigating it turned up **ten
instances of the same defect** — a failed or changed read reported as a successful
state — across `sync.py`, `sync.sh`, `commit-sync-state.sh`,
`check-config-freshness.sh`, `dump-mcp-configs.sh` and the autopilot descriptions:

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
| the fix for the row above | "the baseline is current" | `2>&1` folded a warning into the value |
| `dump-mcp-configs.sh`'s `find` | "these are the repo's agents" | `find` failed; the list was empty |

Each was individually reproduced and fixed. The point of the rule is that the tenth
one gets caught by a test instead of by an incident.

**Deliberate exceptions** are declared in the script, on or just above the line:

```bash
# lint:fail-open-ok best-effort teardown; nothing downstream reads the result
bw logout >/dev/null 2>&1 || true
```

The reason is required (three words or more) — but be clear about what that does and
does not buy: **three filler words satisfy it.** The word count only stops a bare
marker from silencing the rule by accident; it cannot judge whether the reason is any
good. The actual control is that a waiver appears in a diff and has to be defended in
review. Don't reach for one to make the lint quiet — if the rule is firing on
something legitimate, say so in the reason and let a reviewer disagree.

Known limits of the lint, so nobody assumes more than it does:

- It catches **absorbed failure**, not **unchecked success** — a read whose value is
  used with no test at all still passes. Widening that far would flag most of
  `dump-mcp-configs.sh` legitimately and the signal would go.
- It is line-based. Backtick substitution and `[ "$(git …)" = "" ]` are not matched;
  neither appears in this repo's style.
- The reader list is a list. A command that reads state and is not on it is invisible
  to the rule — `find` was, until it wasn't.

**Until the CI wiring lands** (adding `test_shell_guards.py` and
`test_config_freshness.py` to `.github/workflows/test.yml` needs a token with
`workflow` scope, which no agent has), any change to `sync.sh`,
`commit-sync-state.sh` or `update-checkout.sh` must run
`python3 -m pytest scripts/test_shell_guards.py` by hand.

## Autopilot descriptions get more care than a PR, not less

**Read an autopilot's `status` before writing its description, and never leave a
description referencing code that is not on `main`.** If a change needs unmerged
code, the text goes to the reviewer to apply *after* the merge — the description
and the merge cannot be the same step.

The reason is structural: an autopilot description is the one artefact in this
system with **no review gate and no CI**. Nobody diffs it, nothing tests it, and
a broken one is discovered by a job failing hours later. It is simultaneously the
easiest thing to break and the hardest to notice, which is why it deserves the
extra check rather than the lighter touch it invites.

Both halves of that rule were learned the same day (CHA-1211):

- The instruction that actually caused the skill deletion lived in a description,
  not in the repo — no PR could have caught it, which is why `sync.sh`'s guard
  was not enough on its own.
- A step-1 rewrite was applied to a live, **active** autopilot while the script
  it referenced existed only on an unmerged branch. That set the next run up to
  exit 6. It was caught minutes later only because the change was verified by
  printing the autopilot back and reading it — which is the check, not luck, and
  is why `status` is the first thing to look at.

Practically: `multica autopilot get <id>` before and after, confirm the `status`
you expected, extract any shell block from the **live** text and run `bash -n` on
it rather than trusting what you typed into a text field.

## If a comment asserts a guarantee, write the test that breaks it

Three times in CHA-1211 a comment claimed an invariant the code beneath it did
not uphold — and all three were found by *running* the thing, never by reading it:

| Where | The comment claimed | The code did |
|---|---|---|
| `update-checkout.sh` | "'the sync ran against a stale checkout' cannot be true after a zero exit" | swallowed the fetch error, so the next line compared HEAD against a cached ref |
| `_live_custom_env_for_state` | "a resolved value that never enters the snapshot cannot escape" | returned the JSON-string shape verbatim, secret included |
| `autopilot-step1.sh` | "prefer the copy inside the checkout we just advanced" | fell back to a copy from elsewhere, verifying one tree while the sync read another |

The first two are in git history (`bce49d2`); the third never landed — the fixture
caught it before the commit, which is the heuristic doing its job at the cheapest
possible moment.

A comment asserting a guarantee is a claim about behaviour, and the cheapest way
to find out whether it is true is to try to violate it. So: **when you write one,
write the test that breaks it.** If the test cannot be written, the comment is
probably describing an intention rather than a property, and should say so.

It is also a one-line review question — *"where is the test for that sentence?"* —
and it caught three real bugs here, two of them in the patches that existed to
remove the same class of bug.

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

## A config flag is not a boolean until you've watched it behave

`SLACK_MCP_ADD_MESSAGE_TOOL` reads like an on/off switch and is not one. In
`slack-mcp-server` it is a **channel allowlist**: `true` means every channel, a
comma-separated list means those channels, `!` negates. So `"false"` is parsed as a
one-entry list naming a channel called `false` — and the write tool is still
registered and still offered to the model. Measured against 1.3.0 by listing the
server's tools over stdio:

```
unset    -> 15 tools, conversations_add_message absent
"true"   -> 16 tools, conversations_add_message PRESENT
"false"  -> 16 tools, conversations_add_message PRESENT   <- the trap
""       -> 15 tools, conversations_add_message absent
```

All 35 Chainlayer agents therefore carry `""`, not `"false"`, and
`SlackWriteToolDisabledTest` in `scripts/test_sync.py` fails on any non-empty value.

Two general rules came out of it:

- **Prefer the value that cannot fail unsafe.** If some layer of the delivery path
  drops an empty env var, the result is `unset` — still disabled. `"false"` degrades
  the other way, to enabled. Between two values that both work, pick the one whose
  failure mode is the safe one.
- **Read the flag's semantics from the implementation, not from its name.** This is
  the same defect as the rest of CHA-1211 wearing different clothes: an answer
  arrived where an answer was expected (`false` where a boolean was expected) and
  nobody checked it was an answer to the question being asked.
