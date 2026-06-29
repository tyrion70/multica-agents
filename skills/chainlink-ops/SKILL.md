---
name: chainlink-ops
description: Operate ChainLayer's Chainlink node fleet — RPC config changes, node debugging, adapter lifecycle, token refreshes, topup, and the chainlink-ops/jira-sync/delete-jobs services. Use whenever touching anything in the chainlink-* namespaces, editing node TOML configs in k8s-apps, decommissioning external adapters, or refreshing Slack/registry credentials. These are live oracle nodes earning revenue — strictest ask-first rules of any domain.
---

# Chainlink operations

**Blast-radius warning:** everything here serves live oracle jobs. A bad config
merge crashloops nodes; a wrongly deleted adapter breaks feeds. Mutations get
explicit confirmation; config changes go through k8s-apps MRs (see `git-mr`).

## Fleet layout

- **Namespaces**: `chainlink` (shared svcs) plus `chainlink-{automation,bootstrap,ccip,cre,cre-df,data-feeds,data-streams,keystone,streams[-experimental],database,vpn}` and `chainlink-ea`, `chainlink-ea-data-streams-{production,staging}` (external adapters). `chainlink-database` = Zalando postgres.
- **Pod containers**: `node` (the chainlink binary — `kubectl logs <pod> -c node`),
  sidecars `auto-approve`, `registry`. Init: `init-config`, `init-secrets`.
  Rendered config inside the pod: `/mount/config.toml`.
- **Node configs in git**: `k8s-apps/appsets/chainlink/decentralized-oracle-network/{bootstrap,cre,cre-df,data-feeds,automation,ccip,keystone,data-streams}/nodes/<chain|capability>.yaml`
  — a multi-line **TOML-in-YAML string**. Watch for commented-out reference
  blocks (filter `#` lines when grepping for active URLs) and mixed quote styles.

## RPC config rules

Per-chain TOML shape:

```toml
[[EVM]]
ChainID = "<id>"

  [[EVM.Nodes]]
  Name = "<label>"
  WSURL = "ws://..."
  HTTPURL = "http://..."
  IsLoadBalancedRPC = true   # REQUIRED for any *.rpc.cinternal.com URL
  Order = 1
```

- **`IsLoadBalancedRPC = true` for every HAProxy URL** (`*.rpc.cinternal.com`).
  It makes the node declare a sole stale LB endpoint dead and reconnect
  (next TCP lands on a healthier upstream). `false` (default) = "dedicated RPC,
  never give up on it" — wrong for an LB.
- **One `<chain>.rpc.cinternal.com` entry is enough** — the normal backend
  already round-robins full-node + archive. Don't add `<chain>-archive` as a
  second `[[EVM.Nodes]]`. Exception: `eth-main-execution` + `-archive` are
  genuinely separate pools — keep both.
- **Strict TOML decoder**: unknown keys hard-crash old images. Known too-old:
  `2.9.1-automation-20240304`, `v2.20.0-0.0.5-tron`, `v2.24.0-starknet-plugins`,
  `2.26.1-aptos-hotfix8a/8b`. `2.39.x+` is safe for `IsLoadBalancedRPC`. Check
  the product's image tag before adding new TOML keys.
- **OCR1 fragility**: OCR1 bootstraps via one-shot `ConfigFromLogs`; if the pod
  restarts after its `ConfigSet` block left the RPC's log window, the job won't
  start. Don't casually restart OCR1 pods.
- LogPoller backfill of pruned ranges needs the **archive RPC URL directly**
  — a full node's `--rollup.historicalrpc` does NOT forward pruned receipts.

## Adapter lifecycle (chainlink-ea)

- **Decommission check needs TWO metrics over 24h** (datasource
  `deexgsum1bz7ka` / prometheus-nl-oven):
  `http_request_duration_seconds_sum{namespace="chainlink-ea"}` (HTTP) AND
  `bg_execute_total{namespace="chainlink-ea"}` (WebSocket bg execute). HTTP
  alone falsely flags ~29 WS-driven adapters as idle. Zero on both → candidate;
  even then watch for infrequent runners (PoR sub-adapters).
- **Composite adapters** are marked `app.chainlayer.io/composite-adapter: "true"`
  on the Service, optional `bridge-alias`/`bridge-aliases` annotations.
  Composite = `*_ADAPTER_URL`/`*_DATA_PROVIDER_URL` pointing at data sources;
  pointing at other adapters = orchestrator, NOT composite.
- Adapter images: `public.ecr.aws/chainlink/adapters/` (tracked by Renovate semver).

## Shared services

- **chainlink-ops** (deployment, `chainlink` ns): jira_sync + jd_processor loops
  every 5 min; PVC `chainlink-jira-sync-state`; HTTP :8080 `/health` `/status`.
- **chainlink-topup** (svc :8080): `GET /api/v1/{config,status,history,balances}`.
  The live API is authoritative — the repo `topup.json` can be stale. The
  `description` field drives alert-exclusion labels; canonical values: `Safe`,
  `Admin`, `Topup Caller`, `Excluded`, `Automation` (NOT `Keeper`).
- **Slack token refresh** (when jd_processor 401s): grab `xoxc-…` from the POST
  body field `token` of any authenticated api.slack.com call in Slack **web**
  (not desktop), workspace `chainlink-nodes`; `xoxd-…` is the `d` cookie (keep
  URL-encoded). Push both:
  `gcloud secrets versions add chainlink-delete-jobs-slack-{token,cookie} --project=mythic-fulcrum-424015-f9 --data-file=-`
  Then force ESO: delete `Secret/chainlink-delete-jobs-secrets` via **ArgoCD
  UI** (Background) → recreated in ~5 s → `kubectl -n chainlink rollout restart deploy/chainlink-ops`.
- **ESO refresh in general**: annotate `force-sync=$(date +%s)` if RBAC allows;
  otherwise the ArgoCD-UI secret-delete dance. Peter's RBAC on `chainlink` ns
  cannot patch externalsecrets directly.

## Credentials

Machine-consumed secrets live in **GCP Secret Manager** (`mythic-fulcrum-424015-f9`
for chainlink-ops secrets) and reach pods via ExternalSecrets. Human-held
credentials (UI logins, API keys you need mid-task) → use the **bitwarden**
skill, `company` folder. Never paste a token into a YAML/TOML file — wire it
through GCP + ESO.

## Permission model

✅ Without asking: logs, describe, metrics queries, topup API GETs, reading
configs in git, rendering proposed TOML diffs.

🔶 GitOps: ALL config changes (TOML, images, sidecars) = k8s-apps MR. Remember
Helm lists replace, not merge — include all sidecars when overriding per-node.

🛑 Ask first, with a one-line blast-radius statement: pod deletes/restarts
(especially OCR1 and keystone), job deletions, adapter removals (show the
dual-metric evidence first), secret pushes to GCP, ESO secret deletes, anything
in `chainlink-database`.

## Chainlink pre-escalation investigation

**Gate — ask Peter first.** Before running any Chainlink investigation steps,
explicitly confirm with Peter (via issue comment or Slack) that an investigation
is warranted. Do not self-start — these steps touch live node APIs and adapter
endpoints on revenue feeds.

This section documents the verified procedure from CHA-193 for investigating
datafeed anomalies **before escalating to Chainlink support**. The pattern:
query the node for the exact jobspec → replay that requestData against the
external adapter → check data provider coverage for gaps.

### Topology

- **Cluster**: `nl-oven` (k8s)
- **Node ns**: `chainlink-data-feeds`
- **Adapter ns**: `chainlink-ea` (each EA :8080 http / :9080 metrics)
- **Provider keys**: k8s secrets per-adapter, wired via `envFrom`

**Host RBAC**: readonly hosts (`tag:claude-readonly`, e.g. `multica-02`) can
`get`/`logs` only — `exec`/`port-forward`/`secrets` denied. Run from a
write-RBAC host (e.g. `claude-workstation-01`), ctx `nl-oven`.

### Procedure

All steps are **non-mutating reads**. Secret values must never be printed into
issues, comments, or logs.

```bash
# 1) Fetch jobspec — requestData / observationSource via node API
kubectl exec <chainlink-data-feeds-*-pod> -n chainlink-data-feeds -c node -- sh -c '
  E=$(sed -n 1p /mount/.api); P=$(sed -n 2p /mount/.api); CJ=$(mktemp)
  curl -s -c $CJ -X POST localhost:6688/sessions \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$E\",\"password\":\"$P\"}" >/dev/null
  curl -s -b $CJ localhost:6688/v2/jobs/<jobID>; rm -f $CJ'
# Parse .data.attributes.pipelineSpec.dotDagSource for the bridge request body

# 2) Replay exact requestData against the EA
kubectl port-forward -n chainlink-ea svc/<ea> 18080:8080 &
curl -s -X POST localhost:18080 \
  -H 'Content-Type: application/json' \
  -d '<exact requestData from step 1>'
# kill %1 after to clean up port-forward

# 3) Provider coverage — Coin Metrics (safe REST catalog endpoint)
API_KEY=$(kubectl get secret <ea-secret> -n chainlink-ea -o json |
  jq -r '.data.API_KEY|@base64d')
curl -s \
  "https://api.coinmetrics.io/v4/catalog/markets?base=<sym>&api_key=$API_KEY"
# Check market max_time recency
```

### GSR safety caveat

**The GSR direct provider hit is NOT routine.** The only direct path reuses
the live node's single shared prod credential (`WS_USER_ID` + `secret/gsr`
`WS_PRIVATE_KEY`) on `wss://oracle.prod.gsr.io/oracle`. A second concurrent
session can knock the live EA off its (already-flapping) socket on a revenue
feed. Treat as a coordinated test only, or ask GSR support instead.

### Hand-off

After collecting investigation results:
1. **Post a summary to Slack** (#chainlink-ops or the relevant channel) so the
   team has context.
2. **File a Jira issue** (project OPS or CLL) with the findings, or add them
   to the existing issue.
These steps are manual — no automation wraps them yet.
