# Repositories

Repositories you may need to read, clone, or open MRs against from this VM. All hosted on GitLab under `chainlayer/`.

> **Auth:** push + clone both work over HTTPS using the GitLab PAT at `/etc/claude-readonly/creds/gitlab-token` — see `CLAUDE.md → GitLab` for the `https://oauth2:$TOKEN@...` URL pattern. `glab` / `gh` CLIs are not authenticated; you don't need them for normal git work.

## Convention

Clones for active work go under `~/claude/repositories/<repo>/`. Inspect first (`ls ~/claude/repositories/` at the start of a session) — if already cloned, `git fetch origin && git pull --ff-only` instead of re-cloning.

## Kubernetes infrastructure (GitOps via ArgoCD)

### `clusters`
- URL: `git@gitlab.com:chainlayer/infrastructure/kubernetes/clusters.git`
- HTTPS: `https://gitlab.com/chainlayer/infrastructure/kubernetes/clusters`
- Purpose: per-cluster GitOps roots, Argo `Application` / `AppProject` definitions, cluster-scoped RBAC, operator install manifests, namespaces, generic config.
- Modify here when:
  - Adding or changing cluster-scoped resources (RBAC, CRDs, ClusterRoles, namespaces)
  - Wiring a new app into a cluster (add an Argo Application file)
  - Adjusting `generic-config` for a specific cluster

Directory cheat sheet:
```
argocd/base/            ArgoCD bootstrap + AppProjects (default, argo-apps, blockchain-apps, lcm)
argo-apps/              Shared infra Argo Apps deployed across clusters
argo-apps-general/      Same but a different sync wave
clusters/<name>/        Per-cluster app-of-apps wiring (just Argo Application objects)
clusters/<name>/generic-config/   Per-cluster non-Application manifests (cert issuers, RBAC, secret stores, snapshot classes, ...)
talos/                  Talos OS configs — hand-applied separately
util/                   Admin/dev utilities, hand-run
examples/               Reference examples, copy-and-modify
```

Key contract: `clusters/<name>/` directory should contain **only** Argo `Application` objects — `kustomize build .` there must not emit anything else. Real resources live in `generic-config/` or in `argo-apps/`.

RBAC for the `claude-readonly` group on nl-oven lives at `clusters/nl-oven/generic-config/rbac-claude-readonly.yaml`. The `generic-config` Argo Application that syncs that dir is defined in `clusters/nl-oven/generic-config-app.yaml`.

### `k8s-apps`
- URL: `git@gitlab.com:chainlayer/infrastructure/kubernetes/k8s-apps.git`
- HTTPS: `https://gitlab.com/chainlayer/infrastructure/kubernetes/k8s-apps`
- Purpose: app manifests (Argo Application objects + ApplicationSets pointing at helm charts or kustomize builds) for everything deployed *into* clusters.
- Modify here when adding or tuning an application (a Chainlink node, blockchain node, monitoring stack, etc.). Cluster-level changes do **not** go here.
- CODEOWNERS: `**/chainlink/**` → @joakim.w @jessemig.

Directory cheat sheet:
```
apps/                                Argo Application definitions + kustomize bases for apps
apps/op-stack/<chain>/               geth-based op-stack chains (per-chain kustomize, hand-written manifests)
apps/op-reth/<chain>-reth/           reth-based op-stack chains (kustomize where used)
apps/snapshot-manager/environments/  per-cluster snapshot-manager cronjob lists
appsets/                             ApplicationSet template values (matrix generators)
appsets/op-stack/<chain>/mainnet/    helm value overlays for geth chains (base-values.yaml + environments/{full-node,archive}.yaml)
appsets/op-reth/<chain>-reth/mainnet/  helm value overlays for reth chains (same shape)
clusters/<name>/op-stack-nodes/      ApplicationSets that bind chain configs to a specific cluster
projects/                            Per-app/per-chain AppProjects
monitoring/                          Monitoring config
disabled/                            Apps temporarily disabled
```

### `helm-charts`
- URL: `git@gitlab.com:chainlayer/infrastructure/kubernetes/helm-charts.git`
- HTTPS: `https://gitlab.com/chainlayer/infrastructure/kubernetes/helm-charts`
- Purpose: the actual helm chart definitions consumed by k8s-apps. Tagged per chart, multiple charts live in one repo.
- Notable charts + the tag conventions:
  - `charts/op-stack/` — geth-based op-stack node (tags `op-stack-vX.Y.Z`)
  - `charts/op-reth/` — reth-based op-stack node (tags `op-reth-vX.Y.Z`)
  - `charts/snapshot-manager/` — periodic + on-demand VolumeSnapshot+upload orchestrator (tags `snapshot-manager-vX.Y.Z`)
  - `charts/chainlink-node/`, `charts/chainlink-ea/`, plus various others
- To render a chart at the deployed version: `git checkout <tag> -- charts/<name>` then `helm template …`. k8s-apps `clusters/.../op-stack-nodes/*.yaml` pins the tag used in production.
- Modify here when adjusting the chart template itself (not when changing values for a specific chain — that's k8s-apps).

## Load balancer

### `haproxy`
- URL: `git@gitlab.com:chainlayer/infrastructure/haproxy.git`
- HTTPS: `https://gitlab.com/chainlayer/infrastructure/haproxy`
- Purpose: per-blockchain backends list (`backends.yaml`), templated into `backends.out.cfg` by `backends.py`. CI/CD pushes the rendered config to the LB nodes on merge to `main`.
- Modify here when:
  - Adding a new chain's RPC backend
  - Switching a chain's backends from VM nodes to k8s LB (typical migration: add k8s LB as a 3rd server with per-node `check_port "check port 8545"` since k8s pods don't run the legacy `:11001` health-agent — see OPS-1909 / 2017 celo precedent for shape)
  - Removing decommissioned backends
- Render check before committing: `python3 backends.py` (it writes `backends.out.cfg`). `grep` for your chain in the output to confirm the expected `backend` / `server` lines appear.

## Tailscale ACLs

### `tailscale-acls-production`
- URL: `git@gitlab.com:chainlayer/infrastructure/tailscale-acls-production.git`
- HTTPS: `https://gitlab.com/chainlayer/infrastructure/tailscale-acls-production`
- Purpose: the single `policy.hujson` file driving the tailnet's ACLs, tagOwners, grants, SSH policies.
- Modify here when:
  - Adding a new tailnet tag (`tagOwners`)
  - Granting a tag k8s impersonation (`grants` with `tailscale.com/cap/kubernetes`)
  - Changing who can SSH to what

CI auto-pushes the merged policy to Tailscale on merge to `main`. No manual step.

The `tag:claude-readonly` → k8s group `claude-readonly` grant lives in the `grants` section near the comment marked `// END of k8s section`.

## How auth flows from these repos to this VM's `kubectl`

1. **`tailscale-acls-production/policy.hujson`** — "tag `tag:claude-readonly` impersonates k8s group `claude-readonly`". Drives what the Tailscale operator does on incoming connections from this VM.
2. **`clusters/clusters/nl-oven/generic-config/rbac-claude-readonly.yaml`** — "group `claude-readonly` is bound to `view` + `chainlayer:claude-readonly-extra`". Drives what kube allows that group to do.
3. The ArgoCD app `generic-config` (defined in `clusters/clusters/nl-oven/generic-config-app.yaml`) syncs (2) onto nl-oven.

Either repo can change independently; both must be in sync for new perms to take effect.

## External references (read-only)

- https://docs.base.org/base-chain/node-operators/snapshots — base mainnet reth snapshot index (`/latest` returns the current filename).
- https://metalayerlabs.mintlify.app/building/guides/node/snapshot.md — blast snapshot docs (the canonical `docs.blast.io/...` URL 404s).
- https://snapshots.publicnode.com — base+part lz4 snapshots for op-stack chains.
- https://chained.grafana.net/ — Grafana Cloud (see `CLAUDE.md → Grafana / Prometheus probing` for the API pattern).
- https://linear.app/chained/ — Linear workspace (DevOps team, OPS- prefix).

## Adjacent repos under `chainlayer/infrastructure/` (not normally touched here)

Listed for completeness; touch only when Peter directs:

- `proxmox-iac` — Terraform for Proxmox VMs (useful for grep when checking whether a chain has a VM workload alongside k8s).
- `netbox-iac` — NetBox IPAM/inventory as code.
- `host-management` — Ansible for host-level config.
- `proxmox-setup`, `vm-templates`, `aws-iac`, `gcp-iac`, `fortigate-iac`, `gitlab-iac`, `dns-chosts`, etc.

## Workflow conventions (observed)

- Branch naming: `<author>/ops-NNNN-<title-slug>` — generated by Linear, use as-is.
- MR descriptions reference the Linear ticket explicitly (link or `Refs OPS-NNNN`).
- Commit message footer: `Refs OPS-NNNN`.
- Most MRs are squash-merged.
- Reviews on infra MRs typically come from karim@ or joakim.w@.
- Notifications for ArgoCD events go to Slack channel `xinfra-argocd-k8s` (annotation on every Application).

## Linear

- Workspace URL: `https://linear.app/chained/`
- Team for infra work: **DevOps** (prefix `OPS-`).
- The work that set up this VM's read-only access: parent `OPS-1943`, children `OPS-1981` (ACL grant) and `OPS-1982` (cluster RBAC rebind).

## Repos NOT to touch

Anything outside the ones listed above unless Peter explicitly directs. Product / blockchain repos belong on developer workstations with appropriate credentials — this VM doesn't have them and shouldn't.
