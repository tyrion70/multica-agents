---
name: chainlayer-knowledge
description: Durable cross-cutting knowledge about ChainLayer's live infra projects — the chainlink-tools platform, the Optimism/Postgres/Proxmox migrations, the Filecoin voter node, and QuickNode RPC URLs. Read this for background/state and key decisions when working any ChainLayer infra issue; it points you at the domain skill for HOW-TO. Keep it updated (PR) when a durable fact or decision changes. ALSO the authoritative list of **AI-managed hosts** — the hosts on which an agent acts without human pre-approval (the rule itself is in the company `CLAUDE.md`) — read this before deciding whether a host is in that tier; membership is the list, never a judgement call. ALSO the rule for posting to Slack: agent messages go out as the dedicated `peter_agent` bot (field SLACK_BOT_TOKEN_PETER_AGENT, xoxb, from Bitwarden at point of use), NEVER through the `slack` MCP server, which carries Peter's personal xoxp token and would make every AI message look like he wrote it — read this before posting anything to Slack.
---

# ChainLayer knowledge

Background facts, decisions, and gotchas about ChainLayer's live projects — the
stuff worth carrying between issues. **HOW-TO lives in the domain skills**
(`chainlink-ops`, `company-k8s`, `company-proxmox`, `haproxy`, `deploy-app`,
`grafana-monitoring`, …); this skill is durable *knowledge and decisions*, not a
runbook, and not day-to-day status (don't put "N of M done as of <date>" here —
that rots). When something durable changes, update this file via a PR against
`tyrion70/multica-agents` and tell the user.

## AI-managed host tier — the list of hosts agents operate without asking

The **AI-managed tier** is a named set of hosts on which an agent takes an
operational action it judges necessary without human pre-approval. The authority
rule — the two conditions, the mandatory post-report, and the stop-on-anomaly
limit — is in the company `CLAUDE.md` ("AI-managed hosts: act, don't ask").
**This section is the list that rule points at, and the list is the whole
definition of the tier.**

**A host is in the tier because it appears below, never because it looks
AI-managed.** "AI-managed" is also a phrase in some repo descriptions and the
name of the `ai-maintained` deploy key; neither puts a host in the tier. If you
find yourself arguing that a host qualifies, it does not — it is out until this
list says otherwise, and extending the list is a PR against
`tyrion70/multica-agents`, not a call made inside a run.

**In the tier — the nineteen AI-maintained node networks, and every VM belonging
to them.** One flat list: for membership all nineteen are equal, and how or when
a network arrived here decides nothing.

| network | repo | metrics label (`chainlayer_network`) |
|---|---|---|
| ab        | `chainlayer/nodes/ab-infra` | `ab` |
| abstract  | `chainlayer/nodes/abstract-infra` | `abstract` |
| adi       | `chainlayer/nodes/adi-infra` | `adi` |
| apechain  | `chainlayer/nodes/apechain-infra` | `apechain` |
| astar-l1  | `chainlayer/nodes/astar-l1-infra` | `astar` |
| bitlayer  | `chainlayer/nodes/bitlayer-infra` | `bitlayer` |
| bittensor | `chainlayer/nodes/bittensor-infra` | `bittensor` |
| cronos    | `chainlayer/nodes/cronos-infra` | `cronos` |
| etherlink | `chainlayer/nodes/etherlink-infra` | `etherlink` |
| hemi      | `chainlayer/nodes/hemi-infra` | `hemi` |
| katana    | `chainlayer/nodes/katana-infra` | `katana` |
| lens      | `chainlayer/nodes/lens-infra` | `lens` |
| morph     | `chainlayer/nodes/morph-infra` | `morph` |
| pharos    | `chainlayer/nodes/pharos-infra` | `pharos` |
| rootstock | `chainlayer/nodes/rootstock-infra` | `rootstock` |
| stable    | `chainlayer/nodes/stable-infra` | `stable` |
| tac       | `chainlayer/nodes/tac-infra` | `tac` |
| wemix     | `chainlayer/nodes/wemix-infra` | `wemix` |
| xdc       | `chainlayer/nodes/xdc-infra` | `xdc` |

**A row is three strings, not one, and one row's differ.** The row name is the
repo/inventory string: repo `chainlayer/nodes/<row>-infra`, ansible inventory
group `<row>`, hosts `<row>-main-rpc-{1a,2a}-nl2v.chosts.io`. The **metrics**
string is the third column — the `chainlayer_network` label Prometheus and
Alertmanager carry — and it is the same word on eighteen rows and **not** on
`astar-l1`, whose label is `astar`. Checked all nineteen on 2026-09-09 against
the label index on `prometheus-node-1a-nl2v`, in both directions: every other
row's label is byte-identical to its row name, and each label resolves to that
row's two hosts.

So pick the column by what the consumer keys on, and never translate between
them by hand: an alert filter, a Grafana query or the **Networks health sweep**'s
VM set keys on the **label**; the **Networks renovate + LCM sweep**, `gitlab-iac`
consumer lists and CI paths key on the **repo**. Writing `astar-l1` where a label
is wanted matches nothing and fails silently — the config reads as correct and
covers nothing, which is exactly how the network went unwatched (CHA-1267).

**The invariant: this list is the `tag:ai-maintained` set on the
`java-moth.ts.net` tailnet.** Nineteen networks, thirty-eight hosts, one to one —
checked in both directions on CHA-1251 (38 = 19 × 2; no tagged host missing from
this table and no row without its tagged hosts). The tag string is exactly
`tag:ai-maintained`, and a Tailscale tag write is replace-only, so a near-miss
name cannot be granted by accident.

Write the invariant down so drift is detectable rather than silent: if the
`tag:ai-maintained` host count ever stops being twice the number of rows here,
one of the two moved and it is worth finding out which. It is a **detector, not
a second definition** — the row is the membership. A network carrying the tag but
no row here is *not* in the tier, and a row here whose hosts are untagged is a
tagging job, not a demotion. Extending the tier is both: add the row, tag the
hosts.

**Out of the tier — explicitly, and as binding as the list above:**

- the `chainlink-*` oracle namespaces — live revenue-earning nodes; the
  strictest-ask-first rules in the `chainlink-ops` skill stand unchanged,
- the shared HAProxy fleet,
- the Proxmox hosts themselves (as distinct from a tier VM running on one),
- GitLab and GCP IAM,
- the monitoring2 Alertmanager mesh,
- **everything not named in the table above**, including every other node
  network. The tier is those nineteen, not "node networks" as a category — a
  twentieth network is out until it has a row.

Two consequences worth stating on their own, because each has been got wrong:

- **A shared-infrastructure change stays out of the tier even when it is done
  for a tier node.** Changing the shared HAProxy config, DNS, the Proxmox host,
  a shared CI template or the `gitlab-iac` consumer lists on behalf of lens is a
  shared-infrastructure change, not a lens change. Nineteen `-infra` repos being
  in the tier puts **nothing shared** in it, however many tier networks a change
  is for — "it's for all of them" makes a change more shared, not less. This is
  not new: it is why the drain/undrain work was dropped on CHA-1230 — it needed
  a shared HAProxy change and would have silently downgraded the health gate.
- **The tier is about authority, not access.** It widens nothing the JIT grant
  model gates: the `GRANT_CAP` of 2 on the shared `peter-agent` principal is a
  coordination constraint, unaffected by this.

Origin: CHA-1258 → CHA-1259. A deliberate reboot of the lens standby node
bounced because no agent held a rule saying a lower-risk class of host exists,
so every agent correctly fell back to the strictest rule it had. Widened from
seven networks to nineteen on 2026-09-09, taking the set and the tailnet-tag
invariant from CHA-1251.

## chainlink-tools platform (dynamic node registry)
Three apps under `chainlink-tools/`, all deploying to the `chainlink` namespace in
`k8s-apps`, replacing the static `sites.json`/`hostmap.json` at
`chainlink.chainlink.cinternal.com` with dynamic registration:
1. **chainlink-service-registry** — Flask, in-memory node registry + heartbeats.
2. **chainlink-delete-jobs** — CronJob; registry-aware via `REGISTRY_URL`.
3. **chainlink-jira-sync** — stateless CronJob.
All nodes share one password stored as a k8s secret (the registry does NOT serve
it). Later phase: split each into its own repo + CI. The
`chainlink-utility-sidecar` image must be rebuilt to include `registry_sidecar.py`.

## Optimism migration (OPS-2135) — archive is bare-metal-only
Migrated OP mainnet to **k8s op-reth, full-node only**, on nl-oven. **Archive is
deferred indefinitely** because OP's published `mainnet-reth-archive-*.tar.zst` is
structurally broken — every reth version crashes at `StaticFileProducer` init
(`Receipts index` mismatch); confirmed across all known workarounds. The legacy
`.tar.zst` files are l2geth chaindata / bedrock op-geth datadirs, not RLP, so not
usable with `op-reth import-op` without major work. **Bare-metal Hetzner archive
keeps serving archive RPC indefinitely.** Do NOT re-attempt the published
reth-archive snapshot unless OP has published a fix dated later than 2026-05-19.
Full-node combo that works: op-reth v1.11.3 + op-node v1.16.9.

## Postgres migration (VMs → Zalando operator on k8s)
Migrating **82 Chainlink Postgres DBs** off 8 dedicated DB VMs to the Zalando
Postgres Operator on nl-oven (operator already installed). The big one is
`chainlink-database-1a-nl2v` (75 DBs). Project files: `projects/postgres-migration/`.
Zalando config lives in the **`clusters`** repo (not k8s-apps). GCS WAL backup needs
the `gcs-walg-creds` secret (only in `dev` ns so far). Decommissioning these VMs
depends on the Prox7→9 migration finishing.

## Proxmox 7→9 migration — decommission Prox7
Migrating all VMs from Prox7 (nl2) to Prox9 (nl2_c4) via PBS backup/restore + TF
import, to decommission Prox7. Project: `projects/proxmox-migration/` (migration-plan.md,
vm-assignments.csv, run-plan.sh). **The full procedure + disk-string safety rules live
in the `company-proxmox` skill — use it.** Durable decisions worth remembering: every
VM gets a Linear issue (project "Proxmox 9 VM Migration in NL"); silence alerts BEFORE
any action via the AM v2 tailnet API (NOT the stale `silence-vm.sh` — see
`grafana-monitoring` skill + `company-proxmox` skill for the current AM path); merge
TF `removed` blocks before stopping VMs; do NOT start VMs after restore (user moves
disks ceph→local-ZFS first); max 10 VMs/MR; never hand-construct disk strings — read
the live string and flip only the differing flags.

## Filecoin voter node — Lotus, and the fork-check
ChainLayer's Filecoin **governance/voting** node is **Lotus** (ArgoCD
`filecoin-lotus-mainnet`, nl-oven, ns `filecoin`), **not** the separate bare-metal
ChainSafe **Forest** deployment (`chainlayer/nodes/filecoin-infra`). Filecoin **NVxx
upgrades are mandatory and epoch-gated**: a too-old Lotus silently forks onto a dead
minority chain while `lotus sync status` still says "complete". Detect by comparing
tipset CIDs at a fixed height against glif (`api.node.glif.io`) vs in-pod
`lotus chain list`; fix = bump the image to the NV release + Argo rollout (binary-only;
the chainstore is preserved). History: OPS-2343, missed NV28 on v1.35.0 → v1.36.0.

## QuickNode RPC URL structure
Endpoints are `https://<prefix>.<network>.quiknode.pro/<token>`:
- `<prefix>` = **`side-convincing-emerald`** — fixed for the ChainLayer account, all chains.
- `<network>` = QuickNode network slug, varies per chain (not secret).
- `<token>` = the credential — store ONLY this, in **GCP Secret Manager project
  `mythic-fulcrum-424015-f9`** (surfaced via the `k8s-shared` ClusterSecretStore on
  nl-oven), secret name `quiknode-rpc-key`. Prefix + slug are non-secret (chart values).

## Data-feeds fleet — ChainLayer is the Chainlink node operator

ChainLayer **is** the Chainlink node operator for the data-feeds fleet. The
external adapters (EAs/bridges) run in our own `chainlink-ea` k8s namespace on
nl-oven — we hold the API-key secrets and own the bridge job specs.
Config/operation (job specs, ticker→exchange-suffix mapping, pod lifecycle) is
ours to fix directly. A genuine defect in the EA **software** goes as an **MR
against the Chainlink `external-adapters` repo** — never a bespoke
reimplementation adapter in our repo.

## Chainlink node job spec retrieval — use the operator UI / API

Job specs for data-feeds (and other `FeedsManager = true`) nodes live in the
**node DB**, not k8s configmaps. Retrieve via the REST API — no `kubectl exec`
or port-forward needed:

```
GET https://{chain}.chainlink-data-feeds.nl-oven.chainlayer.cloud/v2/jobs/{id}
```

The `observationSource` field in the response is the full TOML pipeline spec
(bridge task names, ds1/ds2/ds3, task graph). Full how-to including auth and
credential location: **`chainlink-ops` skill**, "Chainlink node API" section.

## Datafeeds health app — lives on the **monitoring VM**, not multica-02

The `chainlink-datafeeds-health` app (report, dashboard, DB, sweeps) **moved
off multica-02** (CHA-1035 migration, cut over 2026-08-13). Current home:
**monitoring VM** — `192.168.18.232` / `monitoring.252h.org`, VMID 130 on
proxmox4. Everything datafeeds was **deleted from multica-02 on 2026-08-21**
(CHA-1087) — the DB and its roles, the containers and images, the nightly
`backup-datafeeds-health` timer and its dumps, the checkout, and the crontab block.
So multica-02 is not a fallback you can start up: there is nothing there to start,
and a DSN pointing at `127.0.0.1` from multica-02 (or from a Multica agent
workspace, which runs on multica-02) now fails instead of silently hitting a frozen
copy. The repo's `CLAUDE.md` is the short authoritative version of this.

- **Dashboard**: container `datafeeds-health-dashboard` on the monitoring VM,
  port **8080** (`http://monitoring.252h.org:8080`), `--network host`,
  restart `unless-stopped`. Served from `/opt/chainlink-datafeeds-health`
  (repo checkout). The adapter-test button needs the **write path** enabled:
  `DATAFEEDS_HEALTH_WRITER_DSN` + `WEBAPP_SECRET_KEY` plus
  `CHAINLINK_NODE_EMAIL`/`CHAINLINK_NODE_PASSWORD`/`REGISTRY_URL` set on the
  container — if those are present-but-empty, `writes_enabled()` is false and
  the test adapter reports disabled with that exact reason (CHA-1067).
- **Postgres**: the `datafeeds_health` schema lives on the **monitoring VM**
  at `127.0.0.1:5432` (loopback only). Roles exist there (e.g.
  `datafeeds_readonly`, `datafeeds_health_writer`); the vault DSNs point at
  the monitoring VM's loopback, not multica-02's.
- **Sweeps / baseline**: hourly sweep + daily baseline run as root cron on
  the monitoring VM (`/etc/cron.d/datafeeds-health-sweep`,
  `/etc/cron.d/datafeeds-health-baseline`), not the Multica autopilots (those
  are paused). Each `sweep-cron.sh` run pulls the checkout, so **merge to main
  is the deploy** for the sweep path; the dashboard image is rebuilt separately
  via `dashboard/deploy.sh` on the VM.
- **VM access**: request access through **JIT** (`https://jit.java-moth.ts.net/`;
  agents use `POST /agent/grant`, see the `ssh` skill). The standing
  `id_ed25519_peter` key still works on the LAN as a fallback while it exists,
  but JIT is the mechanism that replaces it. Tailscale SSH to the monitoring
  node is denied by tailnet policy.

## Slack: agent messages go out as an agent bot (`xoxb`), NOT through the `slack` MCP server
**The MCP `slack` server is configured with the `xoxp` PERSONAL token, which
authenticates as Peter's own user account** (workspace owner/admin). Posting through
it makes every AI-authored message appear as though **Peter wrote it personally** —
in fourteen channels. Don't. This is not a style preference: the reader cannot tell
an agent's finding from their colleague's opinion.

It is easy to get wrong because the MCP server is right there and looks like the
obvious path. It was got wrong on 2026-09-04 (CHA-1211): a connectivity test posted
to `#general` as `UserID UR1T4EEL8 / peter`, and the only copy of this rule was
inside one autopilot's description, where nothing outside that autopilot's own run
could find it.

**Instead**, resolve the bot token at point of use via the `bitwarden` skill — item
**`ChainLayer · Slack — bot token (xoxb)`**, field **`SLACK_BOT_TOKEN_PETER_AGENT`** —
and call the Web API directly:

```bash
curl -s -X POST -H "Authorization: Bearer $SLACK_BOT_TOKEN_PETER_AGENT" \
  -H 'Content-type: application/json; charset=utf-8' \
  --data '{"channel":"#<channel>","text":"...","unfurl_links":false}' \
  https://slack.com/api/chat.postMessage
```

That field is **`peter_agent`** (`U0BV2JXRW04`, app `B0BUSMY10KD`) — a bot identity
created specifically for agent posts (2026-09-04), so an AI-authored message is
distinguishable from **both** Peter and Albert Indigo. It holds `chat:write.public`,
so it can post to any *existing* public channel **without being invited first**.
Never echo the token.

**Pick the field by name, not by shape.** The same Bitwarden item holds three fields,
and the two bot tokens are indistinguishable by eye — both `xoxb`, both 57 characters:

| field | identity | use it for |
|---|---|---|
| `SLACK_BOT_TOKEN_PETER_AGENT` | `peter_agent` / `U0BV2JXRW04` | **agent posts — this one** |
| `SLACK_BOT_TOKEN` | `ai_bot` "Albert Indigo" / `U0BA9MGR77U` | the workspace's older AI bot; not for agent posts |
| `SLACK_APP_TOKEN` | `xapp` app-level token | Socket Mode, not the Web API |

Three practical notes:

- **`bw sync` before an ad-hoc lookup.** The local Bitwarden cache does not notice a
  field added on another machine, so a fresh field reads as absent — which looks
  exactly like "the field doesn't exist" and sends you to the wrong one.
  `SLACK_BOT_TOKEN_PETER_AGENT` was invisible for that reason within minutes of being
  created (CHA-1211). `sync.sh` already runs `bw sync` before resolving placeholders;
  an interactive or one-off lookup has to do it itself.
- **Read the message back** rather than trusting the write's return value. A
  `chat.postMessage` that returns `ok` still tells you nothing about which identity
  it posted as — that is exactly how the CHA-1211 slip was caught, and how it would
  have gone unnoticed otherwise. `auth.test` answers the same question before you
  post, and is the only thing that tells the two `xoxb` tokens apart.
- **`xoxb` is fetched fresh from Bitwarden every time, `xoxp` is not.** The `xoxp`
  token is baked into 35 agents' `mcp_config`, so rotating it requires a
  repo→workspace delivery; rotating `xoxb` requires nothing. And the `xoxp` server
  cannot simply be retired in favour of a bot token: `search.messages` rejects a bot
  token with `not_allowed_token_type` even when the app has been granted the whole
  `search:read.*` set (checked 2026-09-04 on `peter_agent`, which has it). Reading
  the scope list says yes; reading the API's answer says no. Search stays user-token
  work; **posting** does not.

## Co-authored-by commit hook — disabled at the workspace setting
The Multica daemon installs a git `prepare-commit-msg` hook (in each bare repo's
`hooks/` dir under `.repos/<workspace_id>/<repo>.git/hooks/`) that injects a
`Co-authored-by: multica-agent <github@multica.ai>` trailer on every agent commit —
which violates our no-`Co-Authored-By` rule. **The toggle is a server-side workspace
setting, `co_authored_by_enabled`, NOT a daemon binary flag or env var.** It is
**disabled (`false`) for the Chainlayer workspace** — Peter set it via the Multica web
UI workspace settings (admin/owner). The daemon reads it at `multica repo checkout`
time and skips the hook when it's off. Verify with `multica workspace get` →
`settings.co_authored_by_enabled` (the `multica workspace update` CLI does not expose
this flag — it's UI-only). This reconciles the CHA-175 finding that no config flag
existed in the daemon binary: the control was never daemon-local, it's the workspace
record the daemon queries. With it off, a fresh checkout no longer reinstalls the hook
and agent commits carry no trailer and stay SSH-signed (verified Good). If the trailer
ever reappears, first check `co_authored_by_enabled` is still `false`. (CHA-175/CHA-177)
