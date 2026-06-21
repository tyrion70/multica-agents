---
name: company-k8s
description: Operate ChainLayer's Kubernetes clusters (nl-oven, nl-spud, no-fryer). Use whenever running kubectl against company clusters, debugging pods/chain nodes/ArgoCD apps, changing manifests in k8s-apps, or investigating cluster storage/monitoring. Detects read-only vs writeable access from the Tailscale login and defines exactly which actions need user permission.
---

# ChainLayer Kubernetes operations

## Step 0 — detect your access level (always do this first)

Run `scripts/detect-access.sh` (relative to this skill directory). It prints a final
`ACCESS=WRITEABLE|READONLY|NONE` verdict. Do not assume; detect.

How it works — and what to do if the script is unavailable:

1. **Tailscale identity is the k8s identity.** All kubectl contexts point at the
   Tailscale operator API proxy (`https://tailscale-operator-<cluster>.java-moth.ts.net`,
   kubeconfig user `tailscale-auth`). The proxy impersonates whoever the host's
   Tailscale login is.
   - `tailscale status --json | jq '.Self | {HostName, Tags}'` plus the matching
     `.User[]` entry gives the login.
   - Personal login (`*@chainlayer.io`, no tags) → impersonated as that user,
     normally `system:masters` → **WRITEABLE**.
   - Tagged device (owner `tagged-devices`, e.g. `claude-readonly-01`) → no personal
     grant; those hosts carry static **view-only ServiceAccount kubeconfigs**
     (`claude-readonly`, ClusterRole `view`) → **READONLY**.
2. **RBAC is authoritative, Tailscale is the hint.** Confirm per cluster with
   `kubectl --context <ctx> auth whoami` and `kubectl --context <ctx> auth can-i create pods -A`.
3. A context that doesn't resolve (e.g. `tailscale-operator-no-fryer...` failing DNS)
   is **unreachable from this host**, not broken — say so and move on; don't retry
   with other credentials.

### Behavior in READONLY mode

- Never attempt mutations — not even "harmless" ones. They will fail, and trying
  signals you ignored the access model.
- The `view` ClusterRole **excludes Secrets** by design. Don't query them and don't
  work around it; secret inspection happens from a writeable workstation.
- Your deliverable is findings plus the **exact commands or k8s-apps MR diff** a
  writeable operator should apply. Write them out fully, ready to paste.
- Read-only hosts typically only have `nl-oven` + `nl-spud` kubeconfigs; `no-fryer`
  is out of scope there.

## Permission model in WRITEABLE mode

Three tiers. When in doubt, treat an action as the more restrictive tier.

### ✅ Proceed freely (no permission needed)

- All reads: `get`, `describe`, `logs`, `events`, `top`, `auth can-i`, `kubectl get
  applications -n argocd`, CRD inspection.
- `port-forward` for reading metrics/APIs.
- Read-only `exec` into pods (e.g. `curl localhost:6060/metrics`, `ls`, `du`) — never
  state-changing commands via exec.
- Reading a Secret **when debugging requires it** — mention in your report that you did.
- Local renders/diffs: `helm template`, `kustomize build`, `python3 backends.py`.

### 🔶 Proceed via GitOps — the change itself needs no permission, the path is fixed

Everything on these clusters is ArgoCD-managed from the `k8s-apps` repo. **Any
persistent spec change goes through an MR, never `kubectl apply/edit/patch`:**

- Helm values, image bumps, env vars, replica counts, resources, PVC sizes,
  new environments — even a one-line `persistence.size` bump = fresh branch off
  `origin/main`, MR with template, merge, let Argo sync (~3 min git poll).
- Create the Linear issue **before** coding and use its branch name.
- PVC online expansion: `kubectl patch pvc` is permitted as immediate insurance,
  **always followed by the MR** so the Argo source of truth stays aligned.

### 🛑 Ask the user first (even with full admin)

Anything destructive, hard to reverse, or touching live revenue infrastructure:

- **Deleting anything**: pods, PVCs, PVs, VolumeSnapshots, Secrets, namespaces,
  ArgoCD Applications. (Known exceptions below still get a one-line confirmation.)
- **Live mutations**: `kubectl apply/edit/patch` on Argo-managed resources, scaling
  up/down, `rollout restart`, node `cordon`/`drain`.
- **Chain-node StatefulSets**: restarting or deleting a chain-node pod can mean
  hours-to-days of resync; deleting its PVC without a VolumeSnapshot means a full
  re-bootstrap from snapshot. Always snapshot first, always ask.
- **Chainlink namespaces** (`chainlink-*`): these are live oracle nodes earning
  revenue. Any mutation — pod delete, config change, secret refresh — gets explicit
  confirmation with a one-sentence blast-radius statement.
- **ArgoCD sync/rollback** of anything not merged to main.

Known pre-approved patterns (confirm intent in one line, then proceed):

- **OrderedReady catch-22**: a config fix is merged but the StatefulSet won't roll
  because pod-0 is unready *because of the bug being fixed* → `kubectl delete pod <sts>-0`
  is the documented break-glass. PVC persists. Snapshot first if data is precious.
- **ESO secret refresh**: delete the ESO-produced Secret via the ArgoCD UI
  (Background delete) → ESO recreates in ~5 s; then `rollout restart` the consumer.
  User RBAC may block direct secret deletion — the ArgoCD UI path is the standard one.

### Credentials during k8s work

Machine-consumed secrets reach pods via GCP Secret Manager + ExternalSecrets —
never hand-create k8s Secrets with literal values. When YOU need a credential
mid-task (Grafana token, registry login, API key), use the **bitwarden** skill
(`company` folder) rather than hunting through dotfiles.

### Never (regardless of access)

- `kubectl apply` hand-edited manifests onto Argo-managed resources as a "permanent"
  fix — Argo will revert it and the cluster silently drifts until then.
- Delete a chain-node PVC without a fresh VolumeSnapshot.
- Push credentials/tokens anywhere outside GCP Secret Manager.

## The setup (what you're operating)

### Clusters

| Context | Role | Notes |
|---|---|---|
| `nl-oven` | Primary production (Amsterdam) | Egress NAT `89.149.216.9`; most workloads |
| `nl-spud` | Secondary (Amsterdam) | |
| `no-fryer` | Oslo | Operator proxy not resolvable from all hosts |

All Talos Linux on Proxmox, reached only via Tailscale — **nothing kubectl-based can
run in a cloud agent/routine** (no tailnet there). kubectl contexts are named after
the clusters.

### GitOps triangle (all on GitLab, `chainlayer/infrastructure/kubernetes/`)

- **k8s-apps** — manifests, Helm values, ArgoCD ApplicationSets. *The* source of truth.
- **helm-charts** — custom charts: `op-stack` (geth chains), `op-reth` (reth chains),
  `base-node` (base-reth), `chainlink-node`, `snapshot-manager`, external-adapters.
- **clusters** — cluster infra + ArgoCD bootstrap.

Renovate auto-bumps digest-pinned internal images (`latest@sha256:…`) in k8s-apps
after a code MR merges — don't open manual bump MRs for those.

### Chain nodes (op-stack / op-reth)

Three ArgoCD source layouts; check which manages an app via
`kubectl get application -n argocd <name> -o jsonpath='{.metadata.ownerReferences[0].kind}'`
(`ApplicationSet` vs empty = standalone legacy):

1. `appsets/op-reth/<chain>-reth/<network>/` — current pattern, fans out
   `*-full-node` + `*-archive` apps from `environments/*.yaml`.
2. `appsets/op-stack/<chain>/<network>/` — geth chains (blast, celo, mantle).
3. `apps/op-stack/<chain>/<network>/` — legacy standalone kustomize Applications.

High-value gotchas (full details in the operator's global CLAUDE.md if present):

- **geth archive nodes need `execution.state.scheme: hash` + `--snapshot=false`**;
  without the former the chart silently drops `--gcmode=archive` and the node prunes.
- **`OrderedReady` blocks rolling updates** when pod-0 is unready — see break-glass above.
- Snapshot bootstrap URLs are only consumed when `/data/.initialized` is absent.
- reth `eth_blockNumber` is stuck at the staged-sync checkpoint until the Finish
  stage — not the live tip.
- `--rollup.historicalrpc` only proxies blocks the node truly lacks; it does NOT
  forward empty-but-wrong local log-index results.

### Chainlink

Namespaces: `chainlink` (shared svcs), `chainlink-{automation,bootstrap,ccip,cre,cre-df,data-feeds,data-streams,keystone,streams,database,ea,vpn}`.
Pod containers: `node` (use `-c node` for logs), sidecars `auto-approve`/`registry`;
config rendered to `/mount/config.toml`. RPC config lives as TOML-in-YAML under
`k8s-apps/appsets/chainlink/decentralized-oracle-network/*/nodes/*.yaml` — set
`IsLoadBalancedRPC = true` for any `*.rpc.cinternal.com` URL, and remember old
images crashloop on unknown TOML keys (strict decoder).

### Storage (LINSTOR / Piraeus)

- Classes: `linstor-double-replica` (default), `linstor-archive`, `linstor-archive-zpool`
  — all support **online expansion** (patch PVC + MR, no pod restart).
- Archive classes are replica-1 on a single node; capacity is bounded by the
  most-free archive node, not the sum. Inspect:
  `kubectl -n piraeus-datastore exec deploy/linstor-controller -c linstor-controller -- linstor sp l`

### Monitoring

- kube-prometheus-stack per cluster (10s scrape, all ServiceMonitors auto-picked-up);
  Thanos sidecar → bare-metal Thanos Query; Grafana Cloud (`chained.grafana.net`) is
  the visualization layer.
- Chain-node health: `node_agent_*` metrics from the healthcheck sidecar
  (`endpoint="healthcheck-metrics"`); `node_agent_last_known_state_active=1` means
  the RPC poll is failing and values are stale. Rollup-layer peers come from op-node
  (`op_node_default_p2p_peer_count or p2p_peers`), not `node_agent_peer_count`.
- PrometheusRules: `k8s-apps/monitoring/prometheusrules/`, deployed via `apps-monitoring`.

## Reporting discipline

- State your detected access level at the start of any cluster work.
- After any live mutation (insurance patch, break-glass pod delete), report it
  explicitly and open/link the aligning MR before calling the task done.
- If tests/probes fail or a cluster is unreachable, say so plainly with output.
