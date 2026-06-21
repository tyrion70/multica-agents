---
name: ssh
description: Peter's SSH key setup — which key does what (auth/login vs signing), how to reach private homelab vs company hosts, git auth to GitHub/GitLab, and SSH commit signing. Use whenever SSHing to a machine, cloning/pushing over SSH, configuring git auth or commit signing, or wiring keys onto a new host. Keys live in the vault `shared` folder.
---

# SSH keys & access

Two purpose-built ed25519 keys (plus YubiKey FIDO2 fallbacks). Keep their
roles separate — auth/login is one key, signing is another.

| Key | Role | Used for |
|---|---|---|
| `~/.ssh/id_ed25519_peter` (`peter@chainlayer`) | **auth + login** | SSH login to machines (private homelab + company), and git auth to GitHub (tyrion70) + GitLab (gitlab.com/chainlayer) |
| `~/.ssh/id_ed25519_signing` (`git-signing`) | **signing** | SSH-format git commit/tag signing. (Also accepted for GitHub/GitLab auth, but its job is signing.) |
| `~/.ssh/id_ed25519_sk_yk_*` | fallback | FIDO2 YubiKey keys for other/ad-hoc hosts (PIN-gated) |

Both git keys are registered on GitHub **and** GitLab. Confirmed working:
`id_ed25519_peter` → GitHub/GitLab auth + machine login (private + company);
`id_ed25519_signing` → produces a Good commit signature.

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

Host github.com gitlab.com
    IdentityFile ~/.ssh/id_ed25519_peter
    IdentitiesOnly yes
```

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
