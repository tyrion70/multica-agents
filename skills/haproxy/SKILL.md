---
name: haproxy
description: Work on ChainLayer's RPC load balancing — the bare-metal HAProxy fleet (hapee, backends.yaml, *.rpc.cinternal.com) and the k8s HAProxy Ingress Controller (ingress-haproxy ns, haproxy-backend chart/controller). Use when adding or changing a chain backend, debugging 503s/health checks on rpc.cinternal.com hostnames, or extending the k8s IC. All changes are GitOps — never live-edit the dataplane or IC ConfigMap.
---

# HAProxy / RPC load balancing

Two coexisting systems. Identify which one the hostname lives on first:

- **Bare-metal fleet (authoritative for prod RPC)**: `*.rpc.cinternal.com` →
  VIP `89.149.218.7` (haproxy1/2, hapee 2.4). Config repo: `haproxy-gitlab`
  (`backends.yaml` → jinja → `hapee-lb.cfg`).
- **k8s Ingress Controller** (Phase 1 live, worldchain): `haproxy-ingress-rpc`
  in ns `ingress-haproxy`, VIP `10.3.1.54`, hosts `*.nl-oven.chainlayer.cloud`.

## Hard rules (both systems)

- **Never poke the dataplane API live** (port 5555) — all bare-metal changes
  go through a `haproxy-gitlab` MR; CI runs `haproxy -c`; `pushconfig.sh`
  deploys to both LBs.
- **Never live-patch the IC ConfigMap** — selfHeal reverts it in ~1 min
  (root-app-managed, can't disable). Commit to git and let Argo sync.
- Credentials (dataplane basic-auth `haproxy-api-auth`, QuickNode/Ankr tokens)
  live in GCP Secret Manager; human lookups → **bitwarden** skill (`company`).

## Bare-metal fleet

### backends.yaml schema

```yaml
- name: <service>
  channels:
    - {name: '', port: 8545, ws_upgrade: true, ws_port: 8546, check_port: "check port 11001"}
  internal:
    nodes:
      - {name: <hostname.chosts.io>, ip: "<ip>", location: NL2|NO1|DE1|FI1}
  external:                          # optional → *-ext-rpcN/-wsN backends
    nodes:
      - {host: rpc.ankr.com, path_prefix: <chain>/<key>, port: 443}
```

Local render check: `python3 backends.py --dc NL2 -o /tmp/out.cfg`.

### Operational facts

- **Health checks**: `check port 11001` = the chainlayer health-agent
  (`tyrion70/health-agent-new`, deployed by the chain's `*-infra` ansible repo,
  `group_vars/healthcheck.yml`). **No infra repo / no healthcheck.yml → no
  agent → backend stays `DOWN / L4CON` → 503s.** Fallback: `check_port:
  "check port 8545"` (plain L4; loses behind-tip semantics) — precedent:
  base-mainnet / mantle-mainnet full-node-api.
- Diagnose: `curl -s 'http://haproxy.cinternal.com:9600/hapee-stats;csv' | awk -F, '$1 ~ /^<chain>/'`
  — `last_chk = Connection refused` → agent missing; confirm `nc -zv <ip> 11001`.
- **Naming**: `<chain>` backend already includes the archive node (round-robin);
  `<chain>-archive` is archive-only. Don't put both in a chainlink config.
  Exception: `eth-main-execution[-archive]` are separate real pools.
- **Routing flags**: `?external=1` force external, `?noexternal=1` opt out of
  fallback — literal-`1` matches only. Internal rules use `nbsrv gt 0`; empty
  pool falls through to external fallback.
- **`balance source`**: one workstation IP always hits one backend — probe from
  multiple pods/IPs. Stickiness persists even when the target is in maint.
- **WS hardening**: `srvtcpka` (idle 30s/intvl 10s/cnt 3) in defaults is the
  kernel-level dead-backend detector for WS tunnels — don't remove it; it's
  what saves chainlink from Cilium conntrack-pinned dead sockets.
- A bare IP in backends.yaml without a `*.chosts.io` name is suspicious — the
  VM may have been repurposed. Verify before reusing.
- Shared Ankr key for externals: `rpc.ankr.com/<chain>/4d75a29…` (see global notes).

### Recurring workflow: add a chain backend

1. Confirm the health agent exists on each node (`nc -zv <ip> 11001`) or plan
   the `check port 8545` fallback.
2. Add the `backends.yaml` entry (schema above), render locally, MR
   (Linear issue first — `linear-company` skill; MR rules — `git-mr` skill).
3. After deploy, verify via the stats CSV; expect `L7OK` (agent) or `L4OK`.
4. If chainlink consumes it: set `IsLoadBalancedRPC = true` in the node TOML
   (see `chainlink-ops` skill).

## k8s Ingress Controller (Phase 1+)

Layered design: op-reth chart `haproxy:` block → `haproxy-backend` library
chart (Backend CRD + Ingress + intent ConfigMaps) → `haproxy-backend-controller`
materializes EndpointSlices (service unions, VM endpoints) and the `-ext`
third-party backend. Host scheme: `<chain>` (http+ws Upgrade-switched, union
pool), `<chain>-node`, `<chain>-archive[-node]`.

Hard-won facts — don't re-learn:

- **`check-sni <host>` is mandatory for Cloudflare-fronted upstreams**
  (QuickNode/Ankr) — health checks send no SNI otherwise → `L6RSP` on every
  probe while real traffic works.
- **`frontend-config-snippet` is a ConfigMap setting, NOT an Ingress
  annotation** (annotation silently ignored).
- IC doesn't publish LB status on `cr-backend` Ingresses → set
  `external-dns.alpha.kubernetes.io/target` (= `haproxy.dnsTarget`) or
  external-dns deletes the records.
- ArgoCD excludes `discovery.k8s.io/EndpointSlice` cluster-wide — that's WHY
  the controller materializes slices imperatively.
- Slice port **names must match** the op-reth Service ports (`jsonrpc` 8545,
  `websocket` 8546, `node-http` 9545) or the IC won't fold endpoints in.
- Backend names are deterministic `<ns>_svc_<service>_<portname>` — the
  dispatch snippet depends on that.

Where things live: library chart `helm-charts/charts/haproxy-backend`; op-reth
integration `charts/op-reth/templates/haproxy.yaml`; per-chain enable in the
appset env YAMLs; dispatch snippet `clusters/argo-apps/ingress-haproxy/app-rpc.yaml`;
controller `k8s-apps/apps/haproxy-rpc/controller/`. Dev notes + next steps:
`projects/haproxy/CLAUDE.md`. Team how-to: `docs.chainlayer.cloud/infra/haproxy/`.

Debug commands:

```bash
CTX=nl-oven; NS=ingress-haproxy
POD=$(kubectl --context $CTX -n $NS get pod -l app.kubernetes.io/instance=haproxy-ingress-rpc -o name | head -1)
kubectl --context $CTX -n $NS exec "$POD" -- sh -c 'echo "show servers state" | socat /var/run/haproxy-runtime-api.sock stdio'
kubectl --context $CTX -n $NS logs deploy/haproxy-backend-controller
```

## Permission model

✅ Without asking: stats CSV/HTML reads, Prometheus :8405 metrics, local
renders, `show servers state`, controller logs, nc/curl probes.

🔶 GitOps: every backend/frontend/chart change = MR (haproxy-gitlab or
k8s-apps/helm-charts/clusters).

🛑 Ask first: anything through the dataplane API, draining/disabling servers,
deploying with `pushconfig.sh`, changing the dispatch snippet (affects every
chain on the IC at once).
