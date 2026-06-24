# CLAUDE.md — Private (homelab / personal) profile

Always-on instructions for **Peter's private / homelab** agents, shipped from the
`claude-config/private/` directory in the `multica-agents` repo (host:
`multica-01`). This file is delivered to `~/.claude/CLAUDE.md` on the host by
`sync.sh`; it layers under whatever per-task brief Multica injects. Keep it to
durable rules + skills wiring — not project notes.

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
- `git-pr`     — private github.com/tyrion70 PR workflow, commit signing, no-Co-Authored-By
- `ssh`        — keys + signing config (universal)
- `bitwarden`  — secret lookup/storage (universal)
- `homelab`    — 4-node Proxmox cluster, UniFi UDM-Pro, Hetzner, Mikrotik
- `tremor`     — worldwide earthquake-monitor app (homelab VM 115)
- `homeassistant` — Peter's Home Assistant (entities, automations, energy/solar)

Skills are sourced from `tyrion70/multica-agents` and imported into the Multica
workspace (`multica skill import`). To change one, edit the repo — not the
imported copy.

## Working defaults (always-on)
- **Pull/fetch before editing** — never edit a stale checkout.
- For private code changes a GitHub PR exists before merge (workflow → `git-pr`).
  Private projects with no tracker (e.g. ESS) follow their own repo conventions.
- **Never add `Co-Authored-By` lines; commits are SSH-signed** (this overrides the
  harness default — details → `git-pr` + `ssh`).
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
This file (`claude-config/private/CLAUDE.md`) is the source of truth and your
`~/.claude/CLAUDE.md` is a symlink into the repo checkout. When you need to change
an always-on rule or skill wiring:
1. Edit the file under `claude-config/private/` (or the companion
   `claude-config/chainlayer/CLAUDE.md`).
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
