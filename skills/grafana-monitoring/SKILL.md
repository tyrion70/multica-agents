---
name: grafana-monitoring
description: Build or modify Grafana dashboards, run PromQL queries, render panels, manage Prometheus alerting, and apply/expire Alertmanager silences for ChainLayer. Use whenever querying metrics, creating/updating dashboards on chained.grafana.net, debugging why a panel/alert shows wrong data, adding PrometheusRules, or operating the two monitoring stacks (bare-metal monitoring2 + k8s kube-prometheus). Knows the stable datasource UIDs, the node_agent metric semantics, the tailnet AM paths, and the table-transform quirks that have burned hours before.
---

# Grafana / Prometheus / monitoring

## Two monitoring stacks — read before any silence or rule change

ChainLayer runs **two coexistent stacks**. Picking the wrong one silences nothing
or pushes a rule to the wrong repo — always identify which stack owns the alert
first.

### A. monitoring2 — bare-metal (Ansible/Jenkins, repo `infrastructure/monitoring2`)

- **Per-DC Prometheus pairs** (nl2/no1/de2, 15s scrape) + **3-peer HA
  Alertmanager mesh** + **Thanos** query+ruler+sidecars + per-site Grafana
  (nginx :80) + Loki/Promtail.
- **Alertmanager peers** (plain HTTP, no auth, tailnet-direct — any peer, silences
  gossip across the mesh):
  - `http://alertmanager-node-1a-nl2v.chosts.io:9093`
  - `http://alertmanager-node-2a-no1v.chosts.io:9093`
  - `http://alertmanager-node-3a-de2v.chosts.io:9093`
- **Prometheus** `:9090` on the same hosts (e.g. `prometheus-node-1a-nl2v.chosts.io:9090`).
- **Targets** = file-SD under `configuration/sites/<dc>/targets/*.yml` (filename
  = job name). **Rules** = `configuration/{common,thanos}/alerts/` + per-site.
- **Deploy** = commit to `main` → Jenkins → Ansible `serial: 1`.
- **Routes to:** Slack + PagerDuty.
- **Authoritative for:** bare-metal hosts, chain nodes, infra exporters. This AM
  mesh is the production paging path for bare-metal/infra alerts.

### B. k8s — kube-prometheus-stack (repo `k8s-apps`, Argo app `apps-monitoring`)

- Per-cluster Prometheus + Alertmanager: `alertmanager-nl-oven` / `alertmanager-nl-spud`,
  `prometheus-nl-oven` / `prometheus-nl-spud` — first-class tailnet devices.
  Thanos sidecars → bare-metal Thanos Query.
- **Targets** = ServiceMonitors/PodMonitors (auto-discovered,
  `*SelectorNilUsesHelmValues: false`, 10s scrape, 14d retention).
- **Rules** = `PrometheusRule` YAML in `k8s-apps/monitoring/prometheusrules/`
  via the `apps-monitoring` Argo app — MR, not UI edits (`git-mr` skill).
- **Routes to:** Slack (`#xmonitoring-kubernetes`, `#xmonitoring-fullnodes`),
  incident.io, PagerDuty.
- **Authoritative for:** in-cluster workloads.

### C. Grafana Cloud `chained.grafana.net` — dashboard layer

Queries bare-metal Thanos via PDC. **This is where dashboards live.** Bare-metal
per-site Grafana is data-source/legacy layer only.

## How ops differ by stack

| Operation | monitoring2 (bare-metal) | k8s |
|---|---|---|
| **Silence** | `POST /api/v2/silences` on any AM peer above (plain HTTP, no auth) | `POST /api/v2/silences` on `alertmanager-nl-oven` or `alertmanager-nl-spud` (tailnet, operator-exposed, needs SNI/hostname) |
| **Delete silence** | `DELETE /api/v2/silence/<id>` same peer | Same, same peer |
| **PromQL** | Prefer Grafana Cloud datasource-proxy; bare-metal Prometheus `:9090` or Thanos query for local debugging | Grafana Cloud datasource-proxy (k8s UID); or k8s Prometheus tailnet device directly |
| **New rule** | MR to `monitoring2` repo → Jenkins deploys | `PrometheusRule` YAML MR to `k8s-apps/monitoring/prometheusrules/` → Argo |
| **Route/receiver edit** | MR to `monitoring2` (Alertmanager config) | MR to `k8s-apps` Alertmanager config |

## ⚠️ AM write access — the only guard is your discipline

The monitoring2 Alertmanager is **reachable write-enabled and unauthenticated**
over the tailnet (no CF Access, no token). The scoped + time-boxed +
issue-referenced silence discipline below is the **only** protection against
accidentally suppressing real pages.

**Every silence MUST:**
- Have an explicit `endsAt` (max duration appropriate to the task — never open-ended).
- Use the **narrowest possible matchers** (specific `alertname`, `instance`,
  `job` — never a blank `{}` that catches everything).
- Reference the driving issue in `comment` (e.g. `CHA-56: migration silence`).

**Example silence payload** (replace matchers and duration):
```bash
curl -X POST http://alertmanager-node-1a-nl2v.chosts.io:9093/api/v2/silences \
  -H "Content-Type: application/json" \
  -d '{
    "matchers": [{"name": "alertname", "value": "NodeExporterDown", "isRegex": false},
                 {"name": "instance",  "value": "myhost:9100",       "isRegex": false}],
    "startsAt": "2026-06-19T18:00:00Z",
    "endsAt":   "2026-06-19T22:00:00Z",
    "createdBy": "claude-agent",
    "comment":  "CHA-56: migration silence — remove after restore"
  }'
```

Verify: `GET /api/v2/silences` on the same peer; confirm it gossips to the other
two within ~30s. Delete: `DELETE /api/v2/silence/<id>`. Silences gossip across
all 3 peers — write to any one, read from any one.

## Architecture (who scrapes what)

- **kube-prometheus-stack per cluster** (10s scrape, 14d retention); all
  ServiceMonitors/PodMonitors auto-discovered (`*SelectorNilUsesHelmValues: false`).
- **Thanos sidecars** → bare-metal Thanos Query for cross-DC; bare-metal
  Grafana (`grafana.cinternal.com`) is data-source layer only.
- **Grafana Cloud `chained.grafana.net` is where dashboards live** (via PDC).
- Alertmanager → Slack (`#xmonitoring-kubernetes`, `#xmonitoring-fullnodes`),
  incident.io, PagerDuty. **PrometheusRules**:
  `k8s-apps/monitoring/prometheusrules/` via the `apps-monitoring` Argo app —
  alert changes are k8s-apps MRs (`git-mr` skill), not UI edits.

## API access

- Service-account token: `~/claude/.mcp.json` →
  `mcpServers.grafana.env.GRAFANA_SERVICE_ACCOUNT_TOKEN` (`glsa_…`). Works for
  MCP and direct curl (`Authorization: Bearer`). If missing/expired → the
  **bitwarden** skill (`company` folder); read-only hosts have a Viewer token
  at `/etc/claude-readonly/creds/grafana-token`.
- Base `https://chained.grafana.net/api`:
  - `GET /datasources` · `GET /dashboards/uid/<uid>` ·
    `POST /dashboards/db` (`{"dashboard": …, "overwrite": true, "message": "…"}`)
  - Ad-hoc PromQL: `GET /api/datasources/proxy/uid/<ds>/api/v1/query?query=…`
  - Panel PNG: `GET /render/d-solo/<uid>/<slug>?panelId=N&width=W&height=H&from=…&to=…&_=<ts>`
    (`&_=` busts the render cache).

### Stable datasource UIDs

| UID | Name |
|---|---|
| `deexgsum1bz7ka` | prometheus-nl-oven |
| `df37c3m1043r4a` | prometheus-nl-spud |
| `beexh7l99aq68b` | prometheus-no-fryer |
| `cepbu6izhi3nke` / `aepc7djwfjeo0d` / `fepc79v1myg3ke` | thanos-de2 / nl2 / no1 |
| `grafanacloud-prom` | Cloud's own scrape |

## Metric semantics worth knowing before you query

- **Chain-node health = `node_agent_*`** (healthcheck sidecar, filter
  `endpoint="healthcheck-metrics"` for op-stack/op-reth charts; legacy chart
  family uses `endpoint="agent-metrics"`). Key signals:
  - `node_agent_health_status{module="evm"}` 1/0; `node_agent_block_lag_seconds`;
    `node_agent_height_stagnant`.
  - **`node_agent_last_known_state_active = 1` means the RPC poll is FAILING**
    and values are stale replays — check it before trusting height/peers.
  - `node_agent_peer_count` is **execution-layer** peers — legitimately 0 on
    consensus-layer-synced op-stack chains. Rollup peers:
    `op_node_default_p2p_peer_count{...} or p2p_peers{...}` (op-node :7300).
- A *different* image literally named `healthcheck-agent` emits
  `healthcheck_ok`/`latest_block_height` with NO `node_agent_*` and no
  `blockchain` label → invisible to the fleet dashboard. If a chain is missing
  from `opstack-nodes-overview`, check which image its sidecar runs.
- Adapter traffic: ALWAYS both `http_request_duration_seconds_sum` AND
  `bg_execute_total` (see `chainlink-ops` skill).
- Topup balances: `chainlink_key_balance` / `chainlink_key_min_balance` with
  the hand-curated `description` label (`Safe`, `Admin`, `Topup Caller`,
  `Excluded`, `Automation` are the canonical exclusion values).

## Table-panel transform quirks (hours lost here — read before building tables)

With `joinByField` (outer join) + `organize`:

- The first query's non-key fields keep suffix `" 1"` (`blockchain 1`), but
  sometimes the unsuffixed name survives too — positioning surprises follow.
- `indexByName` **silently ignores** names that don't exist in the joined
  frame — a no-op reorder means your field name is wrong.
- `renameByName`/`renameByRegex` rename BEFORE later transforms see the field;
  field-config override matchers match the **renamed** name, but use the
  override's `displayName` property for the column header.
- Deterministic column order: insert a `renameByRegex` before `organize` so
  every field has a unique name, then position by that.

## Recurring workflows

- **New dashboard**: build JSON model → `POST /dashboards/db` with a commit-style
  `message` → verify with a `/render/d-solo` PNG of the key panel(s) and look at
  the image yourself before declaring it done.
- **New alert**: PrometheusRule YAML in `k8s-apps/monitoring/prometheusrules/`
  → MR → verify it appears in the cluster's Prometheus rules UI; route check in
  Alertmanager config. Off-minute `for:`/eval choices beat :00 herd behavior.
- **Ad-hoc investigation**: prefer the datasource-proxy query endpoint over
  spinning up port-forwards; pick the cluster's UID from the table above.

## Permission model

✅ Without asking: all reads (alerts, silences, status, targets, rules, PromQL,
dashboard GETs, panel renders); creating NEW dashboards (mention the URL);
applying/expiring **scoped, time-boxed silences** that match narrowly (explicit
`endsAt`, specific matchers, issue reference in `comment`).

🔶 GitOps: PrometheusRules / Alertmanager routing = MR on the correct repo
(`monitoring2` for bare-metal, `k8s-apps` for k8s). Never hand-edit live config.

🛑 Ask first: broad paging suppression, route/receiver edits, anything that
disables or hides monitoring, overwriting/deleting an EXISTING dashboard you
didn't create this session.

🚫 Never: read/copy/log `~/.claude/.credentials.json` or tailscaled state; paste
any token/secret into an issue; touch non-monitoring infra; deploy to monitoring2
outside its Jenkins/Ansible pipeline.
