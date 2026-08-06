---
name: k8s-deployment-guide
description: Complete guide for creating GitLab repos and deploying apps to k8s — covers gitlab-iac, CI pipelines, GCP secrets, k8s-apps manifests, ArgoCD, and private registry pull access
type: reference
---

Full deployment guide at `/Users/petervanmourik/claude/docs/deploying-to-k8s.md`.

Covers: gitlab-iac repo creation → CI pipeline → GCP secrets → ClusterSecretStore namespace access → Kustomize manifests → private registry pull secrets → ArgoCD Application → Renovate auto-updates.

Key gotchas documented:
- Private registry (`chainlayer/chainlayer`) needs `imagePullSecrets` + ExternalSecret for `gcp-gar-docker-pull`
- Public registry (`chainlayer/quickimage`) needs no auth
- Secrets go in GCP project `mythic-fulcrum-424015-f9` (not the default project)
- Namespace must be in `k8s-shared` ClusterSecretStore allowed list (in k8s-clusters repo)
- Helm lists replace, don't merge — include all sidecars when overriding per-node
- CI `stages:` must include `test` even without test jobs (kaniko template inherits it)
