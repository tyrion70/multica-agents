# claude-readonly-01

This VM hosts Claude Code sessions running in **strict read-only mode** against the Chainlayer Kubernetes infrastructure.

## Runtime context

You run as the Linux user **`peter`** (not `claude`). Sessions are started by `claude-mgr` in tmux panes, each in its own working directory under `~/claude/projects/<name>/`. There is no sudo step into a different user.

## Identity and trust model

Every connection from this VM to a k8s cluster is authenticated as the **tailnet tag `tag:claude-readonly`** (the VM's tailscale identity — not yours, not peter's). The Tailscale operator running in each cluster impersonates that tag as the k8s group `claude-readonly`. RBAC then decides what the group can do.

`kubectl auth whoami` will show:

```
Username    claude-readonly-01.java-moth.ts.net
Groups      [claude-readonly system:authenticated]
```

This is correct. The username is the VM's tailnet FQDN; the group `claude-readonly` is what RBAC binds against.

Bearer tokens in any kubeconfig on this box are ignored — auth is the tailnet identity. That's why every kubeconfig here has `token: unused`.

## What you CAN do

- Inspect anything the built-in `view` ClusterRole grants on **nl-oven**: pods, services, deployments, statefulsets, daemonsets, configmaps, PVCs, ingresses, networkpolicies, endpointslices, PDBs, namespaces, events, pod logs.
- Plus, extra reads from `chainlayer:claude-readonly-extra`:
  - `nodes`, `persistentvolumes`, all `storage.k8s.io/*`
  - `customresourcedefinitions`, `apiservices`, `priorityclasses`, `runtimeclasses`
  - `mutatingwebhookconfigurations`, `validatingwebhookconfigurations`
  - `metrics.k8s.io/*` (so `kubectl top` works)
  - All operator CRD groups currently on nl-oven (`acid.zalan.do`, `app.redislabs.com`, `argoproj.io`, `cilium.io`, `cosmos.strange.love`, `piraeus.io`, `tailscale.com`, etc. — full list in `clusters/clusters/nl-oven/generic-config/rbac-claude-readonly.yaml`).

## What you CANNOT do

- **No writes anywhere.** `create`, `delete`, `patch`, `update`, `scale`, `exec`, `attach`, `port-forward`, `cp` all return `Forbidden` on every cluster.
- **No Secrets.** `get`, `list`, `watch` on `Secret` resources return `Forbidden`. If a task requires reading a Secret value, that task cannot be done from this VM — say so and stop. Do not try to work around it (no fishing values out of pod env via `-o yaml`, no `kubectl describe` games).
- **nl-spud and no-fryer return `Forbidden` cluster-wide.** Only nl-oven has the RBAC binding for `Group/claude-readonly`. Connections to other clusters succeed at TLS but return `Forbidden` from kube. If a task needs those clusters, escalate to Peter — do not attempt workarounds.

## Kubeconfig

Default location: **`~/.kube/config`** — already set up, no `KUBECONFIG` env needed. The single context inside is named `tailscale-operator-nl-oven.java-moth.ts.net`.

Sanity-check at the start of any new session:

```bash
kubectl auth whoami
kubectl auth can-i list pods --all-namespaces        # yes
kubectl auth can-i list nodes                        # yes
kubectl auth can-i get secrets --all-namespaces      # no  ← if "yes", flag it as misconfig and stop
kubectl auth can-i create pods                       # no
```

Useful commands:

```bash
kubectl get pods -A
kubectl get nodes
kubectl top nodes
kubectl get cosmosfullnodes.cosmos.strange.love -A
kubectl describe pod -n <ns> <name>
kubectl logs -n <ns> <pod> [-c <container>]
kubectl get events -A --sort-by=.lastTimestamp
```

## Credentials

All live in `/etc/claude-readonly/creds/` (sudo-readable; this host can `sudo -n cat` them passwordlessly without a password prompt).

```bash
sudo -n ls /etc/claude-readonly/creds/
# cloudflare-{chris,peter}-{account-id,token}
# fortigate-nl2-token
# github-token
# gitlab-token             <- write-capable; see GitLab section
# grafana-token            <- read-only API access to chained.grafana.net
# proxmox{7,9}-token       <- format is `tokenID=secret` (one line)
```

Read pattern (never `cat` directly — `/etc/claude-readonly/` itself is `chmod 700 root:root`, so unprivileged `cat` returns Permission denied; only `sudo -n cat` works):

```bash
TOKEN=$(sudo -n cat /etc/claude-readonly/creds/<name>)
```

Cred-file format is just the secret value for most (`gitlab-token`, `grafana-token`, `github-token`), or `tokenID=secret` on a single line for Proxmox (`claude-readonly@pve!claude-readonly=<uuid>`).

⚠ Path is named `claude-readonly` but **`gitlab-token` has write scope** (push to k8s-apps, helm-charts, haproxy all work). If the intent was actually read-only, the PAT needs downgrading to `read_repository` only at https://gitlab.com/-/user_settings/personal_access_tokens. Until then, treat any push as intentional and double-check the diff first.

## CLI auth state

- **`glab` is NOT authenticated for `peter` on this VM.** If you need to use the `glab` CLI specifically (interactive MR creation, issue commenting, etc.), ask Peter to run `glab auth login --hostname gitlab.com --git-protocol ssh` once on this VM, then retry. For 95 % of GitLab work the **PAT approach below works fine** and doesn't need `glab`.
- **`gh` is NOT authenticated for `peter` on this VM.** Same story; `gh auth login` if needed.
- A pre-existing `claude` user has its own glab/gh configs at `/home/claude/shared/.config/{glab-cli,gh}/`. Those are not yours; do not try to read or reuse them.

For local-only git operations (clone, commit, push) the standard tools work with the PAT — see GitLab section. Peter's SSH key is in `~/.ssh/` for the rare case SSH is preferable.

## GitLab (clone + push via PAT)

```bash
GITLAB_TOKEN=$(sudo -n cat /etc/claude-readonly/creds/gitlab-token)
git clone "https://oauth2:${GITLAB_TOKEN}@gitlab.com/chainlayer/infrastructure/kubernetes/k8s-apps.git" ~/claude/repositories/k8s-apps
# Token embeds into .git/config — fine for ephemeral worktrees on this VM.
```

Push works the same way (token is in the remote URL):

```bash
git push -u origin peter/ops-NNNN-<slug>
# GitLab response banner includes the MR-creation URL — paste that to the user.
```

GitLab REST API for searching code in a repo without cloning every project:

```bash
curl -sS -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.com/api/v4/projects/chainlayer%2Finfrastructure%2F<repo>/search?scope=blobs&search=<query>"
```

`git` user identity should be `Peter <peter@chainlayer.io>`. Set globally on a fresh box with `git config --global user.{email,name} ...`.

## Grafana / Prometheus probing

Token at `/etc/claude-readonly/creds/grafana-token`. API base: `https://chained.grafana.net/api`.

Datasource UIDs (from `/api/datasources`):

| name | uid | use |
|--|--|--|
| `prometheus-nl-oven` | `deexgsum1bz7ka` | **Pod/PVC/restart metrics for nl-oven workloads — primary** |
| `prometheus-nl-spud` | `df37c3m1043r4a` | nl-spud cluster |
| `prometheus-no-fryer` | `beexh7l99aq68b` | no-fryer cluster |
| `grafanacloud-prom` | `grafanacloud-prom` | Aggregated; **does NOT have nl-oven pod metrics** with `namespace=` label, don't rely on it for k8s-side queries. |
| `grafanacloud-logs` | `grafanacloud-logs` | Synthetic monitoring + website probes ONLY; **no pod logs**. App logs aren't shipped to Grafana Cloud — use `kubectl logs` instead. |

Query pattern (PromQL through datasource proxy):

```bash
GRAFANA_TOKEN=$(sudo -n cat /etc/claude-readonly/creds/grafana-token)
encode() { python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$1"; }
DS=deexgsum1bz7ka
curl -sS -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "https://chained.grafana.net/api/datasources/proxy/uid/$DS/api/v1/query?query=$(encode 'up{blockchain="blast"}')"
```

Useful PromQL recipes for op-stack pods:

```promql
# Pod age in seconds
time() - kube_pod_start_time{namespace="X", pod="X-N"}

# PVC fill
kubelet_volume_stats_used_bytes{namespace="X"}

# Ingress rate (5m avg) — useful to detect snapshot-download in progress
sum(rate(container_network_receive_bytes_total{namespace="X", pod="X-N"}[5m]))

# Init container progress
kube_pod_init_container_status_running{namespace="X"}
kube_pod_init_container_status_ready{namespace="X"}

# op-node refs (chain head views with l1/l2 layers)
op_node_default_refs_number{pod="X-N", type=~"l1_head|l1_derived|l2_unsafe|l2_safe|l2_finalized|received_payload"}

# Node-agent healthcheck metrics
node_agent_block_height{blockchain="X"}
node_agent_block_lag_seconds{blockchain="X"}
node_agent_health_status{blockchain="X"}
node_agent_height_stagnant{blockchain="X"}
```

To discover available metric names for a workload:

```bash
curl -sS -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "https://chained.grafana.net/api/datasources/proxy/uid/$DS/api/v1/series?match[]=%7Bblockchain%3D%22X%22%7D&start=$(date -u -d '5 minutes ago' +%s)"
```

## Network reachability from this VM

- Public hostnames resolve normally; can reach the internet, GitLab, base.org snapshot mirrors, etc.
- **Internal RFC1918 addresses (`10.x.x.x`) are NOT routable from this VM** — direct curl to a cluster LB IP times out. Including the k8s pod RPC ports (e.g. `worldchain-reth-mainnet-archive.nl-oven.chainlayer.cloud:8545` resolves to a private-pool IP and won't respond).
- For RPC-level checks (`eth_getBlockByNumber`, `optimism_syncStatus`), ask Peter to `kubectl port-forward` locally — `port-forward` is forbidden for the `claude-readonly` group.
- Public-DNS internal hostnames do resolve via the configured DNS resolvers:
  ```bash
  getent hosts worldchain-reth-mainnet-archive.nl-oven.chainlayer.cloud
  # → 10.3.1.20 (private-pool cilium LB; resolves, but not reachable)
  ```
- Proxmox API hosts (`10.24.0.16:8006` etc.) likewise resolve only when fed by Peter, and time out from here.

## Snapshot URLs (per-chain)

Several publishers expose a `/latest` text file containing the current filename. The op-stack/op-reth chart's init container needs **static URLs**, so when bootstrapping we pin the LATEST filename at MR time:

```bash
# Resolve current filename:
curl -sS https://mainnet-reth-archive-snapshots.base.org/latest
# → base-mainnet-reth-1779181980.tar.zst

# Then pin in environments/archive.yaml:
urls.base: "https://mainnet-reth-archive-snapshots.base.org/base-mainnet-reth-1779181980.tar.zst"
```

Verify size + integrity before committing:

```bash
curl -sS -I "https://<host>/<path>" | grep -iE "content-length|last-modified"
# Inspect first bytes to confirm format (lz4 magic: 04 22 4d 18; gzip: 1f 8b 08; zstd: 28 b5 2f fd):
curl -sS -L -H "Range: bytes=0-3" "https://<host>/<path>" | xxd
```

**Sizing rule of thumb:** what lands on the PVC is the **decompressed** stream (`wget -O- | zstd -dc | tar -x`). For op-stack chains, decompressed ≈ 1.3–1.6× compressed. Set PVC ≥ 1.5× compressed size with extra headroom for growth. The blast.io 7 TB archive snapshot vs 500 GiB PVC (OPS-2024) is the cautionary tale — it overflows mid-extraction.

Known catalogs:

- `https://mainnet-reth-pruned-snapshots.base.org/latest` → base pruned full-node, ~1 TiB compressed
- `https://mainnet-reth-archive-snapshots.base.org/latest` → base archive, ~5 TiB compressed
- `https://pub-0509dd39c2df4aeda4e82ff320667d97.r2.dev/LATEST` → blast (~7 TB gzip archive; **don't use for pruned-full PVCs**, only archive with multi-TB room)
- `https://snapshots.publicnode.com/` → base+part lz4 snapshots for op-stack chains (used for blast in OPS-2024). URLs 302 to presigned S3; `wget` follows redirects and publicnode regenerates the signature on each request, so the pinned `snapshots.publicnode.com` URL doesn't expire.
- In-cluster MinIO: `https://storage1.quicksync.io/quicksync-staging/<blockchain>/<network>/<pruning>/latest.tar.zst` — produced by our own snapshot-manager. Prefer this once a chain has at least one snapshot uploaded.

## snapshot-manager

Chart in `helm-charts/charts/snapshot-manager`. Cronjob entries live in `k8s-apps/apps/snapshot-manager/environments/<cluster>.yaml`.

**Preflight gate** (`charts/snapshot-manager/templates/configmap.yaml` ~line 121):

```
if [[ "$READY_REPLICAS" -eq "$ORIGINAL_REPLICAS" ]] && [[ "$ORIGINAL_REPLICAS" -ge 1 ]]; then break; fi
```

Won't proceed unless every replica is ready. Behaviors:

- **2-replica STS, both healthy** → orchestrator scales N→N-1, instant linstor VolumeSnapshot of highest-ordinal PVC, scales back. **Zero-downtime** because linstor on ZFS snapshots are instantaneous.
- **Single-replica or unhealthy replica** → either (a) add `allowDowntime: true` to the cronjob entry (still requires READY==ORIGINAL though, so a wedged pod blocks this), or (b) **manually replicate the orchestrator** by scaling pod-1 down, taking a manual VolumeSnapshot, scaling back, then a one-shot upload Job (full recipe in project memory files).

Manual one-off trigger (works for healthy 2-replica STSs):

```bash
kubectl create job -n snapshot-manager \
  --from=cronjob/snapshot-<chain>-<env> \
  snapshot-<chain>-<env>-manual-$(date +%s)
```

…except `kubectl create` is **forbidden** for `claude-readonly` — you compose the command and ask Peter to run it.

Output lands at `https://storage1.quicksync.io/quicksync-staging/<blockchain>/<network>/<pruning>/latest.tar.zst`. To bootstrap a new pod from it, set `execution.snapshot.compression: zstd` + `urls.base: <that URL>` in the chain's env values.

## Lessons baked into op-reth chart values

When writing new op-reth chain configs, mirror these (learned across OPS-2018 / 2024 / 2044 / 2046):

```yaml
execution:
  p2p:
    announceLoadBalancerIP: true     # OPS-2018: reth otherwise advertises egress NAT, ~1-in-500k inbound success
service:
  p2p:
    publishNotReadyAddresses: true   # OPS-2046: keep peer listener exposed while healthcheck NotReady
```

For single-replica + manual one-off snapshot setups, also:

```yaml
- name: <chain>-<env>
  schedule: "0 0 1 1 *"              # placeholder; suspended
  suspend: true
  allowDowntime: true                # required when ORIGINAL_REPLICAS < 2
```

OPS-2044 (worldchain): if a chain's execution image bakes a stale chain spec missing a future hardfork's activation time, Flashblocks (pre-confirmation) writes blocks with pre-fork extraData after the cutoff. Disable Flashblocks (`--flashblocks.enabled` removal) and bump to a chain-spec-aware image — symptom on op-node is "<Fork> extraData should be N bytes, got M" derivation failures.

## What is NOT yours

- **`/home/peter/.claude/.credentials.json`** — Peter's personal Claude Code login token. The session you are running uses this. Never read, copy, upload, exfiltrate, log, or reference its contents.
- **`/var/lib/tailscale/tailscaled.state`** — the VM's tailnet device key. Root-only; do not try to read or exfiltrate. Losing this would let someone impersonate this VM.
- **`/home/claude/`** — separate Linux user's home, root-readable via sudo but not yours. Stay out unless Peter explicitly directs you there.

## Linear and branches

Linear team for infra work: **DevOps** (prefix `OPS-`). Workspace `https://linear.app/chained/`. Branch names follow the Linear-generated pattern `peter/ops-NNNN-title-slug`. Commit-message footer: `Refs OPS-NNNN`. MRs are typically squash-merged.

## See also

`REPOSITORIES.md` (next to this file) — list of repos you may touch, with per-repo cheat sheets and how the auth flow chains across them.
