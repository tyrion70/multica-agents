---
name: Postgres migration to k8s
description: Migrating 82 Chainlink node PostgreSQL databases from 8 VMs to Zalando Postgres Operator in k8s nl-oven cluster
type: project
---

Migrating Chainlink PostgreSQL databases from VMs to k8s Zalando Postgres Operator.

**Why:** 8 dedicated database VMs (92 cores, 272GB RAM, 3.2TB disk) are candidates for decommissioning after the Prox7→Prox9 migration. The Zalando Postgres Operator is already installed in k8s but unused.

**How to apply:**
- Project files at `projects/postgres-migration/` (Excel spreadsheet + README)
- Main DB VM (chainlink-database-1a-nl2v, 89.149.218.162) hosts 75 databases and is the biggest challenge
- 5 CRE VMs each host 1 database (small, 4 CPU / 16GB each)
- 2 Mercury/Data-Streams VMs each host 1 database (large, 32 CPU / 32GB each)
- Zalando operator config lives in the `clusters` repo, not k8s-apps
- GCS WAL backup configured but `gcs-walg-creds` secret only exists in `dev` namespace
- 2 stale CRs stuck in deletion since 2026-02-10 need finalizer cleanup
