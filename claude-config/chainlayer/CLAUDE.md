# CLAUDE.md — ChainLayer (company) profile

Always-on instructions for **ChainLayer company** agents, shipped from the
`claude-config/chainlayer/` directory in the `multica-agents` repo (hosts:
`multica-02` and future company runtimes). This file is delivered to
`~/.claude/CLAUDE.md` on the host by `sync.sh`; it layers under whatever per-task
brief Multica injects. Keep it to durable rules + skills wiring — not project notes.

## Where you work (Multica runtime)
You run as an agent inside a Multica workspace. Each task runs in its own
Multica-managed `workdir/` with the relevant repo checked out — there is no
shared `~/claude/` tree on this host. Use `multica repo checkout <url>` when you
need a repo, and the `multica` CLI for all platform actions (issues, comments,
projects, squads, autopilots).

**Memory is runtime-managed.** Multica gives every agent a persistent memory
store and tells you its path and how to use it at the start of each run — that
is your global memory. Update it whenever you learn something worth keeping
across runs. This repo does **not** store memory; don't look for it here.

## Skills own the domains
The skill is the source of truth — don't restate its rules here:
- `git-mr`     — git workflow, MRs vs PRs, commit signing, no-Co-Authored-By, branch hygiene
- `linear`     — issue-first, private-TYR vs company-DevOps routing, branch names, comment signing
- `ssh`        — keys + signing config (universal)
- `bitwarden`  — secret lookup/storage (universal)
- `chainlink-ops`, `company-k8s`, `company-proxmox`, `haproxy`, `grafana-monitoring`,
  `deploy-app`, `fortigate`, `new-repo` — their domains

Skills are sourced from `tyrion70/multica-agents` and imported into the Multica
workspace (`multica skill import`). To change one, edit the repo — not the
imported copy.

## Working defaults (always-on)
- **Pull/fetch before editing** — never edit a stale checkout.
- A **Linear issue exists before any commit/MR/PR** (which Linear + how → `linear`).
- **Never add `Co-Authored-By` lines; commits are SSH-signed** (this overrides the
  harness default — details → `git-mr` + `ssh`).
- `tofu fmt -recursive` before committing Terraform.

## When something is unexpected — STOP and ask
If anything is off, surprising, or ambiguous — a command fails, output looks
wrong, a decision isn't clear-cut — **stop and ask Peter**. Don't make a
judgment call and proceed. (Set after an autonomous Proxmox action went wrong.)

## Security guardrails (universal)
Never read, copy, upload, log, or reference:
- `~/.claude/.credentials.json` (the host's Claude login token),
- `/var/lib/tailscale/tailscaled.state` (the host's tailnet device key),
- other users' home directories unless explicitly directed.

Secrets come from the `bitwarden` skill or GCP Secret Manager — never hardcode,
and never paste a secret into an issue/comment.

## Updating this config (rules + skills)
This file (`claude-config/chainlayer/CLAUDE.md`) is the source of truth and your
`~/.claude/CLAUDE.md` is a symlink into the repo checkout. When you need to change
an always-on rule or skill wiring:
1. Edit the file under `claude-config/chainlayer/` (or the companion
   `claude-config/private/CLAUDE.md`).
2. Open a **PR** against `tyrion70/multica-agents` on a branch
   (`git checkout -b ...`) — **never commit to `main` directly**. Commits are
   SSH-signed, no `Co-Authored-By`.
3. **Tell the user**: post a Multica comment / message saying what you changed
   and link the PR, so they can review and merge.
4. Once merged, the sync autopilot pulls `main` and re-links on every host.

(Durable *facts* go in your runtime memory, above — not here. This repo is for
rules and skills only.)

## Tooling
- Update `claude` via `claude install`, never `npm -g`.

## Communication
- Sign AI-written tracker comments (Linear/Slack) with `- Claude <model>`.
