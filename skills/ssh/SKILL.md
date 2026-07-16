---
name: ssh
description: Peter's SSH key setup — which key does what (auth/login vs signing), how to reach private homelab vs company hosts, git auth to GitHub/GitLab, and SSH commit signing. Use whenever SSHing to a machine, cloning/pushing over SSH, configuring git auth or commit signing, or wiring keys onto a new host. Keys live in the vault `shared` folder.
---

# SSH keys & access

Two purpose-built ed25519 keys (plus YubiKey FIDO2 fallbacks). Keep their
roles separate — auth/login is one key, signing is another.

| Key | Role | Used for |
|---|---|---|
| `~/.ssh/id_ed25519_peter` (`peter@chainlayer`) | **auth + login** | SSH login to machines (private homelab + company), and git auth to **GitHub** (tyrion70) |
| `~/.ssh/id_ed25519_signing` (`git-signing`) | **signing** (+ GitLab auth) | SSH-format git commit/tag signing. **Also the key GitLab accepts for auth** (see note below). |
| `~/.ssh/id_ed25519_sk_yk_*` | fallback | FIDO2 YubiKey keys for other/ad-hoc hosts (PIN-gated) |

Confirmed working (multica-02 runtime, 2026-06-29):
- **GitHub** auth → `id_ed25519_peter` (`ssh -T git@github.com` → "Hi tyrion70!").
- **GitLab** auth → `id_ed25519_signing` only. `id_ed25519_peter` is **rejected**
  by gitlab.com (`Permission denied (publickey)`) — it is not (or no longer)
  registered there. Don't assume the auth key works for both forges.
- `id_ed25519_signing` → produces a Good commit signature.

> **GitLab auth ≠ GitLab repo access for the `chainlayer` group.** Authenticating
> is necessary but not sufficient — the group enforces SAML SSO on git transport.
> See "Git over SSO-enforced GitLab groups" below before trying to clone/fetch a
> `gitlab.com/chainlayer/*` repo.

## Reaching machines

- **Private homelab** (Proxmox VMs): `192.168.16/17/18/19.x`, user `peter` or
  `root`, **port 22**, key `id_ed25519_peter`. See the `homelab` skill.
- **Company hosts**: `*.chosts.io`, user `peter`, **port 2822**, key
  `id_ed25519_peter`. Not reachable from the laptop's plain network the same
  way — mind the non-standard port.

`~/.ssh/config` should carry these so you don't pass flags by hand:

```
Host *.chosts.io
    User peter
    Port 2822
    IdentityFile ~/.ssh/id_ed25519_peter
    IdentitiesOnly yes

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
  group PAT is **not** enough on its own.
- This applies to **every credential available headlessly**: the SSH keys, the
  vault group PAT (`ChainLayer · GitLab — group PAT`), and even
  `multica repo checkout` — they all resolve to the same SSO-gated GitLab
  account. An agent cannot complete the browser SAML flow, so it cannot
  establish the session itself.
- `multica repo checkout` only succeeds for repos that were **already synced**
  into the workspace's bare mirrors while a session was live. Adding a new repo
  (`multica repo add`) and then checking it out triggers a fresh fetch → SSO
  403. So "SSH-clone any repo regardless of workspace config" is **false** for
  this group.
- **What still works headlessly:** the GitLab **REST API** with the group PAT
  (e.g. `GET /projects/:id/repository/files/<path>/raw`). Use it to *read*
  source when you only need to inspect a repo you can't clone.
- **The group PAT has `self_rotate` — keep it alive yourself.** The PAT
  (`ChainLayer · GitLab — group PAT`, Bitwarden `company` folder) carries the
  `self_rotate` scope. Rotate it with
  `POST https://gitlab.com/api/v4/personal_access_tokens/self/rotate` using the
  current token as `PRIVATE-TOKEN`, then **write the new token back** into
  Bitwarden (the item is a SecureNote; the token is in its hidden `PAT` field)
  and `bw sync`. See the **`git-mr`** skill for the full procedure and the
  important caveat (only works while still valid — rotate proactively).
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
`~/.ssh/config` snippet above, and `chmod 644` the regenerated `.pub`
(`ssh-keygen -y -f <key> > <key>.pub`).

## Don'ts

- Don't use the signing key as the primary auth identity in config, or the
  auth key for signing — keep the roles split.
- Don't commit private keys to git; they live in the vault and `~/.ssh` only.
- Don't forget `IdentitiesOnly yes` — without it SSH may offer the YubiKey
  keys first and trigger spurious PIN prompts.
