---
name: deploy-verify-rollback
description: Generic, target-agnostic deploy → verify → rollback procedure for shipping an approved change to production and safely reverting it when health checks fail. Use whenever deploying any service that is NOT covered by a target-specific skill — Kubernetes Deployments, docker / docker-compose hosts, or systemd-managed binaries reached over SSH. Always records the last-known-good state BEFORE deploying so rollback is a single known command. Tremor has its own deploy path — use the `tremor` skill for that, not this one.
---

