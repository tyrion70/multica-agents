---
name: multica-private
description: Track PRIVATE/personal work in Multica (NOT Linear). Use BEFORE any personal coding task that ends in a commit/PR, and whenever creating, updating, commenting on, or looking up a personal issue. The private-side tracker — personal projects (homelab, tremor/earthquakes, ess-ai-planner, weekend-escape-radar, tyrion70/* repos, …) live in Multica. Company/ChainLayer work uses the `linear-company` skill; the `linear-private` guard redirects any private-Linear attempt back here. (Named `-private` because Multica may also be used for company work later, which would get its own skill.) The golden rule: do NOT open a fresh Linear story for things picked up in Multica.
---

# Multica (private) — private/personal issue tracking

Peter's **personal** work is tracked in **Multica**, not Linear. This skill is
the private-side tracker. The `linear-private` skill is a guardrail that catches
any attempt to file a private Linear story and points back here. Company
ChainLayer work is unchanged — that routes to the `linear-company` skill
(ChainLayer Linear via MCP).

## The golden rule

> **Do NOT create a Linear story for each thing picked up in Multica.**

When you are working an item that already exists in Multica (an assigned issue,
an autopilot run, a chat request), **that Multica issue IS the tracking
artifact.** Do not mirror it into Linear, and do not create a parallel Linear
issue "to be safe." One unit of work = one tracker. For personal work that
tracker is Multica.

## Step 1 — route: private or company?

Same private/company ownership fork as the paired router skills — decide first.
Private side: this skill (tracker), `git-pr` (delivery), `new-repo-private`.
Company side: `linear-company` (tracker), `git-mr`, `new-repo-company`.

| Signal | Tracker |
|---|---|
| Repo remote is `github.com/tyrion70/*` | **PRIVATE → Multica (this skill)** |
| Project is personal (homelab, tremor/earthquakes, ess-ai-planner, weekend-escape-radar, …) | **PRIVATE → Multica (this skill)** |
| Repo remote is `gitlab.com/chainlayer/*` | **COMPANY → ChainLayer Linear (`linear-company` skill)** |
| Project is ChainLayer infra (k8s-apps, helm-charts, chainlink-*, haproxy, monitoring, *-iac, *-infra) | **COMPANY → ChainLayer Linear (`linear-company` skill)** |

**If the signals conflict or nothing matches: STOP and ask the user** (one
question, two options: "Multica (private)" vs "ChainLayer Linear (company)").
Never guess, never default.

## Step 2 — the `multica` CLI is the interface

All Multica reads/writes go through the `multica` CLI (already on PATH and
authenticated). Never hit Multica URLs/APIs with `curl`/`wget` — only the CLI
carries auth. The CLI is the manifest: run `multica --help`, then
`multica <command> --help` / `multica <command> <subcommand> --help`, and add
`--output json` for structured data. Never invent commands or flags.

Common surface (verify with `--help` before relying on it):

```bash
multica issue list --output json
multica issue get <id> --output json
multica issue create --title "..." [--description-stdin] [--assignee-id <uuid>] [--project <id>]
multica issue update <id> [--status ...] [--priority ...]
multica issue status <id> <todo|in_progress|in_review|done|blocked|backlog|cancelled>
multica issue comment add <id> --content-stdin   # HEREDOC body, never inline --content
multica issue comment list <id> --output json
```

For comment bodies, use a quoted-delimiter HEREDOC (`<<'COMMENT'`) so the shell
does not expand backticks / `$()` / `$VAR`; never inline `--content` for
authored bodies.

## Conventions (private/Multica work)

1. **Issue before code — in Multica, not Linear.** A personal task that will
   produce a commit/PR needs a Multica issue first. But if you are already
   working an existing Multica issue, that one counts — do **not** create a
   second one (see the golden rule). When in doubt whether an issue already
   exists, list/search Multica first rather than creating a duplicate.
2. **Assign to Peter** (the workspace owner) on issues you create, unless an
   agent/squad should own it. Don't leave personal issues unassigned.
3. **Branch name comes from the Multica issue.** Use the issue identifier as
   the branch slug, e.g. `peter/tre-58-replace-linear-skill`. The `multica repo
   checkout` flow already creates a dedicated worktree branch for agent runs;
   for hand work, branch off `origin/main` with the issue-derived name.
4. **Link the change back to the Multica issue.** After the PR exists, post its
   URL on the Multica issue (comment) and pin `pr_url` in issue metadata if a
   future run on the same issue will read it. The PR description still carries a
   GitHub-side `Closes #NN` for the *code* repo where applicable — see `git-pr`.
5. **No Linear closing magic words for private work.** `Closes TYR-XXX` is gone;
   personal issues close in Multica (`multica issue status <id> done`), not via
   a Linear integration.

## Mentions are side-effecting

In Multica, `[@Name](mention://agent/<id>)` enqueues a *run* for that agent and
`mention://member/<id>` notifies a human — they are actions, not formatting.
Use plain names in prose; only mention to escalate, to delegate a concrete
sub-task for the first time, or when explicitly asked. When wrapping up, end
with no mention. (The workspace `multica-mentioning` skill has the full
contract.)

## When to ask the user (explicit list)

- Ownership routing unclear (private vs company / new project).
- A Multica issue might already exist for this work but you can't find it →
  ask before creating a new one (avoid duplicate trackers).
- Asked to close/cancel an issue you didn't open this session.

## Relationship to the other skills

- `linear-company` — company ChainLayer work only (teams OPS/CLL/MAN, via MCP).
- `git-pr` — how a private change lands (GitHub PR for `github.com/tyrion70/*`).
  The tracker it links back to is the **Multica issue**, not a TYR issue.
- `new-repo-private` — new private repos still go to GitHub `tyrion70` (always
  private); the tracking issue is created in **Multica**, not Linear.

> Note: the workspace also ships platform skills (`multica-working-on-issues`,
> `multica-mentioning`, `multica-creating-agents`, `multica-autopilots`, …) that
> document the Multica *product contracts*. This skill is the thin
> personal-workflow layer on top — defer to those for platform mechanics.
