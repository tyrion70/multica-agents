---
name: branch-mr-workflow
description: Always use Linear branch names, check MR state before pushing, rebase if open, new branch if merged
type: feedback
---

Every MR must be tied to a Linear issue. If none exists, create one first.

Branch names must come from Linear (visible in issue detail). If multiple MRs are needed for the same issue, append a short suffix (e.g. `ops-123-my-issue-cleanup`).

Before pushing to any branch, always check the MR state first:
1. `glab mr list --source-branch <branch>` — is there an open MR?
2. If open: `git fetch origin main && git rebase origin/main` before pushing
3. If merged: create a new branch from main, don't push to the old one
4. Before every push to an existing MR: fetch and rebase

**CRITICAL: Always rebase on origin/main before creating the MR.** Not just before pushing to existing MRs — EVERY new branch must be rebased on latest main right before `git push` + `glab mr create`. The sequence is always:
```
git fetch origin main
git rebase origin/main
git push -u origin <branch>
glab mr create ...
```
MRs behind main cause merge conflicts and block merging.

**Why:** We used ad-hoc branch names like `feat/phase2-key-fetching` instead of Linear branch names. Also pushed to branches whose MRs were already merged. Linear tracking is required for all work.

**How to apply:** Before creating any branch, check Linear for an existing issue or create one. Use the Linear-provided branch name. Include `Closes OPS-XXX` in the MR description.
