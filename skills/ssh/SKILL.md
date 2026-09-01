---
name: ssh
description: SSH keys and access — JIT first. Reaching a host now means requesting access through JIT (https://jit.java-moth.ts.net/), not using a standing key: humans use the web UI with a YubiKey touch, agents use POST /agent/grant. Also covers the git-auth and commit-signing keys (GitHub auth, SSH-format signing) and wiring keys onto a new host. Use whenever SSHing to a machine, cloning/pushing over SSH, configuring git auth or commit signing, or wiring keys onto a new host.
---

# SSH keys & access

The way to reach a machine has changed: **request access through JIT rather
than logging in with a standing key.** The standing `id_ed25519_peter` key still
exists on some hosts, but JIT is the mechanism that replaces it and it is being
removed. This skill leads with the JIT path because that is what works today;
the standing-key path is documented below for what remains, marked for removal.

## Reaching machines — request access through JIT

JIT (just-in-time) grants temporary SSH access to a target host. There are two
paths, and **getting the wrong one looks like JIT is broken** — they differ by
who is calling.

### Humans — the web UI

Open **https://jit.java-moth.ts.net/**, request access to the target host, and
approve with a **YubiKey touch**. The touch is the identity — a grant is
attributable to a specific security key, and grants expire on their own.

### Agents — POST /agent/grant

**Agents cannot use the web UI.** `tailscale serve` does not inject identity
headers for **tagged** devices, so a tagged agent gets **403 on the UI — that is
expected, not a fault.** An agent reaches a host through the agent path:

```
POST /agent/grant
Content-Type: application/json

{"target": "<host>", "reason": "<why>", "seconds": <optional>}
```

The caller must be a tagged agent device (one of the agent identity tags) and
must send a real `reason` — the criteria service decides based on it. A missing
`reason` is refused before any criteria call.

**Then connect over the tailnet FQDN — not the bare hostname.** The grant
authorises; it does not connect, and the two failures look identical. On an
agent runtime `/etc/resolv.conf` reads `search tyrion.eu java-moth.ts.net`, so
bare `monitoring` resolves to `monitoring.tyrion.eu` (the LAN address), reaches
the host's **own `sshd`**, and returns `Permission denied (publickey)` even
though the grant succeeded:

```bash
ssh peter@monitoring.java-moth.ts.net         # USE THIS — works from every client
tailscale ssh peter@monitoring                # fine where the subcommand exists
ssh peter@monitoring                          # WRONG HOST: 192.168.18.232, plain sshd
```

Only the tailnet address is answered by `tailscaled`, and only `tailscaled`
enforces the ACL the grant writes. **`Permission denied (publickey)` right after
a successful grant is a routing symptom, not an authorisation one** — check the
address in `ssh -v` before re-requesting. Do not go hunting for the right key;
no key fixes it (this cost real time on CHA-1088, where `id_ed25519_peter` is
not even present on `multica-02`).

**Give the FQDN, not `tailscale ssh`, when telling a human how to connect.**
`tailscale ssh` can't misroute, so it is a fine habit on a runtime that has it —
but the macOS **App Store and TestFlight builds ship without the subcommand**
(`The 'tailscale ssh' subcommand is not available on macOS builds distributed
through the App Store or TestFlight`), so a Mac reader following that advice is
stuck. The FQDN works everywhere; recommend it by default.

**There is no release endpoint.** `POST /agent/release` is a 404, and no route
releases a tier-1 SSH grant — the panel's "Release now" only covers namespace
and cluster-admin grants. An agent grant runs for its full window, so **size
`seconds` to the job** instead of planning to hand it back.

### What is requestable today

The agent allow-list is **not** the discovered host set. Measured live
2026-09-01 by actually calling `/agent/grant`, the refusal names it in full:

> `'<host>' is not available to agents. Agents are limited to an explicit list
> (monitoring, claude-workstation-01, claude-readonly-01, multica-02,
> rag-refresh) while the criteria service still approves every request; humans
> get the discovered set.`

So agents get those **five** hosts; humans get everything JIT discovers. A
request for anything else returns **HTTP 400** — **that refusal is correct
behaviour, not a broken system.** Don't read it as JIT failing.

**Chain-node and other fleet hosts (`*.chosts.io`) are NOT agent-requestable.**
An agent needing a node's `journalctl` has to ask a human; there is no agent
path to those boxes today.

**Test, don't infer.** This list changes and this file will go stale — one
`POST /agent/grant` answers the question in a second, and the refusal message
names the current list for free. Do not conclude a host is unreachable from
reading this section; that mistake cost a wrong escalation on CHA-1108, where
the nodes were healthy all along and the agent reported them dead rather than
getting the journal.

### The criteria service refuses on its own axes

Being on the allow-list is necessary, not sufficient. A permitted target still
gets **HTTP 403** if the criteria service is unsatisfied, and its codes are
terse. Both of these were returned for `monitoring` on 2026-09-01:

| Response | Meaning |
|---|---|
| `criteria not met: NOK: NO-TICKET-ID` | the `reason` carried no ticket id the service recognised |
| `criteria not met: NOK: NO-NETWORK-SCOPE` | reason had a ticket id but no accepted network scope |

A bare prose `reason` is not enough. **HTTP 400 = wrong target; HTTP 403 =
right target, insufficient reason** — the two look alike in a terminal and mean
completely different things, so read the status code before rewriting the
request.

### `jit` itself is never requestable

`jit` is the approver and is **deliberately not a target**. It is absent from
`JITSSH_TARGETS` by design; do not expect to request access to it.

## Legacy standing access (being removed)

The standing key `id_ed25519_peter` still works on hosts where it is installed,
and is **being removed** — do not treat it as the normal way in. Where it
remains:

- **Private homelab** (Proxmox VMs): `192.168.16/17/18/19.x`, user `peter` or
  `root`, **port 22**, key `id_ed25519_peter`. See the `homelab` skill.
- **Company hosts**: `*.chosts.io`, user `peter`, **port 2822**, key
  `id_ed25519_peter`. Not reachable from the laptop's plain network the same
  way — mind the non-standard port.

Plan all host access as JIT requests; use the standing key only for hosts not
yet covered by a target.

## The keys

Two purpose-built ed25519 keys (plus YubiKey FIDO2 fallbacks). Keep their
roles separate — auth/login is one key, signing is another.

| Key | Role | Used for |
|---|---|---|
| `~/.ssh/id_ed25519_peter` (`peter@chainlayer`) | **auth + login** | Git auth to **GitHub** (tyrion70). Host login via this key is legacy and being removed — reach machines through JIT instead. |
| `~/.ssh/id_ed25519_signing` (`git-signing`) | **signing** (+ GitLab auth) | SSH-format git commit/tag signing. **Also the key GitLab accepts for auth** (see note below). |
| `~/.ssh/id_ed25519_sk_yk_*` | fallback | FIDO2 YubiKey keys for other/ad-hoc hosts (PIN-gated) |

Confirmed working (multica-02 runtime, 2026-06-29):
- **GitHub** auth → `id_ed25519_peter` (`ssh -T git@github.com` → "Hi tyrion70!").
- **GitLab** auth → `id_ed25519_signing` only. `id_ed25519_peter` is **rejected**
  by gitlab.com (`Permission denied (publickey)`) — it is not (or no longer)
  registered there. Don't assume the auth key works for both forges.
- `id_ed25519_signing` → produces a Good commit signature.

`~/.ssh/config` should carry the git-auth mappings so you don't pass flags by
hand:

```
Host github.com
    IdentityFile ~/.ssh/id_ed25519_peter
    IdentitiesOnly yes

# GitLab accepts the signing key for auth, NOT id_ed25519_peter.
Host gitlab.com
    IdentityFile ~/.ssh/id_ed25519_signing
    IdentitiesOnly yes
```

## Git over SSO-enforced GitLab groups (chainlayer)

The `gitlab.com/chainlayer` group enforces **SAML SSO on git transport**. This
bites hard and has caught us before, so know it up front:

- A fresh `git clone`/`git fetch` of any `chainlayer/*` repo over **SSH _or_
  HTTPS** fails with `remote: Cannot find valid SSO session. Please login via
  your group's SSO at …` (HTTP 403) **unless there is an active browser SSO
  session** for the account behind the credential. A valid SSH key or a valid
  token is **not** enough on its own.
- This applies to **every credential available headlessly**: the SSH keys, the
  revoked group PAT (`ChainLayer · GitLab — group PAT`), and even
  `multica repo checkout` — they all resolve to the same SSO-gated GitLab
  account. An agent cannot complete the browser SAML flow, so it cannot
  establish the session itself.
- `multica repo checkout` only succeeds for repos that were **already synced**
  into the workspace's bare mirrors while a session was live. Adding a new repo
  (`multica repo add`) and then checking it out triggers a fresh fetch → SSO
  403. So "SSH-clone any repo regardless of workspace config" is **false** for
  this group.
- **What still works headlessly:** the GitLab **REST API** with the
  `peter-agent` token from 1Password, resolved at point of use (e.g.
  `GITLAB_TOKEN="$(OP_SERVICE_ACCOUNT_TOKEN="$(cat ~/.config/op/service-account-token)" \
  op read 'op://Agent Peter/gitlab/password')" glab api ...`).
  Use it to *read* source or act on a repo you can't clone. The `peter-agent`
  token is the current credential; the old group PAT is revoked.
- **To actually clone/push** a `chainlayer/*` repo from an agent runtime, a human
  must refresh the group's SSO session for the workspace credential (or the repo
  must be pre-synced). Surface this as a blocker rather than burning time on key
  permutations — none of them defeat SSO.

**Rule (Peter):** IF you encounter `Cannot find valid SSO session`, prompt Peter
with the precise url so he can login UNLESS you have a different way to
circumvent the SSO issue.

The "precise url" is the `https://gitlab.com/groups/chainlayer/-/saml/sso?token=…`
link printed in the `remote:` error — surface that exact URL to Peter, don't
paraphrase it. (A "different way to circumvent" means something that gets the
work done without his login, e.g. reading the file you need via the REST API
above — not another SSH-key/PAT permutation, which won't work.)

(GitHub `tyrion70/*` repos have no such enforcement — clone/push works with
`id_ed25519_peter` directly.)

## Git commit signing

SSH-format signing with the dedicated signing key:

```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519_signing.pub
git config --global commit.gpgsign true
# verify locally: add your pubkey to an allowed-signers file
git config --global gpg.ssh.allowedSignersFile ~/.ssh/allowed_signers
#   ~/.ssh/allowed_signers:  peter@chainlayer.io <contents of id_ed25519_signing.pub>
```

`git log --show-signature` should report `Good "git" signature for
peter@chainlayer.io`. Add the signing key to GitHub/GitLab as a **signing**
key (separate from the auth key) for the green "Verified" badge.

## Keys in the vault

Both private keys are stored in the Bitwarden **`shared`** folder (see the
`bitwarden` skill) as file-type items, so any context (private or company)
can use them:

- `ssh/id_ed25519_peter`   → `~/.ssh/id_ed25519_peter` (mode 600)
- `ssh/id_ed25519_signing` → `~/.ssh/id_ed25519_signing` (mode 600)

To wire a fresh host: write each key to its path (`chmod 600`), drop the
`~/.ssh/config` git-auth mappings above, and `chmod 644` the regenerated `.pub`
(`ssh-keygen -y -f <key> > <key>.pub`). `id_ed25519_peter` remains for git auth
to GitHub; host access is through JIT, not this key.

## Don'ts

- Don't use the signing key as the primary auth identity in config, or the
  auth key for signing — keep the roles split.
- Don't commit private keys to git; they live in the vault and `~/.ssh` only.
- Don't forget `IdentitiesOnly yes` — without it SSH may offer the YubiKey
  keys first and trigger spurious PIN prompts.
