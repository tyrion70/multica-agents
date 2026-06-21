---
name: deploy-app
description: Deploy a new application to ChainLayer's k8s GitOps pipeline — gitlab-iac repo creation, CI image build, GCP secrets, ExternalSecrets, k8s-apps manifests, ArgoCD Application, Renovate auto-updates. Use whenever creating a new service/CronJob/repo that ends up running on the clusters, or when an existing app's deploy pipeline (image pulls, secrets, Argo sync) is broken. Full templates live in docs/deploying-to-k8s.md — this skill is the checklist plus the gotchas.
---

# Deploying a new app to k8s

Full copy-paste templates: `~/claude/docs/deploying-to-k8s.md` (read it when
you need exact YAML/HCL). This skill is the ordered checklist and the mistakes
that cost time. Linear issue first (`linear-company` skill); each repo change ships per
the `git-mr` skill.

## The pipeline (7 steps, in order)

**1. GitLab repo** — `repositories/gitlab-iac/`: add the project to the
group's `_projects` local. Set `gcp_docker_registry_access = "private"` for
internal images (enables GAR integration + CI `artifactregistry.reader`
everywhere / `writer` on main only). `tofu fmt -recursive` before commit.

**2. CI pipeline** — `.gitlab-ci.yml` from the kaniko template
(`chainlayer/cicd/templates` `extends/kaniko-image.yml` + gitleaks component).
Gotchas:
- `stages:` MUST include `test` even with no test jobs — the inherited
  `image:test` job declares `stage: test` and the pipeline fails without it.
- `IMAGE_NAME` becomes the registry image name; merge to main tags
  commit-SHA + `latest`.

**3. GCP secrets** — project **`mythic-fulcrum-424015-f9`** (that's where the
`k8s-shared` ClusterSecretStore reads; NOT the default project):
`gcloud secrets create NAME --project=mythic-fulcrum-424015-f9 …`.
Machine-consumed secrets go here. Human-held credentials (dashboard logins,
API keys you hold) → **bitwarden** skill, `company` folder. Never put a secret
value in a manifest.

**4. ClusterSecretStore namespace allowlist** — `k8s-shared` only serves
listed namespaces. Add yours in
`repositories/clusters/clusters/nl-oven/generic-config/cluster-secret-store-k8s-shared.yaml`
(or label the ns `chainlayer.io/external-secrets.k8s-shared: "true"`).
Forgetting this = ExternalSecret stuck `SecretSyncedError`.

**5. k8s manifests** — `repositories/k8s-apps/apps/<category>/<app>/` with
`base/` + `overlays/nl-oven/` kustomize layout. Include:
- `secrets.ExternalSecret.yaml` (store `k8s-shared`, kind ClusterSecretStore).
- **Private registry** (`europe-docker.pkg.dev/prime-hydra-436615-d6/chainlayer/`)
  needs `imagePullSecrets: [name: gcp-gar-docker-pull]` in the pod spec AND a
  `pull-secret.ExternalSecret.yaml` rendering the dockerconfigjson (template in
  the doc). Chainlink namespaces already have it via `appsets/chainlink/shared/`.
  Public registry (`chainlayer/quickimage`) needs nothing.
- `serviceMonitor.yaml` if exposing `/metrics` — Prometheus auto-scrapes all
  ServiceMonitors (`*SelectorNilUsesHelmValues: false`), no extra wiring.
- `# renovate: datasource=docker depName=… versioning=loose` comment above the
  image line so Renovate digest-bumps `latest@sha256:…` automatically. With an
  automerge packageRule, code-merge → image build → auto bump MR → Argo sync,
  no manual k8s MR.

**6. ArgoCD Application** — `clusters/nl-oven/<app>.yaml`: path to the
overlay, `project:` must match an AppProject in `projects/` that allows the
target namespace, syncPolicy automated + `CreateNamespace=true`, Slack
notification annotation `xinfra-argocd-k8s`.

**7. Verify** — repo created → CI green + image in registry → Argo app synced
→ `kubectl get pods -n <ns>` Running → `kubectl get externalsecrets -n <ns>`
SecretSynced → `kubectl describe pod` shows no pull errors.

## Recurring gotchas

- **Helm lists replace, never merge** — overriding `sidecars`/`extraContainers`
  per-node means re-listing ALL existing entries, not just the new one.
- Image in private registry but pods `ImagePullBackOff` → 90% of the time the
  namespace is missing the `gcp-gar-docker-pull` ExternalSecret or the
  allowlist entry (step 4).
- New TOML/env keys consumed by old images can crashloop — check image version
  supports the key before wiring it.
- The ArgoCD ApplicationSet pattern (appsets/) polls git ~3 min — adding an
  env YAML is enough to create an app; no Argo-side change needed.
- Registries: `prime-hydra-436615-d6/chainlayer` = private; `chainlayer/quickimage`
  = public; `chainlayer/quickimage-sandbox` = branch/test builds.

## Permission model

✅ Without asking: writing manifests/HCL on a branch, local renders
(`kustomize build`, `helm template`), CI status checks, kubectl reads.

🔶 GitOps: everything lands via MRs (gitlab-iac → app repo → clusters →
k8s-apps), in that dependency order — don't merge k8s-apps before the image
exists.

🛑 Ask first: creating GCP secrets (state name + project), deleting/renaming
existing Argo Applications, anything touching another team's AppProject, and
`tofu apply` in gitlab-iac if CI isn't doing it.
