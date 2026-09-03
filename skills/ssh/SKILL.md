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

**Release the grant when you are done.**

```
POST /agent/release
Content-Type: application/json

{"target": "<host>"}
```

`target` is **required** — releasing every grant at once is deliberately not
implicit, so an agent holding several does not lose the rest to an omitted
field. There is no criteria call on this route: giving up privilege is not
privileged. The response reports what is `still_open`.

This skill previously said the endpoint was a 404 and that a grant runs for its
full window. **That was wrong**, and it is why grants sit unreleased. Size
`seconds` to the job *and* hand it back.

**Re-requesting the same target RESETS the window — it does not add to it.**
Ask for at least what remains and you extend; ask for less and **you shorten
your own access**, which is the case you walk into by politely requesting a
small window on a target you already hold. If you only need a little longer,
ask for the whole remaining time plus the extra, not the extra.

> **Endpoint behaviour is documented in the approver's own README**, and that is
> the source: [`jit-ssh/README.md`](https://gitlab.com/chainlayer/infrastructure/jit-ssh/-/blob/main/README.md)
> — see *Concurrent grants, one per (principal, target)* for the expiry
> arithmetic and *POST /agent/release* for the contract. Operational guidance
> lives here; the facts live there. This skill has been wrong about JIT
> behaviour before precisely because it kept a **copy** of it.

### What is requestable

**Don't expect a fixed list here.** The target set is configuration, and it has
moved: humans get a discovered set (every tailnet host with `sshEnabled`),
agents get an explicit list plus tag-based selection, and the two are separate
knobs on purpose. A number written down in this skill goes stale silently, which
is the failure this section used to be.

Ask the service instead — the approver's startup line and `GET /version` report
what it actually loaded, and
[`jit-ssh/README.md`](https://gitlab.com/chainlayer/infrastructure/jit-ssh/-/blob/main/README.md)
(*SSH targets: discovery for humans, a list for agents*) explains the split.

What to *do* about a refusal: **"not a JIT-eligible target" is correct behaviour,
not a broken system.** For an agent, `TARGET-OUT-OF-SCOPE` means the host is
reachable in principle but not in scope for your ticket — a different answer
again, and neither is JIT failing.

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

## Git against `gitlab.com/chainlayer` from an agent runtime

**Clone, fetch and push all work headlessly. Don't plan around SSO.**

This section used to say the group enforces SAML SSO on git transport and that
neither a key nor a token is enough without a browser session — so an agent
should surface a blocker rather than try. That is **wrong for the path a company
runtime actually uses**, and it cost real time: work was queued as blocked on
Peter that the runtime could have done itself.

**What is true, measured on a Multica company runtime:**

- Git transport goes over **HTTPS with the `peter-agent` PAT**, not over SSH.
  `~/.gitconfig` carries `url.https://gitlab.com/.insteadOf = git@gitlab.com:`,
  so even a `git@gitlab.com:…` remote is rewritten to HTTPS, and
  `credential."https://gitlab.com".helper` is
  `gitlab-agent-credential-helper`, which resolves the PAT from 1Password at
  point of use. Nothing to configure — clone and push normally.
- **No browser SSO session is involved** in that path. `git ls-remote` returns
  refs and pushes land; this has carried eight merge requests.
- The keys named in the table above (`id_ed25519_peter`,
  `id_ed25519_signing`) are **not installed on a company runtime** — the
  signing key here is `~/.ssh/peter_agent_signing`. So don't debug a GitLab git
  failure by hunting for the right key: the credential is a PAT and the
  transport is HTTPS.
- The **REST API** works the same way (`glab` with `GITLAB_TOKEN`, or
  `PRIVATE-TOKEN`) — see the field trap below, which is the thing that actually
  goes wrong.

**If you DO see `Cannot find valid SSO session`** — surface the exact
`https://gitlab.com/groups/chainlayer/-/saml/sso?token=…` URL from the
`remote:` output to Peter, verbatim, so he can log in. Don't paraphrase it, and
don't try key or PAT permutations: none of them defeat SSO. But treat it as an
**unexpected** condition worth reporting rather than the normal state of
affairs, because on this runtime it is not.

(GitHub `tyrion70/*` repos have no such enforcement either; git auth there goes
through `gh auth git-credential`.)

### The GitLab PAT is in the `password` field — and the wrong field fails as a 404

The item is `op://Agent Peter/gitlab`, and it has exactly two fields:
`notesPlain` and `password`. **The PAT is in `password`.** There is no `token`
field, however much the name suggests one:

```bash
export OP_SERVICE_ACCOUNT_TOKEN="$(cat ~/.config/op/service-account-token)"
GITLAB_TOKEN="$(op read 'op://Agent Peter/gitlab/password')"   # CORRECT

op read 'op://Agent Peter/gitlab/token'                        # errors
op item get gitlab --vault 'Agent Peter' --fields label=token  # errors:
#   [ERROR] "token" isn't a field in the "gitlab" item
```

**The trap is that the error becomes an empty string.** `op` writes it to
stderr and exits non-zero, so `X="$(op read …/token)"` leaves `X` **empty**
while the command "succeeded" as far as the next line is concerned — and then:

| what you sent | GitLab answers |
|---|---|
| empty `PRIVATE-TOKEN` | **`404 Project Not Found`** |
| a wrong non-empty token | `401 Unauthorized` |

So the symptom of *sending no credential at all* is a **404 that reads like the
project doesn't exist or you named it wrong**, and you go looking for a typo in
the path. **404 means you sent nothing; 401 means you sent something wrong.**
That distinction cost three MRs' worth of confusion.

Check the length before you use it, so the failure lands where the mistake is:

```bash
[ -n "$GITLAB_TOKEN" ] || { echo "no PAT — check the FIELD NAME, not the path"; exit 1; }
```

Never echo the value; check that it is non-empty and that it starts with
`glpat-`.

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
