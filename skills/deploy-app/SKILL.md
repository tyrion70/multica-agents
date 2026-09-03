---
name: deploy-app
description: Deploy a new application to ChainLayer's k8s GitOps pipeline — gitlab-iac repo creation, CI image build, GCP secrets, ExternalSecrets, k8s-apps manifests, ArgoCD Application, Renovate auto-updates. Use whenever creating a new service/CronJob/repo that ends up running on the clusters, or when an existing app's deploy pipeline (image pulls, secrets, Argo sync) is broken. Full templates live in docs/deploying-to-k8s.md — this skill is the checklist plus the gotchas.
---

