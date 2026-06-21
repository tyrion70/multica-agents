---
name: linear-company
description: Create, update, comment on, or look up COMPANY Linear issues in the ChainLayer workspace (teams OPS/CLL/MAN, via MCP tools). Use BEFORE any ChainLayer Linear work and BEFORE any coding task on a gitlab.com/chainlayer repo or ChainLayer infra (k8s-apps, helm-charts, chainlink-*, haproxy, monitoring, *-iac, *-infra) that ends in a commit/MR (issue-first rule). For private/personal work use the `multica-private` skill instead (private work is tracked in Multica, not Linear).
---

# Linear — ChainLayer (company) workspace

Company side only: the **ChainLayer** workspace, teams `OPS`/`CLL`/`MAN`,
accessed via the claude.ai Linear MCP tools. Private/personal work is **not in
Linear at all** anymore — it's tracked in Multica; **use the `multica-private` skill for
anything personal** (github.com/tyrion70 repos, homelab, tremor, ess-ai-planner,
…). Routing to the wrong place is the #1 mistake; if ownership is unclear,
**STOP and ask the user** (one question: "ChainLayer (company)" vs "Multica
(private)"). Never guess, never default.

Use this skill when the signal points company:

| Signal | → |
|---|---|
| Repo remote is `gitlab.com/chainlayer/*` | **this skill (ChainLayer)** |
| Project is ChainLayer infra (k8s-apps, helm-charts, chainlink-*, haproxy, monitoring, *-iac, *-infra) | **this skill (ChainLayer)** |
| Repo remote is `github.com/tyrion70/*`, or a personal project | → **`multica-private`** (Multica, not Linear) |

## Access (ChainLayer workspace, via MCP)

- Use the `mcp__claude_ai_Linear__*` MCP tools. These ONLY target the company
  workspace — never use them for private work.
- Teams: **DevOps (`OPS`)** is the default for infrastructure work. `CLL` and
  `MAN` also exist — if the task clearly belongs to one of those, use it; if
  unsure between teams, ask the user rather than defaulting silently.
- The MCP tools are claude.ai-connector backed: they are unavailable in
  headless/cron runs. If the tools are missing, say so — there is no API-key
  fallback for the company workspace (and private work isn't in Linear at all;
  that's the `multica-private` skill).

## Conventions

1. **Issue before code.** Any task that will produce a commit/MR needs its
   issue created FIRST. No exceptions unless the user explicitly insists — in
   that case proceed but note in the MR description that no Linear issue was
   linked and why. (Multica-origin tasks: the Multica issue already exists — use
   the "Multica issues: link & sync" section below to find-or-create and link its
   Linear story before the first commit.)
2. **Issue body template** — always this structure:

   ```
   ## Why
   <why are we doing this / why do we care — required>

   ## Done When
   - [ ] <acceptance criteria as checkboxes — required>

   ## Additional Information
   <optional>
   ```

3. **Always assign to Peter** (`assignee: "me"` on MCP). Applies to follow-up
   issues created mid-task too.
4. **Branch name comes from Linear.** Use the Linear-generated branch name
   (`peter/ops-XXXX-<slug>`). If the branch was already used for a merged MR,
   append a short suffix (`-cleanup`, `-v2`) — never reuse a merged branch.
5. **Sign comments** with `- Claude <model>` so AI-written comments are
   distinguishable.
6. **Link the change back**: after the MR exists, its URL goes on the issue
   (attachment or comment), and the MR description carries `Closes OPS-XXXX`
   for traceability — but **always close the Linear issue explicitly via MCP
   after the MR merges** (magic words are not reliable). See the `git-mr` skill.

## Multica issues: link & sync

When the task comes from a **Multica issue** (you're in a Multica workspace — the
`multica` CLI is present and the runtime brief gave you a Multica issue id) that
routes company (per the table above), the Multica issue is your working surface
but the ChainLayer Linear story stays the delivery system of record. Link them up
front, then keep them in sync.

**On entry — already linked?** Before creating anything, check the Multica issue's
`external_issue_url` metadata (`multica issue metadata list <id> --output json`)
and scan its description + comments for an `OPS-\d+` / `CLL-\d+` / `MAN-\d+`
identifier or a `linear.app/…/issue/…` URL. If any is found, do NOT create a
second story.

- **No link → create one "as usual"** via the MCP access path above (body
  template, assigned to Peter), then pin it back so future runs don't duplicate it:

  ```bash
  multica issue metadata set <multica-issue-id> --key external_issue_url \
    --value "https://linear.app/chainlayer/issue/OPS-123"
  ```

- **Already linked → keep in sync, don't duplicate.** Closing the Multica issue
  must close the ChainLayer story:
  - Include `Closes OPS-XXXX` in the MR description for traceability, but
    **do not rely on it to auto-close the Linear issue** — the GitLab↔Linear
    magic-word integration is not reliable.
  - **After the MR merges (or the Multica issue reaches a terminal state),
    explicitly close the Linear issue** via the `mcp__claude_ai_Linear__*`
    status-update tool. Mirror `done`→Done, `cancelled`→Cancelled. This is a
    required completion step, not a fallback. (MCP is unavailable in
    headless/cron runs — if so, say so rather than skipping silently.)
  - Keep `external_issue_url` honest — if it's stale on entry, overwrite or
    `multica issue metadata delete` it before exiting.

This skill only guarantees Multica-closed ⇒ Linear-closed; don't mirror the
reverse direction unless asked.

## When to ask the user (explicit list)

- Ownership unclear (could be private → would be `multica-private`, not Linear).
- Company team unclear between OPS / CLL / MAN.
- User asks to skip the issue → confirm once, then proceed with the MR note.
- Deleting or closing issues you didn't create this session.
- A Multica issue's `external_issue_url` points at a **private** (Tyrion/TYR)
  Linear story (legacy) → this is the wrong skill, and private work isn't in
  Linear anymore; don't re-link, surface the mismatch (track it in Multica per
  the `multica-private` skill).
