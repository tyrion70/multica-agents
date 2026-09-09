---
name: ssh
description: SSH keys and access — two policies, not one. COMPANY hosts (*.chosts.io, company runtimes, the company tailnet) are reached through JIT + Tailscale with no standing key on disk: humans use the web UI (https://jit.java-moth.ts.net/) with a YubiKey touch, agents use POST /agent/grant, and a 400 (wrong target) is a different answer from a 403 — which may be an insufficient reason, or one of two grant caps (both default 2, neither daily, both escalatable). PRIVATE/LAN machines of Peter's own are reached with a local key on multica-01, which is supported rather than legacy. Also covers git auth to GitHub and GitLab from a host — where the url.insteadOf rewrite, not the key, decides whether your token is used — SSH-format commit signing, and what to do when a key needs recreating (the keys are NOT in the vault). Use whenever SSHing to a machine, cloning/pushing over SSH, hitting "Permission denied (publickey)", configuring git auth or commit signing, or wiring keys onto a new host.
---

# SSH keys & access

## Read this first: company and private are two different policies

This skill covers both, and they do not have the same answer. Getting the
boundary wrong sends you looking for a key that should not exist, or hunting for
a JIT grant on a machine that never had one.

| | **Company hosts** | **Private / LAN — Peter's own machines** |
|---|---|---|
| Examples | `*.chosts.io`, company runtimes (multica-02), anything on the company tailnet | homelab Proxmox VMs, `192.168.16/17/18/19.x`, and multica-01 as the client |
| How you get in | **JIT + Tailscale, every time.** Request a grant, connect over the tailnet FQDN, release when done. | A **local key** is fine — `~/.ssh/id_ed25519_peter` on multica-01. |
| Standing key on disk | **No.** A key on disk is not the company access path. Its **absence is correct**, not a gap to fill. | **Yes**, deliberately, and expected. |

**Peter's ruling, 2026-09-03**, and it settles a question this skill used to
answer with one policy for everything: *company → JIT + Tailscale; private →
a local key on multica-01 for LAN machines.*

Two consequences worth stating, because both have cost time:

- **On a company host, "I can't find the key" is not a problem to solve.**
  `id_ed25519_peter` is not installed on multica-02 and is not supposed to be.
  Do not treat its absence as the reason a connection failed (that is what
  happened on CHA-1088) and do not restore it from anywhere.
- **On multica-01, the local key is not legacy.** It is the intended path for
  Peter's own LAN machines, and it is not queued for removal. What is being
  removed is *standing key access to company hosts*.

Everything below is the detail. The JIT path comes first because it is the
company path and the one most readers need.

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
headers for **tagged** devices. Be precise about what that does and does not
do, because the imprecise version has now propagated into a repo README: the
**entry page still loads** — it is the identity-gated endpoints behind it that
refuse. Measured from `multica-02` (`tag:peter-agent`), 2026-09-07:

```
GET /             → 200      # the page serves
GET /targets      → 403      # the actions behind it do not
GET /grants       → 403
```

**A 403 on those is expected, not a fault**, and a 200 on `/` is not evidence
that the UI will work for you. An agent reaches a host through the agent path:

```
POST /agent/grant
Content-Type: application/json

{"target": "<host>", "reason": "<why>", "seconds": <optional>}
```

The caller must be a tagged agent device (one of the agent identity tags) and
must send a real `reason` — the criteria service decides based on it. A missing
`reason` is refused before any criteria call.

**Then connect over the tailnet FQDN.** The grant authorises; it does not
connect, and the two failures look identical.

**Whether the bare hostname works depends on the host, so don't rely on it —
and don't assert it as the cause of a failure.** On an agent runtime
`/etc/resolv.conf` reads `search tyrion.eu java-moth.ts.net`, and **`tyrion.eu`
is searched first**. So a host with a LAN twin resolves to the LAN, and a host
without one falls through to the tailnet. Both measured on `multica-02`,
2026-09-07:

```bash
getent hosts monitoring              # 192.168.18.232  monitoring.tyrion.eu      ← LAN twin wins
getent hosts lens-main-rpc-1a-nl2v   # 100.94.41.60    …java-moth.ts.net         ← no twin, tailnet
```

```bash
ssh peter@monitoring.java-moth.ts.net         # USE THIS — unambiguous from every client
tailscale ssh peter@monitoring                # fine where the subcommand exists
ssh peter@monitoring                          # WRONG HOST: 192.168.18.232, plain sshd
ssh peter@lens-main-rpc-1a-nl2v               # happens to be right — no LAN twin to lose to
```

Use the FQDN because it is unambiguous, not because the bare name is always
wrong. Only the tailnet address is answered by `tailscaled`, and only
`tailscaled` enforces the ACL the grant writes.

**`Permission denied (publickey)` right after a successful grant CAN be a
routing symptom rather than an authorisation one** — check the address in
`ssh -v` before re-requesting, and do not go hunting for the right key on the
assumption that it is (no key fixes the routing case; this cost real time on
CHA-1088, where `id_ed25519_peter` is not even present on `multica-02`). But
**verify the address rather than asserting misrouting**: on a host with no LAN
twin the bare name already resolved correctly, so a denial there is something
else and the routing explanation will send you past it. The JIT service removed
this same misdirection from its own error text for exactly that reason.

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
privileged.

**What the response hands back is your whole footprint** — `hosts`, `units`,
`live_grants`, `grant_cap`, `at_cap` — the same fields `POST /agent/status`
returns, from the same builder so the two cannot disagree. Read it: it is how
you know whether you are clear of the concurrency cap (below), and releasing a
target you do not hold is **not** an error, because expired, already released
and never held are the same state.

Older approvers answer with `still_open` instead. **Its entries are Tailscale
device ids, not hostnames** (`nRboNNbsT221CNTRL`-shaped — a grant records the id
it was opened against). A device id you do not recognise in that list is
therefore *not* evidence of some foreign grant on your principal; it is a
target of yours in a vocabulary no other route uses. `POST /agent/status`
resolves it.

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
not a broken system** — it is a 400, and no `reason` will change it.

**There is no longer a "not in scope for your ticket" answer.** This paragraph
used to describe `TARGET-OUT-OF-SCOPE` as a third outcome; that rule was
**deleted** by decision 17, along with `NO-NETWORK-SCOPE` and
`AMBIGUOUS-NETWORK` — a resolving ticket is now sufficient on its own, with no
network label to match against a target. Do not craft a reason around it.

**Chain-node fleet hosts CAN be agent-requestable — this section said the
opposite until 2026-09-07, and that was wrong.** It read "*Chain-node and other
fleet hosts (`*.chosts.io`) are not agent-requestable... there is no agent path
to those boxes*". Measured from the `multica-02` runtime (`tag:peter-agent`) on
CHA-1244, against a live mainnet RPC node:

```bash
POST /agent/grant {"target":"lens-main-rpc-1a-nl2v","reason":"<ticket + scope>","seconds":300}
→ 200 {"ok": true, "principal": "peter-agent", "ssh_user": "peter", "capped": false}

ssh peter@lens-main-rpc-1a-nl2v.java-moth.ts.net    # connects; session is recorded
sudo -n docker ps                                    # works
```

No human in the loop, no approval step. So do **not** plan around needing a
human for a node's `journalctl`, and do not design a CI job, pipeline or
credential whose only purpose is to hold an SSH key you were told you could not
have.

**What is still true is the shape, not the verdict:** the agent target set is an
explicit list plus tag selection, it is configuration, and it moves. One node
being requestable today is not a promise about every host or about next month —
that inference is the same mistake in the other direction. Ask the service.

**Two failures, opposite directions, same root cause — believing this document
instead of the API:**

- **CHA-1108** — concluded from this section that nodes were unreachable and
  reported them dead. They were healthy the whole time; one grant would have
  fetched the journal.
- **CHA-1244** — accepted the "no agent path" line, and so specified a GitLab CI
  job to run a read-only diagnostic capture on a node an agent could simply SSH
  into. It reached a coded, QA-passed MR before the owner asked why the pipeline
  existed at all. It also meant a QA blocker ("unbounded write into `/` on a
  live box, real headroom unmeasurable") went two review rounds unresolved, when
  30 seconds of the access above showed `/tmp` was a dedicated 4 GB volume and
  journald held 369 MB.

**So: test, don't infer, and never escalate or design from reading this
section.** One `POST /agent/grant` answers "can I reach it" in a second, and a
refusal names the current list for free.

**Release the grant when you are done** — `POST /agent/release {"target": ...}`.
Both examples above were released (`still_open: []`).

**Note what a refusal does *not* mean:** the node being unreachable **from you**
is not evidence about the node.

### Read the status code: 400 is the wrong target, 403 is a criteria refusal

Being on the agent list is necessary, not sufficient — and the two refusals look
alike in a terminal while meaning completely different things:

| Status | Meaning | What to change |
|---|---|---|
| **400** | wrong target — the host is not agent-requestable | nothing about your reason will help; ask a human, or pick a target that is in scope |
| **403** | right target — the **criteria service** declined. Not necessarily your reason: it is also how both grant caps refuse | read the code in the body; the target is fine |

The criteria codes are terse, and the 403 is **not always a bad reason** — it
can equally be a cap you are sitting on, or a request now parked for a human.
Read the code, not the status:

| `criteria not met: NOK: …` | Meaning | What to do |
|---|---|---|
| `NO-TICKET-ID` | the `reason` carried no ticket id the service recognised | cite one — **or don't**: this refusal *escalates*, and it is the commonest one, so working a host with no ticket costs one human touch rather than being a wall |
| `MALFORMED-TICKET-ID`, `AMBIGUOUS-TICKET` | there is an id but it is unusable, or you cited two | **terminal** — fix it yourself; nobody is woken for a typo |
| `CONCURRENCY-CAP` | you hold too many live grants — see below | release one, or let the escalation be approved |
| `TICKET-BUDGET` | this ticket has already reached distinct targets — see below | new ticket, or let the escalation be approved |
| `ALWAYS-ESCALATE` | the name is on the deny list (`jit`, revenue-critical hosts) | wait for the touch; deny wins and outranks a perfect ticket |
| `TICKET-NOT-FOUND`, `TICKET-CLOSED`, `TICKET-LOOKUP-*` | the resolver's own verdict | **terminal** — an outage is not a decision, and parking it would bury the real requests |

**`NO-NETWORK-SCOPE` is not a rule any more.** It used to be the commonest
refusal, and the previous version of this section told you to supply "the
network scope you actually need". There is no such field to supply — see the
paragraph under *What is requestable*.

> **The code names are the service's to change** — read the response body rather
> than matching on remembered strings. The 400-vs-403 distinction is structural
> and will hold. The authoritative list is
> [`jit-ssh/README.md`](https://gitlab.com/chainlayer/infrastructure/jit-ssh/-/blob/main/README.md)
> (*Escalation — a refusal a human can say yes to*) and `jit_criteria.py`'s
> `ESCALATABLE` set, which is the only copy of it.

### Two caps, both defaulting to 2, and **neither of them daily**

A 403 is often not about your reason at all. Two counts bound how many systems
one agent can reach in sequence, they are checked **before** every way of saying
yes, and three of us guessed their semantics wrong from the error strings before
anyone read the source:

| | default | counts | refusal |
|---|---|---|---|
| `JITSSH_AGENT_GRANT_CAP` | **2** | live grants for one **person**, across both flows | `CONCURRENCY-CAP` |
| `JITSSH_AGENT_TICKET_BUDGET` | **2** | **distinct targets** granted against one ticket id, keyed `(ticket, target)` | `TICKET-BUDGET` |

**There is no daily term anywhere in the criteria path.** Nothing resets at
midnight, and waiting for tomorrow is not the fix for either code.

**Both escalate; neither is terminal.** Each refusal returns an `approve_url`
and a poll handle, deduplicated on `(principal, kind, target, ticket)` so a
retry loop does not mint a request per attempt. A cap refusing into a dead end
would be worse than no cap, because the safe action and the impossible action
would look identical to you.

Four things that decide whether you act correctly on one:

- **The counts are "after this grant"** — the comparison is
  `live_grants + 1 > cap`. Holding two is refused; a caller at the cap is **one
  release away**, not guessing.
- **`GRANT_CAP` groups on `ssh_user`, not principal** — deliberately "across all
  their agents". Two of your agents working at once share one allowance of two,
  and a grant another agent opened counts against you.
- **Re-asking for a target this ticket already used does not count twice** —
  extending a window you hold is not reaching further. `TICKET-BUDGET` means
  *distinct* targets: two hosts on one ticket is the ceiling, and the third host
  needs a different ticket.
- **A cap of `0` disables it.** Absence of a limit is not a limit of zero.

**When you hit `CONCURRENCY-CAP`, enumerate before you guess:**

```
POST /agent/status        # your own grants and nothing else, both flows
→ {"hosts": [...], "units": [...], "live_grants": 2, "grant_cap": 2, "at_cap": true}
```

Enumerate → release → retry is the loop. `hosts` reports **device ids**, not
hostnames, so match on the ids the grants were opened against.

**Recorded because they were all plausible and all wrong** — the three guesses
this fleet made from 403s alone, before reading `jit-ssh`'s README and
`jit_criteria.py`: *"same network only"*, *"one grant at a time, full stop"*
(the documented cap is two — a second live grant, possibly another agent's, is
what makes it feel like one), and *"a fleet-wide daily budget on the
principal"*. Two caps, both `2`, neither daily. **Read the source, not the
error string.**

### `jit` itself is never requestable

`jit` is the approver and is **deliberately not a target**. It is absent from
`JITSSH_TARGETS` by design; do not expect to request access to it.

## Standing keys — supported on private, going away on company

This section used to treat both sides as one dwindling "legacy" path. Per the
ruling at the top, they are not the same thing.

**Private / LAN — supported, not legacy.** Peter's own machines are reached with
a local key and that is the intended arrangement:

- **Homelab** (Proxmox VMs): `192.168.16/17/18/19.x`, user `peter` or `root`,
  **port 22**, key `~/.ssh/id_ed25519_peter` on multica-01. See the `homelab`
  skill. Nothing here is queued for removal.

**Company — being removed; plan every company host as a JIT request.**

- `*.chosts.io`, user `peter`, **port 2822**. Where a standing key is still
  installed it still works, but it is **not the access path** and must not be
  planned around, re-installed, or copied to a new host. Mind the non-standard
  port if you meet one that has not been migrated yet.
- Agents have no standing-key path to these hosts at all — JIT is the whole
  access story for them. This line used to add "and no agent JIT target either",
  which was **wrong**: see *What is requestable*, where a grant against a live
  chain node is shown succeeding with no human involved.

## The keys

Two purpose-built ed25519 keys (plus YubiKey FIDO2 fallbacks). Keep their
roles separate — auth/login is one key, signing is another.

| Key | Role | Used for |
|---|---|---|
| `~/.ssh/id_ed25519_peter` (`peter@chainlayer`) | **auth + login** | Git auth to **GitHub** (tyrion70) — though see the `insteadOf` section: on a host with a `gh` token the transport is HTTPS and this key is not consulted. Host login: **supported for Peter's private/LAN machines** from multica-01; **being removed for company hosts**, which go through JIT. |
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

## GitHub from a host: one `insteadOf` line decides whether the token is used

**A valid `gh` token is not enough. The remote's URL form decides the transport,
and the transport decides whether the token is ever consulted.**

This is not theory. On 2026-09-03 `Private Sync` on **multica-01** failed every
run with `git@github.com: Permission denied (publickey)`, and it looked exactly
like a missing credential — a PAT was nearly created for it. It wasn't missing:

- multica-01 had `gh` 2.94.0 and a **working OAuth token all along** (`gh auth
  login` answered *"You were already logged in to this account"*).
- Its remote was in SSH form (`git@github.com:…`) and the host had **no
  `url.insteadOf` rewrite**, so git went out over SSH and hit a key that had
  been deleted — while the perfectly good token sat there unused.
- **multica-02 had the rewrite.** It therefore used the token over HTTPS and
  never noticed. That single line of git config was the entire difference
  between the two hosts.

So, on any host where git talks to GitHub:

```bash
git config --global url."https://github.com/".insteadOf git@github.com:
gh auth setup-git          # installs gh as the credential helper
```

```bash
# Diagnosing "Permission denied (publickey)" against GitHub — check in this order:
git config --get-regexp 'url\..*insteadOf'   # is the rewrite there at all?
gh auth status                                # is there a token, and with what scopes?
git ls-remote <remote> >/dev/null && echo ok  # what actually happens end to end
```

**`Permission denied (publickey)` for GitHub on a host with a working `gh`
login means the rewrite is missing, not the credential.** Reach for
`git config --get-regexp url` before reaching for the vault, and before asking a
human to mint a token — the same class of mistake as looking for the missing key
on multica-02, and it cost most of a day here.

(This is the GitHub twin of the GitLab rewrite documented above:
`url.https://gitlab.com/.insteadOf = git@gitlab.com:` plus
`gitlab-agent-credential-helper`. Same mechanism, same failure if it is absent.)

## Git commit signing

SSH-format signing with the dedicated signing key. **Which key and which
identity is host-dependent** — the same split `git-mr` Step 2 documents, and
getting it wrong is not cosmetic:

| Host | `user.name` / `user.email` | `user.signingkey` |
|---|---|---|
| **Multica agent runtime** (multica-01/02) | `peter-agent` / `peter+agent@chainlayer.io` | `~/.ssh/peter_agent_signing.pub` |
| **Peter's own machines** | `Peter van Mourik` / `peter@chainlayer.io` | `~/.ssh/id_ed25519_signing.pub` |

`id_ed25519_signing` is **not installed on an agent runtime** — the same point
the GitLab-auth section above makes about the key table. Prescribing it there
pins signing to a path that does not exist, and every signed commit hard-fails.

On an agent runtime the global config is **already correct**. Check before you
write anything:

```bash
git config --global --get-regexp '^(user\.|gpg\.|commit\.gpgsign)'
```

Only if it is genuinely absent, and matching the host from the table above:

```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/peter_agent_signing.pub   # agent runtime
git config --global commit.gpgsign true
# verify locally: add the pubkey to an allowed-signers file
git config --global gpg.ssh.allowedSignersFile ~/.ssh/allowed_signers
#   ~/.ssh/allowed_signers:  peter+agent@chainlayer.io <contents of the .pub>
```

⚠️ **`--global`, never repo-local** — see the warning in `git-mr` / `git-pr`
Step 2. A Multica checkout is a git *worktree* sharing one bare-repo config, so
a repo-local write here overrides the identity for every other worktree of that
repo, past and future.

`git log --show-signature` should report `Good "git" signature for` the email
listed in `allowed_signers` on that host. Note that `allowed_signers` matches on
**principal**: a signature made with the right key but attributed to the *other*
host's email still fails verification, so the email and the key have to come
from the same row of the table. Add the signing key to GitHub/GitLab as a
**signing** key (separate from the auth key) for the green "Verified" badge.

## The keys are NOT in the vault — corrected 2026-09-03

**This section used to say both private keys live in the Bitwarden `shared`
folder as `ssh/id_ed25519_peter` and `ssh/id_ed25519_signing`. They are not
there.** Checked 2026-09-03: the `shared` folder holds three unrelated items,
and there are **no SSH key items anywhere in the vault**. Whether they were ever
there and were later removed is not known — what is established is that the
path this section gave does not resolve today.

That matters more than a stale path, because it was a **recovery procedure that
does not work**. Someone rebuilding a host would have followed it, found
nothing, and had to work out mid-task whether the key was lost or the document
was wrong. A documented recovery path that fails is worse than none: it is
believed until it is needed.

**What is actually true:**

- `~/.ssh/id_ed25519_peter` exists **on multica-01 only**, and has **no
  backup** — not in Bitwarden, not in 1Password. If that host is lost, the key
  is lost, and the recovery is to generate a new one and re-register the public
  half (GitHub for git auth, plus any LAN `authorized_keys`).
- Company runtimes do not have it and do not need it (see the top of this
  skill), so its absence there is not a recovery problem.
- The company runtime's signing key is `~/.ssh/peter_agent_signing`, generated
  per runtime.

**Wiring a fresh host**, then, is not a vault restore. Generate a key, register
the public half where it is needed, and drop in the `~/.ssh/config` git-auth
mappings above (`chmod 600` the private key, `644` the `.pub`). For company
hosts there is nothing to wire: access is JIT.

> If a key ever *is* put in the vault, correct this section in the same change.
> The failure above was not the key moving — it was the document outliving the
> arrangement it described.

## Don'ts

- Don't use the signing key as the primary auth identity in config, or the
  auth key for signing — keep the roles split.
- Don't commit private keys to git; they live in `~/.ssh`, and in a vault only if
  one actually holds them — see *The keys are NOT in the vault* above.
- Don't forget `IdentitiesOnly yes` — without it SSH may offer the YubiKey
  keys first and trigger spurious PIN prompts.
