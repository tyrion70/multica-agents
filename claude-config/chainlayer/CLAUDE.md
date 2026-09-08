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
- `1password`  — 1Password secret lookup (universal; the GitLab PAT lives here)
- `chainlayer-knowledge` — durable cross-cutting facts and decisions, **including
  the AI-managed host list** the rule below points at
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

## AI-managed hosts (list in `chainlayer-knowledge`): act, don't ask
This is a **carve-out from the rule above, and the only one** — off the list,
STOP-and-ask applies unchanged.

On a host in the AI-managed tier you do not need human approval for an
operational action you judge necessary — including a destructive one (reboot,
restart, drain, disk reclaim) — provided both of these hold:

1. **Redundancy preserved.** One node of a pair at a time — and establish from
   the load balancer's own view **how the pair absorbs the loss**, not merely
   that the peer is up. The CCIP pairs are active/active (`act=1 bck=0` both,
   no `backup` server, nothing drains); what carries an undrained reboot is
   HAProxy's `option redispatch` + `retries 3` +
   `on-marked-down shutdown-sessions`. If a pair has no such absorption
   configured, it is **not** a free reboot and the licence does not cover it.
2. **Blast radius confined to that host.** Anything that changes shared
   infrastructure — the shared HAProxy config, DNS, the Proxmox host, a shared
   CI template — is outside the tier *even when done for an AI-managed node*.

Then: **no pre-approval, mandatory post-report** — what you did, when, and the
measured outcome, on the issue. And **stop and report on the first anomaly**:
the licence covers *starting*, never *continuing past a surprise*. Repairing in
place after an unexpected result is a new decision and needs a human.

**Which hosts is a list, not a judgement.** The `chainlayer-knowledge` skill
holds it, with the exclusions written down as explicitly as the inclusions. A
host is in the tier by appearing on that list and no other way — "it looks
AI-managed" is not membership. If either condition fails, or the host is not on
the list, you are back under STOP-and-ask.

## Security guardrails (universal)
Never read, copy, upload, log, or reference:
- `~/.claude/.credentials.json` (the host's Claude login token),
- `/var/lib/tailscale/tailscaled.state` (the host's tailnet device key),
- `~/.config/op/service-account-token` (the 1Password service-account token —
  the bootstrap secret unlocking the vault that holds the GitLab PAT; agents may
  *use* it through `op`, never print it),
- other users' home directories unless explicitly directed.

Secrets come from the `bitwarden` or `1password` skills, or GCP Secret Manager —
never hardcode, and never paste a secret into an issue/comment.

## Updating this config (rules + skills)
This file (`claude-config/chainlayer/CLAUDE.md`) is the source of truth and
`sync.sh` copies it to `~/.claude/CLAUDE.md` on each host (copy, not symlink).
When you need to change an always-on rule or skill wiring:
1. Edit the file under `claude-config/chainlayer/` (or the companion
   `claude-config/private/CLAUDE.md`).
2. Open a **PR** against `tyrion70/multica-agents` on a branch
   (`git checkout -b ...`) — **never commit to `main` directly**. Commits are
   SSH-signed, no `Co-Authored-By`.
3. **Tell the user**: post a Multica comment / message saying what you changed
   and link the PR, so they can review and merge.
4. Once merged, **run `sync.sh` on each host** (or wait for the nightly sync
   autopilot) to redeploy the file — the nightly sync is the backstop, not the
   primary deploy path, so don't treat merge as deploy.

**`.sync-state.json` is not covered by step 2.** It is generated bookkeeping — the
record of what `sync.sh` last pushed to each workspace — with no reviewable content,
and it changes on every sync. Commit it **straight to `main`** (`chore: sync state`),
which is what the Sync autopilot already does. Requiring a PR per sync run is friction
that gets the commit skipped, and a skipped commit leaves the baseline behind the live
workspaces, which makes the next unrelated change surface as a false "both sides
changed" conflict. `check-config-freshness.sh` reports that as `BASELINE_LAG` (exit 4).

**The exemption is scoped by PATH, not by commit message.** It covers exactly one
file — `.sync-state.json` — and nothing may ride along on it. Commit it with
`scripts/commit-sync-state.sh --push`, which enforces that scope and refuses if
anything else is dirty; `sync.sh` fails the run (exit 5) rather than leaving a
mixed tree for you to sweep up. Read as a message-scoped licence, this rule put
4,139 unreviewed deletions on `main` in one night (CHA-1211): a sync run rewrote 22
skill bodies and they were committed as "bookkeeping". Any other repo change a sync
produces — an `agent.json` pulled back, a skill body pulled back — is reviewable
content and goes through step 2.

(Durable *facts* go in your runtime memory, above — not here. This repo is for
rules and skills only.)

## Tooling
- Update `claude` via `claude install`, never `npm -g`.

## Communication
- Sign AI-written tracker comments (Linear/Slack) with `- Claude <model>`.
