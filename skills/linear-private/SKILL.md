---
name: linear-private
description: STOP — private/personal work does NOT use Linear. Triggers whenever you're about to create, look up, or sync a Linear issue for a github.com/tyrion70 repo or a personal project (homelab, tremor/earthquakes, ess-ai-planner, weekend-escape-radar, …). Private/personal tracking lives in Multica — use the `multica-private` skill instead. This is a guardrail to prevent accidentally filing private Linear stories. For ChainLayer COMPANY Linear work, use the `linear-company` skill.
---

# Private work does NOT use Linear — use Multica

This is a **guardrail skill**, not a how-to. If you got here because a private or
personal task looked like it needed a Linear issue: **stop.** Private/personal
work is tracked in **Multica**, not Linear. There is no private Linear workspace
in the loop anymore.

→ **Use the `multica-private` skill** for anything personal: `github.com/tyrion70/*`
repos, homelab, tremor/earthquakes, ess-ai-planner, weekend-escape-radar, and
the like. The Multica issue is the tracking artifact — see `multica-private` for the
find-or-create / link / close conventions.

## The rule

> **Do NOT create, mirror, or sync a Linear story for private/personal work.**
> One unit of private work = one Multica issue. No TYR stories, no
> Multica→Linear mirroring on the private side.

This replaces the old `linear-tyrion` flow (a Tyrion/TYR workspace reached via a
personal API key, which used to find-or-create a Linear story per Multica
issue). That behavior is intentionally gone — it created exactly the duplicate
private stories this guardrail now prevents.

## Routing — am I actually private?

| Signal | → |
|---|---|
| Repo remote is `github.com/tyrion70/*` | **private → `multica-private` skill** (NOT Linear) |
| Project is personal (homelab, tremor/earthquakes, ess-ai-planner, weekend-escape-radar, …) | **private → `multica-private` skill** (NOT Linear) |
| Repo remote is `gitlab.com/chainlayer/*`, or ChainLayer infra | → **`linear-company`** (company Linear is still in use) |

If ownership is unclear, **STOP and ask the user** (one question: "Multica
(private)" vs "ChainLayer Linear (company)"). Never guess, never default.

## When to ask the user

- You believe a private task genuinely needs a Linear story anyway (rare) →
  confirm explicitly before creating anything; default is Multica.
- A Multica issue's `external_issue_url` points at a private/TYR Linear story
  (legacy) → surface it; don't recreate or re-sync it, just track in Multica.
