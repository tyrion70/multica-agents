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

## Step 2 — pre-flight (mandatory, every push)

1. **Git identity**: the commit identity is host-dependent. On an agent
   runtime `git config user.email` must be `peter+agent@chainlayer.io` and
   `user.name` `peter-agent`; on Peter's own machines it is `peter@chainlayer.io`.
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
- **Signing**: commits are SSH-signed with whatever `user.signingkey` this host
  is configured with (`gpg.format ssh`, `commit.gpgsign true`). **The key is
  host-dependent — do not assume a path.** On an agent runtime the signing key is
  the agent's own key, so commits are attributed to
  `peter-agent <peter+agent@chainlayer.io>`; on Peter's machines it is his key.
  The company rule that commits are signed is unchanged; only the key differs by
  host. If `git log --show-signature` isn't `Good`, fix the signing config
  rather than committing unsigned (see "Wiring a host to sign as the agent"
  below).
- Terraform repos: `tofu fmt -recursive` before committing.
- Never commit secrets; machine-consumed tokens live in GCP Secret Manager,
  human-held credentials in the vault (use the **bitwarden** skill — `company`
  folder, or the **1password** skill for the GitLab PAT, which lives at
  `op://Agent Peter/gitlab/password`), local caches only in the gitignored
  `~/.claude/secrets/`.

## Wiring a host to sign as the agent (runbook)

When a new agent runtime is provisioned, it needs the same signing wiring
`multica-02` has. The private key lives in 1Password — pull it from there, never
generate a new one and never reproduce key material in any skill, MR, or
comment. The 1Password item is **"peter-agent SSH commit-signing key
(multica-02)"** in the `Agent Peter` vault (concealed fields `private key` and
`public key`).

1. Read the key out of 1Password at point of use and write the private half to
   `~/.ssh/peter_agent_signing` (mode 0600) and the public half to
   `~/.ssh/peter_agent_signing.pub`. Do not print the key; write it straight to
   the file (a tool's own report of its own action is not evidence — check the
   files afterwards).
2. Configure git (global on the runtime host):
   ```bash
   git config --global user.name "peter-agent"
   git config --global user.email "peter+agent@chainlayer.io"
   git config --global user.signingkey "/home/<user>/.ssh/peter_agent_signing.pub"
   git config --global commit.gpgsign true
   git config --global gpg.format ssh
   ```
3. Register the public half on the GitLab service account **as a signing key
   only**: `POST /user/keys` with `usage_type: signing` — not
   `auth_and_signing`, so a leaked copy can sign but never push. Read the key
   back afterwards to confirm `usage_type` rather than assuming.
4. Add the public half to `~/.ssh/allowed_signers` keyed by the agent identity:
   ```
   peter+agent@chainlayer.io ssh-ed25519 <public half> peter-agent commit signing key
   ```

**Verifying — local is not enough.** A local `%G?` of `G` only proves the host's
`allowed_signers` agrees with itself. The real check is against GitLab's
commit-signature endpoint (`/projects/:id/repository/commits/:sha/signature`)
reporting `verification_status: verified`, which confirms both the signature and
that GitLab attributes the commit to `peter-agent`.

## Step 4 — GitLab MR

Two steps, because push options don't support newlines:

```bash
git push -u origin <branch>
GITLAB_TOKEN="$(OP_SERVICE_ACCOUNT_TOKEN="$(cat ~/.config/op/service-account-token)" \
  op read 'op://Agent Peter/gitlab/password')" \
  glab mr create --fill --title "<type>: <title>" --description "$(cat <<'EOF'
## Summary
<1-2 sentences>

## Linked task
Closes OPS-XXXX

## Changes
- <bullets>

## Impact
<scope and risk: what's affected, what's not, required actions>

## Security impact
<mandatory — see below. Never blank, never a bare "N/A".>

---
Claude <model>
EOF
)"
```

### `## Security impact` is mandatory on every MR

**Every MR carries this section, including chores and dependency bumps** — a
version bump *is* a supply-chain change, and "it's only a config file" is how
an exposed admin namespace or a `curl | sh` on every deploy gets shipped
without anyone weighing it.

Answer against these, and only the ones that apply:

- **Attack surface** — new or removed listeners, ports, routes, RPC namespaces,
  published container ports, anything reachable that was not before.
- **Privileges** — anything running as root, new `sudo`/capabilities, broadened
  IAM or RBAC, a service account gaining scope.
- **Secrets and credentials** — new secrets, a credential moving or gaining a
  second home on disk, tokens in argv or logs, rotation implications.
- **Data exposure** — logs or artefacts that could carry sensitive values,
  paths or internal topology committed to a repo.
- **Supply chain** — new or bumped third-party code, unpinned versions, remote
  scripts executed during deploy, registry or mirror changes.
- **Auth and network paths** — authentication or authorisation logic, firewall
  or ACL rules, tailnet/VPN reachability.

**"None" is a valid answer, but only with its reason.** An unreasoned "None"
is worth exactly as much as leaving the section out, so write
*"None — config-only; no new network paths, credentials or privileges"*, not
*"None"*. If a reviewer still has to ask "what's the security impact?", the
section failed.

Say so plainly when the impact is **negative**: an MR that *reduces* exposure
is the best kind, and stating it is how the reduction gets credited and
verified rather than assumed.

**The MR author is the token `glab` authenticates with — and that token is
`peter-agent`, resolved from 1Password at point of use.** Never run
`glab auth login --token`: that would write the PAT into glab's config file,
giving the credential a second home on disk outside 1Password — exactly the
outcome the point-of-use pattern exists to prevent. `glab` honours the
`GITLAB_TOKEN` env var, so the inline resolution above is the whole setup —
there is no stored credential. If a `glab` auth failure tempts you to reach
for `glab auth login`, don't — resolve the token at point of use as above.

Verify **who** it authenticates as, not merely that a call succeeds:

```bash
GITLAB_TOKEN="$(OP_SERVICE_ACCOUNT_TOKEN="$(cat ~/.config/op/service-account-token)" \
  op read 'op://Agent Peter/gitlab/password')" glab api user
# → username: peter-agent  (NOT tyrion70)
```

**MR author vs commit identity.** On an agent runtime these now agree:
commits are signed with the agent's own key (see "Wiring a host to sign as the
agent" above) and the MR is created as `peter-agent`, so author, signature,
pusher and MR author all say `peter-agent`. On Peter's own machines commits
carry his identity while MRs are still authored by `peter-agent` — fine for the
approval gate (`merge_requests_author_approval` keys on the MR author), but
visibly inconsistent unless you know it's deliberate.

**`Closes OPS-XXXX` is for traceability only — do not rely on it to auto-close
the Linear issue.** The GitLab↔Linear magic-word integration is not reliable.
Always include it (or `Refs` for partial work), but you must also explicitly
close the Linear issue via MCP after the MR merges (see "After the MR exists").

## Approval gates — never self-approve (human-only)

If an MR carries a **required-approval gate** (a GitLab approval rule /
required approver), an agent must **not** approve it — not its own MR, and not
another agent's (no "cross-approval"). The gate exists to enforce a
second-party **code review**, and no agent stands in for that.

- **Route the approval to a human via the Tech Lead.** A human clicking
  **Approve** in GitLab — or explicitly telling you "merge it" — satisfies the
  gate. Nothing an agent does can.
- **A verbal go-live "go" (or "go, direct") authorizes the _deploy_, not the
  code-review gate.** It does not let you approve your own or another agent's
  MR, and it does not let you bypass a required approver. If a go-live is
  blocked only on the approval, surface that to the Tech Lead and set the
  issue `blocked` for Peter — do **not** click approve yourself.

(Set after CHA-719, where a fleet agent self-approved a required-approval MR
under a verbal "Go, direct". Codified in CHA-779.)

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

## GitLab PAT — rotation

The token that authors MRs is **`peter-agent`**, stored in 1Password at
`op://Agent Peter/gitlab/password` (a SECURE_NOTE; the token is its concealed
`password` field). It carries both the `api` scope and `self_rotate`, so the
agent can rotate it without human involvement — no more dead-token escalations
blocking MRs.

**What rotation is — and is not.** A token with `api` scope can rotate itself
indefinitely, so annual expiry is a guard against *neglect*, not against the
holder. If you ever want expiry to bind the credential itself, the rotation has
to be performed by something other than the token's own authority. As it stands,
rotation is a maintenance act: do it proactively (near-expiry or scheduled), not
as a post-401 recovery.

**Proactive rotation (while the token is still valid):**

```bash
# 1. Read the current token from 1Password at point of use
OLD_TOKEN=$(OP_SERVICE_ACCOUNT_TOKEN="$(cat ~/.config/op/service-account-token)" \
  op read 'op://Agent Peter/gitlab/password')

# 2. Rotate — returns a new token, revokes the old one
NEW_TOKEN=$(curl -s -X POST https://gitlab.com/api/v4/personal_access_tokens/self/rotate \
  -H "PRIVATE-TOKEN: $OLD_TOKEN" | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")

# 3. Write the new token back into the 1Password item's password field.
#    `op item edit` assignment arguments are visible in argv, so put the
#    value in a template file instead (same gitignore discipline as the
#    bitwarden skill's temp files).
umask 077
OP_SERVICE_ACCOUNT_TOKEN="$(cat ~/.config/op/service-account-token)" \
  op item get 'op://Agent Peter/gitlab' --format json > /tmp/op-gitlab-item.json
python3 -c "
import json
d = json.load(open('/tmp/op-gitlab-item.json'))
for f in d.get('fields', []):
    if f.get('id') == 'password' or f.get('purpose') == 'PASSWORD':
        f['value'] = '$NEW_TOKEN'
print(json.dumps(d))
" > /tmp/op-gitlab-new.json
OP_SERVICE_ACCOUNT_TOKEN="$(cat ~/.config/op/service-account-token)" \
  op item edit 'op://Agent Peter/gitlab' --template /tmp/op-gitlab-new.json
rm -f /tmp/op-gitlab-item.json /tmp/op-gitlab-new.json
```

⚠️ **Caveat — only works while the token is still valid.** A fully-expired
token returns 401 and cannot rotate itself. Rotate **proactively** (near-expiry
or scheduled), not as a post-401 recovery. A hard-expired token still needs a
human to re-issue via the GitLab UI, then the new value written to 1Password.

> **Follow-up:** a scheduled Multica autopilot that rotates the token before
> expiry would eliminate the human-in-loop entirely. Not implemented yet —
> the agent-driven path above is the current approach.

## When to ask the user (explicit list)

- Remote is not `gitlab.com/chainlayer` (and not `github.com/tyrion70`, which
  is the `git-pr` skill's job).
- Any force-push, push directly to `main`/protected branches, or history rewrite.
- Closing/merging someone else's MR, or deleting branches you didn't create.
- An MR carries a **required-approval gate** — never self-approve or
  cross-approve; route to a human via the Tech Lead (see "Approval gates" above).
- The user wants to skip the Linear issue (confirm once, note it in the MR).
