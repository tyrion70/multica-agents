---
name: chainlink-platform-modernization
description: Chainlink service registry + dockerized CronJobs project - three apps being built in chainlink-tools and deployed to k8s-apps
type: project
---

Building three interconnected projects in `chainlink-tools/`:
1. **chainlink-service-registry** — Python Flask server, in-memory node registry with heartbeats
2. **chainlink-delete-jobs** — Dockerized as CronJob, now supports registry via REGISTRY_URL env var
3. **chainlink-jira-sync** — Dockerized as CronJob, stateless operation

**Why:** Replace static `sites.json`/`hostmap.json` at `chainlink.chainlink.cinternal.com` with dynamic registration. All nodes share a single password stored as k8s secret (not served by registry).

**How to apply:** All three deploy to `chainlink` namespace in k8s-apps. Later phase: each moves to its own repo with CI pipeline. The `chainlink-utility-sidecar` image needs rebuilding to include `registry_sidecar.py`.
