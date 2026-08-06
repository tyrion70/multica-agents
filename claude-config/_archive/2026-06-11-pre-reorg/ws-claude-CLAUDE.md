# CLAUDE.md — Project instructions for AI assistants

## Workspace

This is a multi-repo workspace at `~/gsd2/` containing ~33 git repositories for **ChainLayer** — a Chainlink node operator running blockchain infrastructure.

- `repositories/` — All git repos (GitLab + GitHub)
- `projects/` — Working project folders, scripts, docs
- `docs/` — Cross-repo documentation (deploying-to-k8s.md is the key reference)

## Git workflow — ALWAYS DO THIS

1. **Before editing any repo**: `cd` into it, check `git branch`, `git pull origin main`
2. **Never edit on a stale checkout** — always fetch/pull first
3. **Branch naming**: `fix/short-description` or `feat/short-description`
4. **Commits**: Use conventional commits (`fix:`, `feat:`, `chore:`, `docs:`)
5. **MRs via glab**: Use `glab mr create` with a proper description
6. **After finishing work on a branch**: checkout main, drop stashes

## Key repos and relationships

### The K8s triangle
- **k8s-apps** (`chainlayer/infrastructure/kubernetes/k8s-apps`) — App manifests, Kustomize, Helm values, ArgoCD ApplicationSets
- **clusters** (`chainlayer/infrastructure/kubernetes/clusters`) — Cluster infra, ArgoCD bootstrap, argo-apps
- **helm-charts** (`chainlayer/infrastructure/kubernetes/helm-charts`) — Custom Helm charts (chainlink-node, external-adapters, op-stack)

### Infrastructure
- **gitlab-iac** — Terraform for all GitLab repos + GCP secrets
- **aws-iac** — Terraform for AWS (IAM for ECR access)
- **proxmox-iac** — Terraform for VMs on Proxmox
- **monitoring2** — Ansible for bare-metal Prometheus/Grafana/Thanos
- **renovate** (`chainlayer/utilities/renovate`) — Self-hosted Renovate bot config

### Chainlink apps (deployed to k8s)
- **chainlink-service-registry** → `apps/chainlink/service-registry/`
- **chainlink-service-registry-sidecar** → appsets base-values sidecars
- **chainlink-delete-jobs** → `apps/chainlink/delete-jobs/`
- **chainlink-jira-sync** → `apps/chainlink/jira-sync/`

## 3 physical k8s clusters
- `nl-oven` — Main production (Amsterdam)
- `nl-spud` — Secondary (Amsterdam)
- `no-fryer` — Norway (Oslo)

All Talos Linux on Proxmox, accessed via Tailscale.

## Monitoring architecture
- **kube-prometheus-stack** on each cluster (scrapeInterval: 10s, retention: 14d)
- `*SelectorNilUsesHelmValues: false` — Prometheus scrapes ALL ServiceMonitors/PodMonitors automatically
- **Alertmanager** routes: Slack (#xmonitoring-kubernetes, #xmonitoring-fullnodes), incident.io, PagerDuty
- **Thanos sidecar** on k8s Prometheus → bare-metal Thanos Query for unified cross-DC queries
- **Grafana Cloud** via PDC Agent (private data source connect) + Grafana Alloy (logs/events)
- **PrometheusRules** in `k8s-apps/monitoring/prometheusrules/` deployed via `apps-monitoring` ArgoCD app

## Docker registries
| Registry | Access | Use |
|----------|--------|-----|
| `europe-docker.pkg.dev/prime-hydra-436615-d6/chainlayer/` | Private (needs imagePullSecret) | Internal images |
| `europe-docker.pkg.dev/chainlayer/quickimage/` | Public | Public images |
| `public.ecr.aws/chainlink/adapters/` | Public (AWS) | Chainlink external adapters (137 images) |

## Renovate
- Self-hosted at `chainlayer/utilities/renovate` on GitLab
- Autodiscovers all `chainlayer/**` repos, excludes `chainlayer/personal/`
- k8s-apps uses digest pinning (`latest@sha256:...`) for internal tools
- Adapter images tracked by semver tag
- ECR Public auth via `@smithy/signature-v4` (NODE_PATH needed for pnpm)
- `RENOVATE_DETECT_HOST_RULES_FROM_ENV=true` — env vars like `RENOVATE_DOCKER_PUBLIC_ECR_AWS_PASSWORD` auto-map to hostRules

## Deploying new apps
See `docs/deploying-to-k8s.md` for the full pipeline:
gitlab-iac (create repo) → CI (build image) → GCP secrets → k8s-apps (manifests) → clusters (ArgoCD app)

## Tools available
- `glab` — GitLab CLI (installed, authenticated)
- SSH keys use YubiKey (may get `sign_and_send_pubkey: signing failed` — git ops may still work via cached keys)
- `kubectl` access via Tailscale to all 3 clusters

## Formatting for Terraform
- Always run `tofu fmt -recursive` before committing Terraform changes
