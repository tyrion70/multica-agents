---
name: new-repo-private
description: Create a new PRIVATE git repository the right way — GitHub tyrion70 via the gh CLI, ALWAYS private visibility. Use whenever a personal project needs a new repo or you're about to git init something that will be pushed to tyrion70. Covers the bootstrap commit and post-create checklist. For company gitlab.com/chainlayer repos use the `new-repo-company` skill instead.
---

# Creating a new private repository

Private side only: GitHub `tyrion70`, created with `gh`. Decide **private vs
company** first — if it's a ChainLayer project, use the **`new-repo-company`**
skill (Terraform/gitlab-iac). If ownership is unclear, ask the user; don't guess.

## Private → GitHub `tyrion70`, via `gh`

**Private projects get PRIVATE repos. Always.** No exceptions without the user
explicitly saying "make it public" — and even then confirm once, because
flipping private→public later leaks the full history.

```bash
cd ~/claude/repositories/<name>        # canonical clone location
git init -b main
# … initial content, conventional commit …
gh repo create tyrion70/<name> --private --source . --push
```

- Tracking: Multica issue first (`multica-private` skill) — private work is tracked in
  Multica, not Linear. The bootstrap commit can land straight on `main` for a
  brand-new repo; subsequent changes follow `git-pr`.
- Don't commit secrets in the bootstrap — credentials go in the vault
  (`bitwarden` skill, `private` folder) or gitignored `~/.claude/secrets/`.
- A `.gitignore` covering `.env`, `*.secret`, build artifacts is part of the
  bootstrap, not a follow-up.

## Post-create checklist

- Clone lives under `~/claude/repositories/<name>`.
- Add a one-line entry to `~/.claude/REPOSITORIES.md` (the cross-session repo
  index) and, if a project dir uses it, the project's `REPOSITORIES.md`.
- First real change after bootstrap follows the full `git-pr` flow (branch from
  the Multica issue, PR linked back to it).

## When to ask the user

- Ownership unclear (private vs company → `new-repo-company`).
- ANY request for a public repo — confirm explicitly, restate that history
  becomes visible.
- Repo deletion, rename, transfer, or visibility change on an existing repo.
