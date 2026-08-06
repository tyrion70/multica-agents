# claude-config

Shared Claude Code config for ChainLayer infra work, **pull-based** across every
host that runs a Multica runtime. The repo is the **source of truth** — on each
host `~/.claude/CLAUDE.md` is a *symlink into a checkout of this repo*. Edit the
repo (via PR), never the symlink target in place.

This repo holds **always-on rules + skills wiring only**. Agent *memory* is
**not** stored here — Multica gives each agent a persistent, runtime-managed
memory store (it tells the agent the path and how to use it at run start). See
"Memory" below.

## Two profiles

Hosts split into two profiles so company and personal agents get the right brief:

| Profile | Folder | Hosts | Agents |
|---|---|---|---|
| **private** | `private/` | `multica-01` (192.168.16.104) | homelab / personal projects |
| **chainlayer** | `chainlayer/` | `multica-02` (+ future company hosts) | ChainLayer company infra |

Each `<profile>/CLAUDE.md` is **self-contained**: the always-on rules plus that
profile's skills. An agent on a host reads the one its `~/.claude/CLAUDE.md`
points at.

> Note: the two runtimes are **not** workspace-scoped — each daemon serves every
> workspace its token can see. Keeping company vs personal work apart is done by
> **agent/squad assignment**, not by the runtime.

## Wiring a host

Run as the daemon user (e.g. `peter`):

```bash
# 1. clone (or pull if it already exists)
git clone git@github.com:tyrion70/claude-config ~/claude-config
# 2. pick the profile for THIS host
PROFILE=private        # multica-01   |   PROFILE=chainlayer for multica-02
# 3. link the brief
ln -sfn ~/claude-config/$PROFILE/CLAUDE.md ~/.claude/CLAUDE.md
```

## Memory

Memory is **runtime-managed by Multica**, not stored in this repo. Each agent
gets a persistent memory store and is told its path + usage at the start of every
run; agents update it directly when they learn something durable.

The pre-Multica laptop memories that used to live under `chainlayer/memory/` and
`private/memory/` have been retired: their durable learnings were promoted into
the `chainlayer-knowledge` / `private-knowledge` skills (in `tyrion70/claude-skills`,
bound to the team agents), and the originals were moved to
`_archive/2026-06-13-profile-memory/` for reference.

## Keeping it in sync

Each host runs a **daily cron** (04:37) that `git pull --ff-only`s this repo and
re-asserts its profile symlink, so merged changes propagate automatically.
(claude-*skills* are synced separately by each workspace's Skill Sync autopilot.)
Agents never push to `main` directly — they open a PR and tell the user (see
"Updating this config" in each `CLAUDE.md`). Merges are a human review step.

## Layout

```
README.md            # this file
chainlayer/
  CLAUDE.md          # company profile (rules + skills)
  mcp/               # company MCP config
private/
  CLAUDE.md          # private/homelab profile (rules + skills)
_archive/            # pre-reorg snapshots + retired profile memory
```
