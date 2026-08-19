---
name: 1password
description: Read secrets from the 1Password vault via the `op` CLI. Use whenever a task requires a credential that now lives in 1Password (currently the new GitLab PAT) instead of Bitwarden. During the migration BOTH vaults hold real secrets — if a credential isn't found in Bitwarden, check 1Password before concluding it doesn't exist.
---

# 1Password access

1Password is the successor vault for company secrets, migrating in from
Bitwarden/Vaultwarden. **During the migration both vaults hold real secrets** —
a credential missing from one vault may simply live in the other. Check both
before concluding a credential doesn't exist.

## Auth — the service-account token, read at point of use

The `op` CLI authenticates with a service-account token at
`~/.config/op/service-account-token` (mode 0600, owned by the user agents run
as). Read it **at point of use**, never as a session-wide export:

```bash
OP_SERVICE_ACCOUNT_TOKEN="$(cat ~/.config/op/service-account-token)" op read "op://<VAULT>/<ITEM>/<FIELD>"
```

A session-wide `export OP_SERVICE_ACCOUNT_TOKEN=...` puts the token in the
environment of every process and child process for the whole session — far more
places to leak from than one file read at the moment it's needed. Prefer the
inline form above.

**Never echo, print, log, or paste the token** — it is the bootstrap secret
that unlocks the vault holding the GitLab PAT, so it can't itself live in a
vault. It's on the never-read list in `claude-config/chainlayer/CLAUDE.md`
beside `.credentials.json` and `tailscaled.state`. Agents may *use* it through
`op`; they must never print it.

## What lives where (migration in progress)

| Vault | Holds |
|---|---|
| **1Password** (`op`) | The new GitLab PAT (`peter-agent` token). |
| **Bitwarden** (`bw`) | Everything else for now: SSH keys, the old `ChainLayer · GitLab — group PAT`, Tailscale OAuth client + pre-auth key, etc. |

This list is a snapshot; the migration is one-way (Bitwarden → 1Password).
When you learn a credential has moved, update this table in the skill and say so
in your result comment — otherwise the next agent looks in the wrong vault.

## Vault and item names

**The 1Password vault name and item names are NOT yet recorded in this skill.**
Do not invent them — a skill that names the wrong vault is worse than one that
says "ask". The token can list what it can see:

```bash
OP_SERVICE_ACCOUNT_TOKEN="$(cat ~/.config/op/service-account-token)" op vault list
OP_SERVICE_ACCOUNT_TOKEN="$(cat ~/.config/op/service-account-token)" op item list --vault "<VAULT>"
```

If that doesn't reveal what you need, **ask Peter** for the exact
`op://<VAULT>/<ITEM>/<FIELD>` reference. As of this skill's writing, the vault
is known to hold at least the new GitLab PAT.

## Don'ts

1. **Don't export `OP_SERVICE_ACCOUNT_TOKEN` for the session** — read it inline at point of use.
2. **Don't echo, print, log, or paste the token** or any secret value.
3. **Don't conclude a credential is missing from one vault** without checking the other during migration.
4. **Don't invent vault or item names** — use `op vault list` or ask.
5. **Don't commit the token or any secret** to a repo; it lives only at `~/.config/op/service-account-token` and in 1Password itself.
