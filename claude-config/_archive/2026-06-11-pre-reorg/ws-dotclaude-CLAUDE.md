# Claude global context

Personal Claude config root. Loaded into every session.

- **Workspace overview** lives in `~/claude/CLAUDE.md` (clusters, monitoring, registries, k8s deployment pipeline). Read that first for repo layout.
- **Per-project notes** live in `~/claude/projects/<name>/CLAUDE.md`.
- **Repos in active use** are indexed in [REPOSITORIES.md](REPOSITORIES.md).
- **In-flight work, current incidents, open MRs, mid-bootstrap state** are in [STATUS.md](STATUS.md) — read that if the user asks "where are we" or wants to resume something. This CLAUDE.md is for durable knowledge only.

---

## Cluster access

- Production clusters via Tailscale: `nl-oven` (Amsterdam primary), `nl-spud` (Amsterdam secondary), `no-fryer` (Oslo). All Talos on Proxmox.
- `kubectl` contexts are named after the cluster.
- **`nl-oven` cluster egress NAT IP: `89.149.216.9`** — use this to firewall-restrict external mirrors so only the cluster can pull.
- **Anything that needs `kubectl` access cannot run in an Anthropic cloud routine** — cloud agents have no Tailscale. kubectl-based monitoring/automation must live in a session-local cron or a process you start.

## LINSTOR storage classes

- `linstor-double-replica` (default), `linstor-archive`, `linstor-archive-zpool`.
- **All support online volume expansion.** `kubectl patch pvc … requests.storage=…` then update the Helm values to keep Argo in sync. No pod restart needed.
- **Both `linstor-archive` and `linstor-archive-zpool`** back onto the **same `zpool` storage pool** across the 6 archive worker nodes (`k8s-oven-worker-{1..6}-archive-rocky{12,13,14,15,11,16}-nl2b`), each 46.56 TiB total. **`autoPlace: "1"` + `allowRemoteVolumeAccess: "false"`** → replica count = 1, volumes are placed on a single node, so provisionable capacity is bounded by the **most-free node**, not the sum. `WaitForFirstConsumer` binding mode.
- The `k8s-oven-worker-{7st,8st,9}*` nodes are diskless-only (no zpool) and cannot host archive volumes. Worker `8st-rocky4` flaps offline in linstor periodically.
- **Inspect pool capacity:** `kubectl -n piraeus-datastore exec deploy/linstor-controller -c linstor-controller -- linstor sp l` (the controller is `linstor-controller-*` in the `piraeus-datastore` ns).

## Chain-node operations (op-stack / op-reth)

### Three op-stack source directories (Argo Applications come from any of them)

| Source | ArgoCD shape | Notes |
|---|---|---|
| `appsets/op-reth/<chain>-reth/<network>/` | `ApplicationSet:<chain>-reth-<network>` → fans out `*-full-node` + `*-archive` apps | Current pattern for reth chains. Most chains live here. |
| `appsets/op-stack/<chain>/<network>/` | `ApplicationSet:<chain>-<network>` | op-stack chart, `execution.client` selects `geth` or `reth`. Currently used for `blast`, `celo`, `mantle` (all geth, full-node only). |
| `apps/op-stack/<chain>/<network>/` | **Standalone `Application`** (legacy kustomize, no ApplicationSet) | Legacy. Each env (`base/`, `environments/full-node/`, `environments/archive/`) is its own ArgoCD `Application`. The kustomize structure stays in repo even after the chain moves to an appset — check `kubectl get applications -n argocd` to see what's actually live. |

To tell which kind manages an app: `kubectl get application -n argocd <name> -o jsonpath='{.metadata.ownerReferences[0].kind}'` — `ApplicationSet` = appset-managed; empty = standalone.

### Archive vs full-node split

For both appset sources, env YAMLs under `environments/` matrix-generate the Argo apps:

```
appsets/op-{stack,reth}/<chain>/<network>/
  base-values.yaml                 # shared
  environments/full-node.yaml      # → app <chain>-<network>-full-node
  environments/archive.yaml        # → app <chain>-<network>-archive
```

Adding a new env YAML is enough — the ApplicationSet auto-creates the app on the next git poll (default ~3 min). Pod name: `<chain>-<network>-{full-node|archive}-<n>`.

### Helm chart routing

| Chart | Used for |
|---|---|
| `helm-charts/charts/op-stack` | geth-based chains (mantle, blast, celo, op-mainnet, …) |
| `helm-charts/charts/op-reth` | reth-based chains (base, unichain, soneium, worldchain, ronin, fraxtal, xlayer, ink, celo-reth) |
| `helm-charts/charts/base-node` | base-reth specifically (ghcr.io/base/node-reth bundles execution + consensus) |
| `helm-charts/charts/snapshot-manager` | nightly VolumeSnapshot → tar | zstd → MinIO upload |

### Snapshot bootstrap convention

1. **First boot** pulls from the chain owner's public snapshot. Pin a static URL (the chart does `wget -O- <url> | zstd -dc | tar -x -C /data`) — no dynamic indirection.
2. Add the chain to `apps/snapshot-manager/environments/<cluster>.yaml` so it gets a nightly cron. Bucket layout:
   ```
   storage1/quicksync-staging/<chain>/<network>/<full|archive>/latest.tar.zst
   ```
   Public URL: `https://storage1.quicksync.io/quicksync-staging/<chain>/<network>/<full|archive>/latest.tar.zst`
3. Once our snapshotter has published `latest.tar.zst`, **flip `urls.base` in the env YAML to that URL** so future replicas bootstrap from us, not the chain owner.
4. Until our snapshot exists: keep cronjob `suspend: true` and set `allowDowntime: true` so the snapshotter can run later against a single-replica archive without flapping health.

### Chart quirks

- `execution.snapshot.compression` must match the URL (`zstd`, `lz4`, or empty for `.tar.gz`).
- `execution.snapshot.stripComponents` for snapshots packed with a leading dir prefix:
  - base.org reth snapshot extracts to `/data/snapshots/<network>/download/{db,static_files,…}` → use `stripComponents: 3`.
  - Conduit (ronin) snapshot uses `stripComponents: 1`.
- The chart only consumes the URL when `/data/.initialized` is missing. After first boot you can change the URL freely — no-op until PVC is wiped.
- The snapshot init container is **fixed to single-stream wget**. There is no aria2 / parallelism. Long bootstraps are network-bound. Singapore-S3 → Amsterdam single-stream is ~16 MiB/s.
- `mantle-op-geth` lays out chaindata at `/data/chaindata` (no `geth/` prefix). Non-standard vs vanilla geth.
- `base-reth-node` opens existing `op-reth` datadirs cleanly — base.org image switch is an image+env swap, no resync.
- **`ghcr.io/base/node` is the legacy geth + op-node bundle (rebranded but still pre-Azul). The Azul-era image is `ghcr.io/base/node-reth` (separate package) — only `v0.16.0+` carries the new binaries.** Easy multi-hour mistake to grab the wrong one.
- **op-stack geth archive nodes need `--snapshot=false` AND `--gcmode=archive`, and the chart gates gcmode behind `state.scheme: hash`.** The op-stack chart only emits `--gcmode=archive` when `execution.state.scheme: hash` is set (`charts/op-stack/templates/statefulset.yaml`). If you set `gcmode: archive` but leave `state.scheme` empty, the flag is silently dropped → the "archive" node runs default gcmode and **prunes state**. Separately, without `--snapshot=false` geth tries to build the flat snapshot, which never completes on a multi-TB archive DB — it aborts/resumes every block (`accounts=1 slots=0` after hours), pinning block execution at ~75 s/block while op-node loops `Payload execution failed: context deadline exceeded`. Symptom: node "syncing" but advancing ~48 blk/h with time-lag *growing*. Fix (matches Mantle's canonical `docker-compose-mainnetv2`): `execution.state.scheme: hash` + `extraArgs: [--snapshot=false]`. With both, per-block import drops ~75 s → ~10 ms. **Check existing geth archive nodes (celo/blast/future) for this same latent gap.** Always diff your rendered `kubectl get sts … -o json | jq '…execution…args'` against the chain owner's official compose flags.
- **`OrderedReady` podManagementPolicy blocks rolling updates when a pod is not Ready.** If an op-stack pod is stuck unready (e.g. healthcheck failing on sync lag) and you push a config fix via git, Argo updates the StatefulSet spec but the controller won't roll the pod — catch-22 (pod unready *because* of the bug the fix addresses). Break it by `kubectl delete pod <sts>-0`; the StatefulSet recreates it on the new `updateRevision`. PVC persists. Take a VolumeSnapshot first if the data is precious.

### `--rollup.historicalrpc` semantics (verified empirically)
On op-stack reth, `--rollup.historicalrpc=<url>` proxies **only for blocks the full node has no local data on** (i.e. pre-bedrock for migrated chains). It does **not** forward pruned receipts or state for post-bedrock blocks. Chainlink LogPoller backfill of pruned ranges therefore needs to hit the archive node via a separate RPC URL, not via the full node's historicalrpc proxy.

### Healthcheck-agent sidecar (`node_agent_*` metrics)

Every op-stack-shaped pod runs the **chainlayer healthcheck-agent** ([healthcheck-agent-gitlab](#healthcheck-agent)) as a sidecar. It polls the execution RPC every ~10 s and emits a uniform Prometheus metric set regardless of geth vs reth:

- `node_agent_health_status{module="evm"}` — 1 healthy / 0 unhealthy. Goes 0 when `lag > max_lag_seconds`, height-stagnant, or peers < min.
- `node_agent_block_height`, `node_agent_finalized_block_height`, `node_agent_earliest_block_height`, `node_agent_total_blocks`
- `node_agent_block_lag_seconds` — `now - latest_block.timestamp`
- `node_agent_height_stagnant{ }` — 1 if height hasn't advanced in `height_stagnation_threshold` seconds (default 120 s)
- `node_agent_peer_count` — **execution-layer** peers via `net_peerCount` (see peer-counting note below)
- `node_agent_last_known_state_active` — **1 means the RPC poll is currently failing** and the agent is replaying its last successful read. Important to check when block height / peers look "fine" but never change.
- Counters: `node_agent_check_total{result}`, `node_agent_rpc_requests_total{result}`, `node_agent_reconnects_total`

Two distinct sidecar deployments exist in the fleet, distinguished by the Prometheus `endpoint` label:

| Chart family | `endpoint` label | Container name | Port |
|---|---|---|---|
| `helm-charts/charts/op-stack` + `op-reth` | `healthcheck-metrics` | `healthcheck` | 8123 |
| `apps/blockchain-nodes/<chain>/` (legacy, e.g. ronin pre-Bedrock) | `agent-metrics` | `healthcheck-agent` | 8000 |

Filter Grafana queries with `endpoint="healthcheck-metrics"` to limit to op-stack chart sidecars only.

**Image matters, not just container name.** The fleet-standard sidecar image is `node-agent` (e.g. `node-agent:0.0.14`) which emits the `node_agent_*` metrics above — this is what `op-stack` + `op-reth` charts use and what the `opstack-nodes-overview` Grafana dashboard queries. There is a *separate, different* image literally named `healthcheck-agent` (Python) that emits a DIFFERENT metric set (`healthcheck_ok`, `latest_block_height`, `block_time_drift_seconds`, `healthcheck_*`) with NO `node_agent_*` and no `blockchain`/`namespace` labels → **invisible to the dashboard**. The `helm-charts/charts/base-node` chart wrongly uses `healthcheck-agent:latest` (the prior session swapped to it to dodge a node-agent CLI arg error instead of fixing the args). Fix = switch base-node's healthcheck back to `node-agent:0.0.14` with the standard args so it shows on the dashboard like every other op-reth chain.

### Op-stack peer counts — EL vs CL

For chains running `rollup.syncmode: consensus-layer` (most op-reth chains), blocks arrive via op-node Engine API. **`node_agent_peer_count`** measures the **execution layer's** `net_peerCount`, which is frequently 0 by design — e.g. blast sets `--maxpeers=0 + nodiscover: true` explicitly; op-reth in consensus-layer mode doesn't actively peer at the EL even when configured to. **The meaningful peer count is the rollup layer**, exported by op-node on port 7300:

- **Newer op-node** (`v1.16+`): `op_node_default_p2p_peer_count`
- **Older op-node**: `p2p_peers`
- Combined query: `op_node_default_p2p_peer_count{...} or p2p_peers{...}`

### Disk-space gotcha for aria2-style bootstraps

`aria2` needs a seekable file (no `tar | zstd` piping), so the two-step workflow is `aria2c → file` then `zstd -dc | tar -x` from that file. Peak disk = compressed + extracted ≈ 2× the snapshot size. Size the PVC for peak, not steady state. Mitigations: pre-resize PVC, scratch PVC, or stick with the chart's streaming wget.

## reth operational lore

- **`eth_blockNumber` is stuck at the staged-sync checkpoint until the `Finish` stage runs.** During Prune/Execution the RPC does *not* track live tip — don't read it as "current height."
- **Per-segment Prune progress:** `kubectl exec -c execution -- curl -s http://localhost:6060/metrics | grep highest_pruned_block`. Only granular signal during Prune; Status log only ticks on whole-stage completion.
- **Prune target ratchets forward** with chain head — net catch-up rate = pruner rate − chain head rate (~7.2k/h on Base).

## Session-local /loop cron trap

`/loop <interval> <prompt>` uses `CronCreate`. The cron's `prompt` field must be the **bare task** prompt, **not** wrapped in `/loop`. If you store `/loop 1h <task>` as the cron prompt, every fire re-enters the loop skill and schedules another cron on top — duplicates accumulate hourly.

- Cron `prompt` = the verbatim task ("Status check on X: emit …").
- Use an off-minute cron expression (`7 * * * *`, not `0 * * * *`) — avoids the :00 / :30 thundering herd.
- Recurring crons auto-expire after 7 days.

## Process reminders

- **MR-per-bump.** Even a one-line `persistence.size` change goes through a fresh branch off `origin/main`, MR with template, merge. Direct `kubectl patch` only as immediate insurance — always follow with the MR so Argo source-of-truth stays aligned.
- **Helm map-merge null trick.** When switching probe handlers (e.g. `httpGet` → `tcpSocket`), explicitly null the inherited one with `httpGet: ~` — otherwise both leak through and k8s rejects "more than 1 handler type."

## Grafana Cloud (`chained.grafana.net`)

The team's hosted Grafana — production dashboards live here. The bare-metal Grafana on `grafana.cinternal.com` is the data source layer; visualization is in Cloud.

- **Service account token** is stored locally at `~/claude/.mcp.json` under `mcpServers.grafana.env.GRAFANA_SERVICE_ACCOUNT_TOKEN` (format `glsa_…`). Same token works for the MCP server and direct `curl` calls.
- API base: `https://chained.grafana.net/api`. Auth: `Authorization: Bearer <token>`.

**Useful endpoints:**

- `GET /api/datasources` — list datasources (returns `uid`, name, type).
- `GET /api/dashboards/uid/<uid>` — fetch a dashboard JSON model.
- `POST /api/dashboards/db` — create/update a dashboard. Payload `{"dashboard": <model>, "overwrite": true|false, "message": "..."}`. Returns `{"uid","url","version",...}`.
- `GET /render/d-solo/<dash_uid>/<dash_slug>?panelId=N&var-datasource=<ds_uid>&width=W&height=H&from=…&to=…` — server-side PNG render of a single panel (image-renderer). Pass `&_=<timestamp>` to bust the render cache.

**Prometheus / Thanos datasource UIDs** (these survive sessions — stable):

| UID | Name |
|---|---|
| `deexgsum1bz7ka` | prometheus-nl-oven |
| `df37c3m1043r4a` | prometheus-nl-spud |
| `beexh7l99aq68b` | prometheus-no-fryer |
| `cepbu6izhi3nke` | thanos-de2 |
| `aepc7djwfjeo0d` | thanos-nl2 |
| `fepc79v1myg3ke` | thanos-no1 |
| `grafanacloud-prom` | grafanacloud-chained-prom (Cloud's own scrape) |

**Datasource proxy for ad-hoc PromQL:** `GET /api/datasources/proxy/uid/<ds_uid>/api/v1/query?query=…`.

### Grafana `organize` transformation field-naming quirk (table panels)

When using `joinByField` (outer-join by a key like `pod`) followed by an `organize` transform, the **first query's** non-key label fields keep the suffix `" 1"` (e.g. `blockchain 1`) — but in some edge cases the unsuffixed name (`blockchain`) is also retained from the first frame, leading to surprises like `endpoint` column landing at the end despite `indexByName.endpoint = 1`. Workarounds:

- **`renameByName` and `renameByRegex` rename the field before subsequent transforms see it.** Field-config overrides (`matcher: byName`) match the **renamed** name post-rename. Use the override's `displayName` property to set a column header — and remember override matchers use the field's **original** name, not the rename target.
- For deterministic positioning, insert a `renameByRegex` step **before** `organize` so the field has a guaranteed-unique name, then position by that.
- `indexByName` silently ignores entries whose name doesn't exist in the joined frame — empty-handed reorders look like nothing happened.

## Plasma is NOT an OP-stack chain

`apps/blockchain-nodes/plasma/mainnet/` uses upstream **`ghcr.io/paradigmxyz/reth`** as execution + **`ghcr.io/plasmalaboratories/plasma-consensus`** as Plasma's own consensus client. No op-node, no op-reth, no `rollup.json`. Same chart family as Ronin pre-Bedrock (`apps/blockchain-nodes/<chain>/`). When asked about "Plasma op-reth migration" the answer is: there is no migration — it's a standalone EVM chain with its own consensus, not a rollup.

## HAProxy (load balancer in front of almost everything)

- All `*.rpc.cinternal.com` resolves to **`89.149.218.7`** = HAProxy enterprise (hapee 2.4). Also reachable as `haproxy1.cinternal.com`, `haproxy2.cinternal.com`.
- Stats: `http://haproxy.cinternal.com:9600/hapee-stats` (HTML) and `;csv` (machine). Prometheus: `:8405/metrics`. Dataplane API: port 5555, basic auth from GCP secret `haproxy-api-auth`.
- **Don't poke the dataplane API live** — all changes go through the `haproxy-gitlab` repo. MR → `pushconfig.sh` deploys to both LBs.
- Backend dispatch in `hapee-lb.cfg fe_main`: hostname → `txn.backend_rpc = "<name>-rpc"`, `*-ws`, `*-ext-rpcN`, `*-ext-wsN`. Two URL-param flags steer routing:
  - `?external=1` — force external upstream
  - `?noexternal=1` — opt out of auto-fallback to external
  - Both are literal-`1` matches (`-m str 1`). `?external=true` or bare `?external` won't trigger.
- Internal `use_backend` rules use `nbsrv gt 0` (since OPS-2134) — when internal pool drops to 0 healthy, evaluation falls through to the external-fallback rule. The original `ge 0` always matched and returned 503 with an empty pool.
- **`balance source` is the default** — every source IP hashes to one backend forever. To probe both backends from a workstation you need different source IPs (e.g. exec from multiple pods).

### HAProxy `backends.yaml` schema
```yaml
- name: <service>
  channels:
    - {name: '', port: 8545, ws_upgrade: true, ws_port: 8546, check_port: "check port 11001"}
  internal:
    nodes:
      - {name: <hostname.chosts.io>, ip: "<ip>", location: NL2|NO1|DE1|FI1|...}
  external:                                            # optional, renders to *-ext-rpcN/*-ext-wsN
    nodes:
      - {host: rpc.ankr.com, path_prefix: <chain>/<key>, port: 443}
```
Local render: `python3 backends.py --dc NL2 -o /tmp/out.cfg`. CI's `validate-config` job runs `haproxy -c`.

### Shared Ankr key (chainlayer)
`rpc.ankr.com/<chain>/4d75a29da9eb107dcc54d5a22f918e6172bda4390374d0b5a43adb8e5a8e021a` — used by hyperliquid, eth-beacon, optimism, celo, etc.

### Backend health-check pattern (`check port 11001`)
Most `internal.nodes` entries set `check_port: "check port 11001"`. Port 11001 is the **chainlayer health-check agent** — a Docker container (`tyrion70/health-agent-new`) deployed per VM by each chain's `*-infra` ansible repo via `group_vars/healthcheck.yml` (or `group_vars/all/healthcheck.yml`). Agent does an L7 check against the local RPC + Prometheus tip-distance gate, so HAProxy shows `L7OK` when the node is synced.

- **If a chain has no `*-infra` repo or its `healthcheck.yml` is missing, the agent isn't there** → HAProxy gets "Connection refused" on 11001 → backend stays `DOWN / L4CON` → 503s through the frontend. Easy mistake when *adding a backend* for a chain that was previously only reachable directly by chainlink.
- **Fallback when agent is unavailable**: `check_port: "check port 8545"` (plain L4 TCP check on the RPC port). Same pattern is already used for `base-mainnet-full-node-api` and `mantle-mainnet-full-node-api`. Loses "behind tip" semantics, gains "comes up at all."
- To diagnose: `curl -s 'http://haproxy.cinternal.com:9600/hapee-stats;csv' | awk -F, '$1 ~ /^<chain>/'`. `last_chk = Connection refused` → agent not running. `nc -zv <vm-ip> 11001` confirms.

### Backend naming convention (`<chain>` vs `<chain>-archive`)
For op-stack chains with both a full-node and an archive (ronin, soneium, xlayer, worldchain, unichain, base): the **normal `<chain>` backend already includes the archive node** in `internal.nodes` and round-robins across both. The separate `<chain>-archive` backend is **archive-only**, intended for specifically-archive workloads. **Don't add both as separate `[[EVM.Nodes]]` in a chainlink config** — single `<chain>.rpc.cinternal.com` entry is enough. **Exception**: `eth-main-execution` is full-node-only (4 nodes, no archive); `eth-main-execution-archive` is a real separate pool — keep both.

### WebSocket-over-HAProxy hardening
HAProxy `defaults` carries:
```
option srvtcpka
srvtcpka-idle 30s
srvtcpka-intvl 10s
srvtcpka-cnt 3
```
TCP-layer keepalive on server-side sockets. Operates below WebSocket framing so it detects dead backends even when client→server WS pings keep `timeout tunnel` fresh. Closes dead sockets in ~60s (well under chainlink's 5-min `NoNewHeads` alert). **Why this matters**: chainlink doesn't auto-reconnect WS subscriptions when the backend dies; Cilium L4 LB conntrack-pins TCP and doesn't send FIN/RST on hard-pod-kill (snapshot-manager scale-to-zero, OOM, node loss); chainlink WS pings keep `timeout tunnel` from firing. `srvtcpka` is the kernel-level circuit breaker that catches all of these.

### Where chainlink RPC config lives & shape
`k8s-apps/appsets/chainlink/decentralized-oracle-network/{bootstrap,cre,cre-df,data-feeds,automation,ccip,keystone,data-streams}/nodes/<chain or capability>.yaml`. Inside each, a multi-line **TOML-in-YAML string** (the chainlink `config.toml`). Per-chain layout:
```toml
[[EVM]]
ChainID = "<id>"
... chain-level keys ...

  [[EVM.Nodes]]
  Name = "<label>"
  WSURL = "ws://..."
  HTTPURL = "http://..."
  IsLoadBalancedRPC = true   # set for any *.rpc.cinternal.com URL
  Order = 1                  # priority for PriorityLevel selection
```
Commented blocks (lines starting with `#`) are common (held for reference). When grepping for "active" URLs, filter them out. Watch for **mixed single/double quotes** within the same file.

## Chainlink `IsLoadBalancedRPC` flag

Lives in `chainlink-framework/multinode` (`node.go`, `node_lifecycle.go`). 5 lifecycle gates + recovery loop:

- `true` → treat URL as proxy/LB; if it's the only Node and goes stale/no-new-heads/no-finalized → declare OutOfSync/Unreachable → reconnect (next TCP may land on a healthier upstream).
- `false` (default) → treat as single dedicated RPC; never declare it dead when it's the only one — force-marks alive even when degraded ("if we kill it we have nothing").

**Set `true` for any HAProxy URL** (`*.rpc.cinternal.com`). Required for transparent failover from the `nbsrv gt 0` HAProxy rule.

**Crashloops on old chainlink images** — strict TOML decoder rejects unknown field. Too old to support it: `2.9.1-automation-20240304` (keeper), `v2.20.0-0.0.5-tron`, `v2.24.0-starknet-plugins`, `2.26.1-aptos-hotfix8a/8b` (keystone). Supported: `2.39.x+`, `2.40.x+`, `2.41.x+`, `2.43.x+`, `2.44.x+`, `2.46.x+`, `2.47.0`, `2.48.0-rc.0`.

## Chainlink k8s namespaces

`chainlink` (shared services) · `chainlink-automation` · `chainlink-bootstrap` · `chainlink-ccip` · `chainlink-cre` · `chainlink-cre-df` · `chainlink-data-feeds` · `chainlink-data-streams` · `chainlink-keystone` · `chainlink-streams[-experimental]` · `chainlink-database` (Zalando postgres) · `chainlink-ea` + `chainlink-ea-data-streams-{production,staging}` · `chainlink-vpn`

**Containers in chainlink pods**: `node`, `auto-approve`, `registry` (sidecars). Logs: `kubectl logs <pod> -c node`. Init containers: `init-config`, `init-secrets`. Config inside pod at `/mount/config.toml` (rendered from `config-template.toml` ConfigMap by init).

**Chain-node yaml configs**: `k8s-apps/appsets/chainlink/decentralized-oracle-network/{automation,bootstrap,ccip,cre,cre-df,data-feeds,data-streams,keystone}/nodes/*.yaml`.

## chainlink-ops (Slack/Jira sync service)

Persistent service in `chainlink` ns, image `europe-docker.pkg.dev/prime-hydra-436615-d6/chainlayer/chainlink-ops`. Replaces two former CronJobs (`chainlink-jira-sync` + `chainlink-delete-jobs`).

- Two background loops every 5 min: `jira_sync` (Jira↔Linear) + `jd_processor` (Slack JD msg → Linear → node-job delete).
- PVC `chainlink-jira-sync-state` (100 Mi, `linstor-double-replica`, RWO) at `/data`. Two JSON files: `sync_state.json` + `jd_state.json`.
- HTTP `:8080`: `/health`, `/metrics`, `/status`.

### Slack token refresh (`xoxc-…` + `xoxd-…`)

1. **Slack web** (NOT desktop) → workspace `chainlink-nodes` → DevTools → Network → filter `api.slack.com`.
2. `xoxc-…` lives in the **POST body** form-data field `token` of any authenticated call (`client.boot`, `users.list`, …). NOT a cookie.
3. `xoxd-…` is the `d` cookie. Keep URL-encoded (`%2F`, `%2B` stay as-is).
4. Push to GCP:
   ```bash
   echo -n 'xoxc-…' | gcloud secrets versions add chainlink-delete-jobs-slack-token  --project=mythic-fulcrum-424015-f9 --data-file=-
   echo -n 'xoxd-…' | gcloud secrets versions add chainlink-delete-jobs-slack-cookie --project=mythic-fulcrum-424015-f9 --data-file=-
   ```
5. Force ESO refresh + pod restart:
   - ArgoCD UI → `chainlink-ops` app → right-click `Secret/chainlink-delete-jobs-secrets` → Delete (Background, no Force). ESO recreates in ~5 s.
   - `kubectl -n chainlink rollout restart deploy/chainlink-ops`.

## chainlink-topup

REST API at k8s svc `chainlink-topup` in `chainlink` ns, port 8080:
- `GET /api/v1/config` — full topup config (per-network addresses, min thresholds, descriptions)
- `GET /api/v1/status` · `/api/v1/history` · `/api/v1/balances` · `/api/v1/watchlist/:network`
- `PATCH /api/v1/config/addresses` (auth) — update a single address's description

The repo file `k8s-apps/apps/chainlink/topup/overlays/nl-oven/topup.json` can be **stale**; the live API is authoritative. The `description` field is hand-curated → drives the Prometheus label `description` on `chainlink_key_balance`, `chainlink_key_min_balance`, `chainlink_key_has_topup_contract` (chainlink-service-registry MR !84). Canonical values referenced in alert exclusion regex: **`Safe`, `Admin`, `Topup Caller`, `Excluded`, `Automation`** — use those literally. `Keeper` / `Keeper V1` are NOT matched (legacy names).

## ExternalSecrets Operator (ESO)

- ExternalSecret CR pulls from GCP Secret Manager → emits a k8s Secret. Default `refreshInterval: 1h`.
- Force immediate refresh: `kubectl annotate externalsecret <name> -n <ns> force-sync=$(date +%s) --overwrite` (needs `externalsecrets.io patch` RBAC).
- If RBAC blocks: **delete the produced Secret via ArgoCD UI** (right-click → Delete → Background). ESO recreates within seconds.
- My user RBAC on `chainlink` ns: can `delete pods` + `patch deployments`; **cannot** patch externalsecrets or delete secrets directly → use ArgoCD UI (full perms).

## Fortigate firewalls

- nl2 `https://10.22.0.1:8443` · no1 `https://10.122.0.1:8443`.
- API tokens in GCP Secret Manager: `fortigate-automation-fg-nl2-core-api-token`, `fortigate-automation-fg-no1-core-api-token`. Also locally in `~/claude/projects/proxmox-migration/.env` as `FORTIOS_TOKEN_NL2/NO1`.
- IaC in `fortigate-iac`. Conventions:
  - Address groups: `A-AG-*` (TF-managed). Network ranges: `N-NL-*`. Hosts: `A-H-*`. External hosts: `A-EXT-*`.
  - Colors: addresses=18 (sky-500), TF-managed addresses=21 (violet-200), AGs=22 (purple-200, TF), AGs=23 (manual).
  - Comment for TF-managed objects: `<context>\nManaged by Terraform`.

## External DNS / k8s LoadBalancer hostnames

`*.nl-oven.chainlayer.cloud` → LoadBalancer ext-IPs on nl-oven cluster (Cilium L2 announcements). Example: `worldchain-reth-mainnet-full-node-api.nl-oven.chainlayer.cloud` → `10.3.1.44`. P2P LBs separately on public IPs in `176.103.222.0/23` / `176.103.223.0/24` (k8s public-IP pool, allowlisted in Fortigate via `A-AG-NL-K8S-PUBLIC-RANGES`).

### Cilium L4 LB conntrack pinning (failure mode worth knowing)
Cilium for `Service: LoadBalancer` is conntrack-pinned at L4 — when a backend pod hard-dies (SIGKILL, node crash, scale-to-zero), no FIN/RST is sent to existing TCP sockets. New SYNs hit a new pod, but **existing TCP sockets sit in conntrack pointing at a dead endpoint** until something else (kernel keepalive, app-layer timeout) kills them. This is why long-lived WS subscriptions through a per-chain `LoadBalancer` Service hang on pod restart. The bare-metal HAProxy `srvtcpka` defaults (see HAProxy section) are what catches it when chainlink routes via HAProxy instead.

## Chainlayer bare-metal IP scheme

| Prefix | DC / role |
|---|---|
| `176.103.222.0/23` + `176.103.223.0/24` | NL2 Worldstream — bare-metal chain VMs + k8s public-IP pool |
| `86.111.48.0/24` | NO1 Oslo bare-metal |
| `89.149.218.7` | HAProxy VIP (`*.rpc.cinternal.com`, `haproxy{,1,2}.cinternal.com`) |
| `89.149.216.9` | nl-oven cluster egress NAT |
| `10.22.0.0/16` | nl2 management (Fortigate `10.22.0.1`) |
| `10.122.0.0/16` | no1 management (Fortigate `10.122.0.1`) |
| `10.3.x.x` | nl-oven pod/LB CIDRs |

**`<chain>.chosts.io` is the bare-metal VM hostname convention** (e.g. `bsc-main-node-1a-nl2v.chosts.io`). DNS in `dns-chosts` repo. **A bare IP showing up in any config without a matching `*.chosts.io` cname is suspicious** — could be a repurposed VM (the IP got reassigned to a different chain).

## GCP projects (chainlayer)

- `mythic-fulcrum-424015-f9` — chainlink-ops secrets (slack token/cookie, …)
- `prime-hydra-436615-d6` — private docker registry (`europe-docker.pkg.dev/prime-hydra-436615-d6/chainlayer/`)
- `chainlayer` — public quickimage registry (`europe-docker.pkg.dev/chainlayer/quickimage/`)
- Common secrets: `haproxy-api-auth`, `fortigate-automation-{fg-nl2,fg-no1}-core-api-token`, `chainlink-delete-jobs-slack-{token,cookie}`.

## Operational gotchas (collected)

- **HAProxy source-stickiness**: probes from a single workstation IP only test one backend. Run from multiple pods/IPs to spread.
- **Chainlink OCR1** uses one-shot `ConfigFromLogs` to bootstrap. If the OCR1 pod restarts after its `ConfigSet` block has fallen out of the RPC's log-index window, the job won't start. OCR2's continuous LogPoller doesn't have this fragility.
- **Optimism cinternal "archives" (de1m, fi1m)** serve state and headers fine but `eth_getLogs` returns 0 beyond ~100 k blocks — started without receipts/log index. Workaround: Ankr as external HAProxy upstream (already wired).
- **Chainlink TOML decoder is strict** — unknown fields are a hard error. New TOML keys have to wait for the relevant chainlink image to support them (see IsLoadBalancedRPC crashloop).
- **`balance source` + maint**: HAProxy keeps the hash sticky even when the chosen server is in maint — it won't auto-roll to the other backend in the same pool. To force fallover you either drain the whole pool or rely on the external-fallback rule firing (after the `gt 0` change).
- **Renovate handles k8s-apps digest bumps automatically** for internal images pinned `latest@sha256:…`. After merging a code MR, expect Renovate to auto-open + auto-merge the corresponding k8s-apps bump → ArgoCD sync → pod rollout. No manual k8s MR needed.
- **YubiKey SSH** sometimes prints `sign_and_send_pubkey: signing failed` but git ops still work via cached keys.
- **Tofu**: always `tofu fmt -recursive` before committing Terraform.

## Homelab Proxmox cluster (`proxmox`, `proxmox2`, `proxmox3`, `proxmox4`)

4-node PVE cluster at the user's home — separate from the chainlayer prod boxes (`Prox7`, `Prox9`). Quorate, cluster master IP `192.168.16.200`. Nodes: `proxmox` (192.168.16.200), `proxmox2` (192.168.16.151), `proxmox3` (192.168.19.81), `proxmox4` (192.168.19.82). Direct root SSH from this host works (Tailscale-routed via VM 112).

**VM 110 = `Ubuntu-2404-Template`** (cloud-init, cloned to spawn new VMs). Lives on `proxmox4`. Don't start it; clone it.

**Cloning a new VM:**

```bash
ssh root@<node-ip> '
  qm clone 110 <VMID> --name <name> --full
  qm set <VMID> --cores N --memory <MiB> --onboot 0
  qm resize <VMID> scsi0 <size>G
  qm start <VMID>
'
# Get DHCP IP (~10–30 s after start):
ssh root@<node-ip> "qm guest cmd <VMID> network-get-interfaces" | jq …
```

**VMID convention:** ask before reusing. `pvesh get /cluster/nextid` works but homelab has gaps (115 was free as of 2026-05). Existing 100-series VMIDs are documented in `~/claude/projects/proxmox/cluster-overview-*.md`.

**Default cloud-init has:** `ciuser=root`, `cipassword` preset, `vmbr0` bridge, `ipconfig0=ip=dhcp`, SSH keys including `peter@chainlayer`. After clone, the VM gets a DHCP lease on `192.168.16.0/22` from the UDM.

Distinct from chainlayer prod proxmox endpoints (Prox7 `10.24.0.16`, Prox9 `10.34.0.163`).

## Linear & Slack conventions

- Linear team: **DevOps**. Always create the issue **before** coding; use the Linear-generated branch name (`peter/ops-XXXX-<slug>`). Body template: `## Why … ## Done When (checkboxes) … ## Additional Information`. MRs must link a Linear issue.
- Comments: sign with `- Claude <model>` to distinguish AI-written.
- Slack channels worth knowing: `#xmonitoring-kubernetes`, `#xmonitoring-fullnodes` (monitoring alerts); `#xnetwork-<chain>` per-chain; `#inc-*` auto-created incident channels. `chainlink-nodes` workspace = where to grab the `xoxc-` for the JD processor token refresh.

## This host (`claude-workstation-01`)

If this session is running on `claude-workstation-01` itself, you're on the homelab VM at:

| | |
|---|---|
| LAN IP | `192.168.17.34` |
| Tailscale | `peter-workstation-01` / `100.102.224.96` |
| User | `peter`, login shell zsh |
| Native claude | `~/.local/bin/claude` — installed via `claude install`, **not** npm. PATH set in `~/.zshrc`. |
| VMID / host | 121 on `proxmox4` (Ubuntu 24.04, 16c/64GB/100GB system + 500GB ext4 /home on `/dev/sdb`). |

Rebuild gotcha: VM **must** be `cpu: host` (or `x86-64-v3`). Default `kvm64` lacks AVX → Bun (Claude Code runtime) segfaults on launch with "CPU lacks AVX support". Documented in the `claude-workstation-vm` playbook.

Don't `npm install -g @anthropic-ai/claude-code` — Claude warns about external package managers and breaks its self-update path afterwards. Use `claude install` or `claude-mgr update`.

## Multi-session management — `claude-mgr` / `cm`

Each Claude session lives in its own tmux session named `claude-<name>` on the VM. Source repo: `tyrion70/cm` (see REPOSITORIES.md).

- On VM: `claude-mgr {list,start,attach,send,logs,kill,restart,update,broadcast}`
- From laptop: `cm <same>` SSH-wraps and translates `~/claude/...` → `/home/peter/claude/...`
- Default flags: `--continue --dangerously-skip-permissions`. `--continue` is **auto-dropped** when the workdir has no prior session jsonl (otherwise claude exits straight back to a shell).
- `/remote-control` is **on by default** (opt-out via `--no-remote`).
- `restart <name>` and `update` use `tmux respawn-pane -k` (NOT `send-keys "/exit"` — slash commands don't reliably fire via send-keys, they get typed into Claude's prompt instead).
- `update` runs `claude install`, NOT `npm install -g`.

State lives entirely in `tmux list-sessions` — no daemon, no registry file. Sessions survive across SSH disconnects but **not** tmux server restarts; session jsonls on disk in `~/.claude/projects/<encoded-cwd>/` survive everything.

## Hetzner box (off-site)

`135.181.22.118` / `hetzner.252h.org` — Hetzner dedicated AX-series. AMD Ryzen 9 3900 (12c/24t), 128 GiB RAM, 2× 894 GB Samsung NVMe, **10× 14.6 TB SATA in ZFS `tank` (146 TB raw)**. Debian 13 + PVE 9.1.2. Runs VM 100 (MinIO) + CT 101 (PDM). Tailscale `100.85.45.86`, internal subnet `10.99.0.0/24` routed via VM 112 from home.

| Connect | Command |
|---|---|
| SSH | `ssh -p 2822 root@135.181.22.118` (**non-standard port**) |
| PVE UI | `https://hetzner.252h.org:8006` (only allowed from home WAN) |

**iptables: default policy `DROP`**, allowlist-based. Existing inbound allows: `tailscale0`, loopback, established/related, TCP/2822, TCP/8006-8007 from home WAN, plus per-task ports (`51234` for nginx file-server when sharing `/tank/video`). Add temporary rules with `iptables -I INPUT N -i enp7s0 -s <ip> -p tcp --dport <port> -j ACCEPT`. **Persistence** survives across UniFi-OS-style upgrades only via `/mnt/data/on_boot.d/*.sh` boot scripts — `iptables-save` is **not** persisted by default.

`apt-get update` returns **401 Unauthorized** on `proxmox-enterprise` (no subscription) — ignore the error; installs from Debian core still work. Eventually swap to `pve-no-subscription`.

For sharing large files (multi-TB snapshots, etc.), use **nginx** — never `python3 -m http.server` (single-threaded, tiny buffers, falls over).

## Network public IPs worth remembering

- **Home WAN** (Putten, behind UDM-Pro Max Caiway uplink): **`62.45.81.180`**
- **ChainLayer corporate egress** (NAT'd outbound IP for chainlayer-internal traffic): **`89.149.216.9`**

Used in firewall allowlists on hetzner + similar.

## UniFi API (UDM-Pro Max) capabilities

- `portforward` endpoint is **TCP/UDP only** — schema requires numeric `dst_port` regex. **No** GRE (protocol 47), no IPsec passthrough, no IP-protocol-level forwarding via API.
- Confirmed by direct probe: `proto=gre` and `proto=47` both rejected with `api.err.InvalidValue`.
- WAN-networkconf has no `dmz_*` field exposed — no "DMZ host" feature.
- PUTs are **partial-commit** (well documented in memory and existing forbidden-imports section).

So: ExtraIP-style GRE-routed extra IPs aren't natively supportable on UDM-Pro Max without SSH'ing in + adding iptables DNAT to `/mnt/data/on_boot.d/`. Cleaner alternative: terminate the GRE on the hetzner box (which already has a public IP) or use a small VPS as relay.

## Refinement to `historicalrpc` semantics

(Adds to section above on `--rollup.historicalrpc`.) **Reth's fallback only fires when reth thinks it lacks the data locally — never when its own index returns 0.** Specifically:

- `eth_getBlockByNumber` for a pruned block → forwards via historicalrpc (works).
- `eth_getLogs` for a range reth has locally but its log index is incomplete → returns `[]` from local index, **does not forward**.

Verified empirically on ronin-mainnet 2026-05-26: `ronin-reth-mainnet-archive` returns `0 logs` for block range `0x32b1d90..+10`, while geth `ronin-mainnet-full-node` returns `228 logs` for the same range. Archive doesn't fall back to its own historicalrpc target because it believes it has the block.

Practical implication: pointing an archive's historicalrpc anywhere is mostly dead code (only fires for queries the archive truly can't answer, e.g. state on blocks before its snapshot). Pointing a full-node's historicalrpc at an archive is fine only if the archive's index is complete; otherwise full-node + archive both return wrong-but-non-error empty results.
