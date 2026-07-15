---
name: git-pr
description: Ship a PRIVATE code change as a GitHub PR. Use whenever committing, pushing, or creating a pull request in a github.com/tyrion70 repo. Enforces Multica-issue-first, issue-derived branch names, rebase-before-push, SSH-signed commits, and linking the PR back to the Multica issue. For company gitlab.com/chainlayer MRs use the `git-mr` skill instead.
---

# Shipping changes — GitHub PR workflow (private)

Private side only: `github.com/tyrion70/*` repos, shipped via `gh` PRs.
**Company `gitlab.com/chainlayer/*` repos use the `git-mr` skill** — different
forge, CLI, and tracker. If `git remote get-url origin` is neither, ask the user.

Companion to the `multica-private` skill: that one decides *which issue*, this one
decides *how the change lands*. Private/personal work is tracked in **Multica**,
not Linear (the `linear-private` skill is just a guardrail that redirects any
private-Linear attempt to Multica). If no Multica issue exists yet, **invoke the
`multica-private` skill first** — issue-before-code, no exceptions unless the user
explicitly waives it (then note the waiver in the PR description). Some private
projects deliberately use no tracker at all — respect the project's notes if so.

## Step 1 — confirm the remote is private

```bash
git remote get-url origin   # must be github.com/tyrion70/*
```

| Remote | Forge | CLI | Tracker | Link-back |
|---|---|---|---|---|
| `github.com/tyrion70/*` | GitHub | `gh` | Multica (`multica-private` skill) | link & close in Multica |
| `gitlab.com/chainlayer/*` | → use the **`git-mr`** skill | | | |
| anything else | **ask the user** | | | |

## Step 2 — pre-flight (mandatory, every push)

1. **Git identity**: `git config user.email` must be `peter@chainlayer.io`.
   Fix repo-locally if wrong — never commit as a hostname email.
2. **Fetch**: `git fetch origin main`.
3. **Existing PR state** for the branch:
   - `gh pr list --head <branch>`
   - PR **open** → rebase on `origin/main`, then push.
   - PR **merged** → do NOT push to the old branch; new branch off
     `origin/main` with a suffix (`-cleanup`, `-v2`).
   - none → continue.
4. **Branch name**: from the Multica issue — use the issue identifier as the
   slug (e.g. `peter/tre-58-<slug>`). New branches start from `origin/main`,
   never from local main: `git checkout -b <branch> origin/main`.
5. **Rebase right before EVERY push** — including the first one. The sequence
   is always:

   ```bash
   git fetch origin main
   git rebase origin/main
   git push -u origin <branch>
   ```

   PRs behind main cause conflicts and block merging.

## Step 3 — commits

- Conventional commits: `<type>: <description>` (feat, fix, refactor, docs,
  test, chore, perf, ci). Short and to the point — don't over-explain.
- **No `Co-Authored-By: Claude` lines.** Peter wants only his own name.
- **Signing**: commits are SSH-signed with `~/.ssh/id_ed25519_signing`
  (`gpg.format ssh`, `commit.gpgsign true`); auth uses `~/.ssh/id_ed25519_peter`.
  Keep the roles separate — full setup in the **ssh** skill. If
  `git log --show-signature` isn't `Good`, fix the signing config there rather
  than committing unsigned.
- Never commit secrets; human-held credentials live in the vault (use the
  **bitwarden** skill — `private` folder), local caches only in the gitignored
  `~/.claude/secrets/`.

## Step 4 — GitHub PR

```bash
git push -u origin <branch>
gh pr create --title "<type>: <title>" --body "$(cat <<'EOF'
## Summary
<1-2 sentences>

Tracked in Multica: <issue identifier / URL>
EOF
)"
```

There is **no Linear closing magic word** for private work — the tracking issue
lives in Multica, not Linear. A GitHub-side `Closes #NN` may still be used to
close an issue in the *code* repo itself, when one exists.

## Approval gate — never self-approve (human review is required)

If the PR carries a **required-review gate** (branch protection "require a pull
request review before merging", required reviewers, CODEOWNERS approval), an agent
must **NOT** submit an approving review on it — **not on its own PR, and not to
cross-approve another agent's PR.** The gate exists to enforce a second-party
*code review*; an agent approving its own or a peer's change defeats the control
the gate is there to provide.

- A **human** approving the PR — or explicitly saying "merge it" / "approved" —
  satisfies the gate. Nothing an agent does satisfies it.
- A verbal go-live "go" (e.g. "Go, direct") authorizes the **deploy**, not the
  code review. It does **not** substitute for the approval. (CHA-719: a verbal
  "Go, direct" was wrongly treated as approval for a required-approval MR.)
- **Route the approval to a human via the Tech Lead.** Post the PR, state it is
  ready and blocked on a required approval, and ask the Tech Lead to have a human
  approve. Do not merge until the gate is satisfied by a human.

## After the PR exists

- Link the PR URL back on the Multica issue (`multica issue comment add`, and
  `pr_url` metadata if a future run will read it) and report it to the user.
- For squad-managed Multica issues, do not leave the issue assigned to the
  individual coder. After the result comment, leave the status in `in_review`
  unless the role/user says otherwise, then assign the issue back to the owning
  squad/team so the standing router wakes and sends it to QA/deploy. Use the
  squad id/name from the issue, project notes, or runtime context; if no owning
  squad is clear, state that instead of guessing. Do not @mention QA as a
  substitute unless the user explicitly asked for a direct mention.
- Close the Multica issue (`multica issue status <id> done`) when the PR merges.
- After the branch merges: check out main, drop stale stashes.

## When to ask the user (explicit list)

- Remote is not `github.com/tyrion70` (and not `gitlab.com/chainlayer`, which
  is the `git-mr` skill's job).
- Any force-push, push directly to `main`/protected branches, or history rewrite.
- Closing/merging someone else's PR, or deleting branches you didn't create.
- The user wants to skip the Multica issue (confirm once, note it in the PR).
