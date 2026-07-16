---
name: git-mr
description: Ship a COMPANY code change as a GitLab MR. Use whenever committing, pushing, or creating a merge request in a gitlab.com/chainlayer repo. Enforces Linear-issue-first (ChainLayer OPS/CLL/MAN), Linear branch names, rebase-before-push, the MR template, SSH-signed commits, and explicit Linear ticket closure on merge. For private github.com/tyrion70 PRs use the `git-pr` skill instead.
---

# Shipping changes — GitLab MR workflow (company)

Company side only: `gitlab.com/chainlayer/*` repos, shipped via `glab` MRs.
**Private `github.com/tyrion70/*` repos use the `git-pr` skill** — different
forge, CLI, and tracker. If `git remote get-url origin` is neither, ask the user.

Companion to the `linear-company` skill: that one decides *which issue*, this
one decides *how the change lands*. If no Linear issue exists yet, **invoke the
`linear-company` skill first** — issue-before-code, no exceptions unless the
user explicitly waives it (then note the waiver in the MR description).

> **Documentation carve-out (`gitlab.com/chainlayer/documentation`).** Doc work
> in the documentation repo is tracked in **Multica, not Linear** — the Multica
> issue is the system of record. For doc MRs, follow every mechanic below
> (identity, fetch/rebase, SSH-signed commits, no `Co-Authored-By`, the MR
> template) **except** the Linear-issue-first requirement and the
> `Closes OPS-XXXX` closing words: reference the Multica issue in the MR
> description instead, and skip the Linear close step. The **only** exception is
> a doc change that *derives from* an existing OPS/CLL/MAN issue — then keep the
> normal Linear linkage and closing words. Use the **`chainlayer-docs`** skill
> for the docs toolchain (templates, markdownlint + retype build, gitleaks,
> the merge-to-`main` → Pages publish path, and the sensitive-page sign-off gate).

## Step 1 — confirm the remote is company

```bash
git remote get-url origin   # must be gitlab.com/chainlayer/*
```

| Remote | Forge | CLI | Tracker |
|---|---|---|---|
| `gitlab.com/chainlayer/*` | GitLab | `glab` | ChainLayer Linear (OPS/CLL/MAN) |
| `github.com/tyrion70/*` | → use the **`git-pr`** skill | | |
| anything else | **ask the user** | | |

> **GitLab auth token (group PAT).** `glab` and the REST API authenticate with
> the vault group PAT (`ChainLayer · GitLab — group PAT`, `bitwarden` **company**
> folder). It carries the **`self_rotate`** scope, so a near-expiry token is
> **not** a reason to escalate — rotate it yourself and write the new value back
> to the vault. Full recovery path (rotate via `POST
> /personal_access_tokens/self/rotate`, write-back, and the "must still be valid,
> so rotate proactively" caveat) lives in the **ssh** skill under *GitLab group
> PAT — keep it alive yourself*. A hard-expired (401) token still needs a human.
> This is orthogonal to the SAML SSO gate (also in the **ssh** skill), which a
> fresh token does not defeat.

## Step 2 — pre-flight (mandatory, every push)

1. **Git identity**: `git config user.email` must be `peter@chainlayer.io`.
   Fix repo-locally if wrong — never commit as a hostname email.
2. **Fetch**: `git fetch origin main`.
3. **Existing MR state** for the branch:
   - `glab mr list --source-branch <branch>`
   - MR **open** → rebase on `origin/main`, then push.
   - MR **merged** → do NOT push to the old branch; new branch off
     `origin/main` with a suffix (`-cleanup`, `-v2`).
   - none → continue.
4. **Branch name**: from the Linear issue (`peter/ops-XXXX-<slug>`). New branches
   start from `origin/main`, never from local main:
   `git checkout -b <linear-branch> origin/main`.
5. **Rebase right before EVERY push** — including the first one. The sequence
   is always:

   ```bash
   git fetch origin main
   git rebase origin/main
   git push -u origin <branch>
   ```

   MRs behind main cause conflicts and block merging.

## Step 3 — commits

- Conventional commits: `<type>: <description>` (feat, fix, refactor, docs,
  test, chore, perf, ci). Short and to the point — don't over-explain.
- **No `Co-Authored-By: Claude` lines.** Peter wants only his own name.
- **Signing**: commits are SSH-signed with `~/.ssh/id_ed25519_signing`
  (`gpg.format ssh`, `commit.gpgsign true`); auth uses `~/.ssh/id_ed25519_peter`.
  Keep the roles separate — full setup in the **ssh** skill. If
  `git log --show-signature` isn't `Good`, fix the signing config there rather
  than committing unsigned.
- Terraform repos: `tofu fmt -recursive` before committing.
- Never commit secrets; machine-consumed tokens live in GCP Secret Manager,
  human-held credentials in the vault (use the **bitwarden** skill — `company`
  folder), local caches only in the gitignored `~/.claude/secrets/`.

## Step 4 — GitLab MR

Two steps, because push options don't support newlines:

```bash
git push -u origin <branch>
glab mr create --fill --title "<type>: <title>" --description "$(cat <<'EOF'
## Summary
<1-2 sentences>

## Linked task
Closes OPS-XXXX

## Changes
- <bullets>

## Impact
<scope and risk: what's affected, what's not, required actions>

---
Claude <model>
EOF
)"
```

**`Closes OPS-XXXX` is for traceability only — do not rely on it to auto-close
the Linear issue.** The GitLab↔Linear magic-word integration is not reliable.
Always include it (or `Refs` for partial work), but you must also explicitly
close the Linear issue via MCP after the MR merges (see "After the MR exists").

## After the MR exists

- Post the URL on the Linear issue and report it to the user.
- **After the MR merges: explicitly close the Linear issue.** Use the
  `mcp__claude_ai_Linear__*` status-update tool to move the issue to Done
  (or Cancelled if appropriate). **Do NOT rely on `Closes OPS-XXXX` magic words
  to do this automatically** — the GitLab↔Linear integration does not reliably
  auto-close. This is a required completion step, not a fallback.
  (MCP is unavailable in headless/cron runs — if so, say so rather than
  skipping silently.)
- ChainLayer k8s-apps note: merging is usually the end of your job — Renovate
  auto-bumps digest-pinned images and ArgoCD syncs (~3 min). Don't open manual
  bump MRs for `latest@sha256:…` pins.
- After the branch merges: check out main, drop stale stashes.

## When to ask the user (explicit list)

- Remote is not `gitlab.com/chainlayer` (and not `github.com/tyrion70`, which
  is the `git-pr` skill's job).
- Any force-push, push directly to `main`/protected branches, or history rewrite.
- Closing/merging someone else's MR, or deleting branches you didn't create.
- The user wants to skip the Linear issue (confirm once, note it in the MR).
