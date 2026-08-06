# Repositories — global index

Pointers to repos that come up across sessions. Workspace-level overview also in `~/claude/CLAUDE.md`.

GitLab namespace `chainlayer/*`, clone path `~/claude/repositories/`. Personal GitHub repos noted inline. Per-issue file-touch notes belong in [STATUS.md](STATUS.md), not here.

## K8s triangle (always relevant)
| Repo | Local path | Purpose |
|---|---|---|
| k8s-apps | `~/claude/repositories/k8s-apps` | App manifests, Kustomize, Helm values, ArgoCD ApplicationSets |
| clusters | `~/claude/repositories/clusters` | Cluster infra, ArgoCD bootstrap, argo-apps |
| helm-charts | `~/claude/repositories/helm-charts` | Custom Helm charts (chainlink-node, base-node, op-reth, external-adapters, op-stack) |

## Infrastructure-as-code
| Repo | Local path | Purpose |
|---|---|---|
| gitlab-iac | `~/claude/repositories/gitlab-iac` | Terraform: GitLab repos + GCP secrets |
| aws-iac | `~/claude/repositories/aws-iac` | Terraform: AWS IAM for ECR access |
| proxmox-iac | `~/claude/repositories/proxmox-iac` | Terraform: VMs on Proxmox |
| monitoring2 | `~/claude/repositories/monitoring2` | Ansible: bare-metal Prometheus/Grafana/Thanos. Per-chain scrape targets at `configuration/sites/<site>/targets/<chain>-{network,node-exporter}.yml`. |
| renovate | (chainlayer/utilities/renovate) | Self-hosted Renovate bot config |

## Chainlink apps (deployed to k8s)
| Repo | Local path | Deploys to | Notes |
|---|---|---|---|
| chainlink-ops | `~/claude/repositories/chainlink-ops` | `apps/chainlink/ops/` | Python Flask + 2 daemon loops. **Replaces** chainlink-jira-sync + chainlink-delete-jobs. State on `/data` PVC (`chainlink-jira-sync-state`, 100 Mi linstor-double-replica). Slack token refresh procedure in CLAUDE.md. |
| chainlink-service-registry | `~/claude/repositories/chainlink-service-registry` | `apps/chainlink/service-registry/` | In-memory HTTP registry + Prometheus metrics; sidecars register here. |
| chainlink-service-registry-sidecar | `~/claude/repositories/chainlink-service-registry-sidecar` | appsets base-values sidecars | Lives in every chainlink pod as the `registry` sidecar. |
| chainlink-topup | `~/claude/repositories/chainlink-topup` | `apps/chainlink/topup/` | Node.js — REST API on :8080 (`/api/v1/config|status|history|balances`). Wraps EthBalanceMonitor contracts across multiple chains. |
| chainlink-balancemonitor | `~/claude/repositories/chainlink-balancemonitor` | (Solidity) | Source for the EthBalanceMonitor contracts that chainlink-topup talks to. |
| chainlink-delete-jobs | `~/claude/repositories/chainlink-delete-jobs` | (superseded) | Code merged into chainlink-ops; repo retained for history. |
| chainlink-jira-sync | `~/claude/repositories/chainlink-jira-sync` | (superseded) | Code merged into chainlink-ops; repo retained for history. |
| chainlink-tools | `~/claude/repositories/chainlink-tools` | n/a | Utility scripts (healthcheck daemons, etc.). |
| chainlink-adapter-update | `~/claude/repositories/chainlink-adapter-update` | n/a | Bumps external-adapter image tags. |
| chainlink | `~/claude/repositories/chainlink` | n/a | Upstream `smartcontractkit/chainlink` — cloned for source reference (e.g. EVM.Node config schema, multinode lifecycle). |

## HAProxy / Fortigate / DNS (network IaC)
| Repo | Local path | Purpose |
|---|---|---|
| haproxy-gitlab | `~/claude/repositories/haproxy-gitlab` | **Active** HAProxy config (`backends.yaml`, `backends.j2`, `backends.py`, `hapee-lb.cfg`, `pushconfig.sh`). MRs deploy via dataplane API to both LBs. |
| haproxy-setup | `~/claude/repositories/haproxy-setup` | Older Jenkins-driven HAProxy repo — superseded by haproxy-gitlab. Still useful for archaeology (e.g. which chain a now-repurposed IP used to serve — diff `backends.out.cfg.*` snapshots). |
| fortigate-iac | `~/claude/repositories/fortigate-iac` | Terraform for Fortigate firewalls (nl2 + no1). Per-site directories under `fortigates/`. |
| dns-chosts | `~/claude/repositories/dns-chosts` | DNS records for `*.chosts.io` bare-metal hostnames. |

## Chain VM infrastructure (`*-infra` family)
Ansible repos that provision the bare-metal chain VMs (docker-compose stacks, monitoring agents, firewall, ssh). Each chain that runs as **bare-metal VM-only** (not deployed via k8s helm-charts) has its own `*-infra` repo. They share a common layout: `playbook.yml`, `inventories/{netbox,static}.yml`, `group_vars/all/{node-exporter,healthcheck,...}.yml`. The `healthcheck.yml` deploys the HAProxy check-port-11001 agent (`tyrion70/health-agent-new` Docker container) — without it, HAProxy backends stay `L4CON / Connection refused`.

| Repo | Local path | Notes |
|---|---|---|
| axelar-infra | `~/claude/repositories/axelar-infra` | Has `group_vars/all/healthcheck.yml` (cosmos_lcd + cosmos_rpc on ports 11001/11002). |
| base-infra | `~/claude/repositories/base-infra` | Has healthcheck config. |
| fraxtal-infra | `~/claude/repositories/fraxtal-infra` | Has healthcheck (script `optimism`). |
| optimism-infra | `~/claude/repositories/optimism-infra` | Has healthcheck + firewall config. |
| zksync-infra | `~/claude/repositories/zksync-infra` | **Only has `node-exporter.yml`, no `healthcheck.yml`** → port 11001 not deployed. |

**Chains with NO `*-infra` repo** even though they have bare-metal VMs (gap): zkevm, plasma, sonic, scroll, metis, gnosis, bsc, and several other older chains. Their VMs are reachable but no ansible owns them — if you add them to HAProxy with `check port 11001` they'll stay DOWN. Use `check port 8545` as fallback until network owners create the `*-infra` repo.

## Sidecars / shared chart components

| Repo | Local path | Notes |
|---|---|---|
| <a id="healthcheck-agent"></a>healthcheck-agent-gitlab | `~/claude/repositories/healthcheck-agent-gitlab` | Python FastAPI sidecar (`europe-docker.pkg.dev/chainlayer/quickimage/healthcheck-agent`) injected into every op-stack pod by the `op-stack` and `op-reth` Helm charts. Emits `node_agent_*` Prometheus metrics on `:8123/metrics` (op-stack chart) or `:8000/metrics` (legacy `apps/blockchain-nodes/`). Health-check modules per chain family at `src/healthchecks/{evm,cosmos,aptos,near,solana,substrate,sui}.py`. **Distinct** from the bare-metal `tyrion70/health-agent-new` Docker container that VMs use for HAProxy port-11001 checks (see HAProxy section in CLAUDE.md). |

## Documentation
| Repo | Local path | Notes |
|---|---|---|
| documentation | `~/claude/repositories/documentation` | Retype site (chainlayer/documentation) — sources in `~/claude/projects/documentation/` |

## Personal projects (GitHub, not GitLab — no Linear)
| Repo | Local path | Origin |
|---|---|---|
| ess-ai-planner | `~/claude/repositories/ess-ai-planner` | github.com/tyrion70/ess-ai-planner |
| weekend-escape-radar | `~/claude/repositories/weekend-escape-radar` | github.com/tyrion70/weekend-escape-radar |

## Laptop-side / VM-provisioning tooling (GitHub, personal)

| Repo | What | Origin |
|---|---|---|
| **cm** | Laptop wrapper (`cm`) + VM-side multi-session manager (`claude-mgr`) — installed at `/usr/local/bin/claude-mgr` on the workstation VM. Pull-and-`install-vm.sh` workflow. | `github.com/tyrion70/cm` |
| **claude-workstation-vm** | Ansible playbook + inventory that provisions a fresh `claude-workstation-01`-class VM (apt base, Node, Go, terraform/tofu, kubectl, helm, gh, glab, sops/age, mosh, Docker, Tailscale, gcloud, gsd-pi, native `claude install`). | `github.com/tyrion70/claude-workstation-vm` |

## Personal (GitHub tyrion70)
| Repo | Local path | Purpose |
|---|---|---|
| claude-skills | `~/claude/repositories/claude-skills` | All Claude Code skills (PRIVATE). install.sh symlinks into ~/.claude/skills; make-zips.sh builds desktop zips. |
