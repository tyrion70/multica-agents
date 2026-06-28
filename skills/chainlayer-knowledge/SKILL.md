---
name: chainlayer-knowledge
description: Durable cross-cutting knowledge about ChainLayer's live infra projects — the chainlink-tools platform, the Optimism/Postgres/Proxmox migrations, the Filecoin voter node, and QuickNode RPC URLs. Read this for background/state and key decisions when working any ChainLayer infra issue; it points you at the domain skill for HOW-TO. Keep it updated (PR) when a durable fact or decision changes.
---

# ChainLayer knowledge

Background facts, decisions, and gotchas about ChainLayer's live projects — the
stuff worth carrying between issues. **HOW-TO lives in the domain skills**
(`chainlink-ops`, `company-k8s`, `company-proxmox`, `haproxy`, `deploy-app`,
`grafana-monitoring`, …); this skill is durable *knowledge and decisions*, not a
runbook, and not day-to-day status (don't put "N of M done as of <date>" here —
that rots). When something durable changes, update this file via a PR against
`tyrion70/claude-skills` and tell the user.

## chainlink-tools platform (dynamic node registry)
Three apps under `chainlink-tools/`, all deploying to the `chainlink` namespace in
`k8s-apps`, replacing the static `sites.json`/`hostmap.json` at
`chainlink.chainlink.cinternal.com` with dynamic registration:
1. **chainlink-service-registry** — Flask, in-memory node registry + heartbeats.
2. **chainlink-delete-jobs** — CronJob; registry-aware via `REGISTRY_URL`.
3. **chainlink-jira-sync** — stateless CronJob.
All nodes share one password stored as a k8s secret (the registry does NOT serve
it). Later phase: split each into its own repo + CI. The
`chainlink-utility-sidecar` image must be rebuilt to include `registry_sidecar.py`.

## Optimism migration (OPS-2135) — archive is bare-metal-only
Migrated OP mainnet to **k8s op-reth, full-node only**, on nl-oven. **Archive is
deferred indefinitely** because OP's published `mainnet-reth-archive-*.tar.zst` is
structurally broken — every reth version crashes at `StaticFileProducer` init
(`Receipts index` mismatch); confirmed across all known workarounds. The legacy
`.tar.zst` files are l2geth chaindata / bedrock op-geth datadirs, not RLP, so not
usable with `op-reth import-op` without major work. **Bare-metal Hetzner archive
keeps serving archive RPC indefinitely.** Do NOT re-attempt the published
reth-archive snapshot unless OP has published a fix dated later than 2026-05-19.
Full-node combo that works: op-reth v1.11.3 + op-node v1.16.9.

## Postgres migration (VMs → Zalando operator on k8s)
Migrating **82 Chainlink Postgres DBs** off 8 dedicated DB VMs to the Zalando
Postgres Operator on nl-oven (operator already installed). The big one is
`chainlink-database-1a-nl2v` (75 DBs). Project files: `projects/postgres-migration/`.
Zalando config lives in the **`clusters`** repo (not k8s-apps). GCS WAL backup needs
the `gcs-walg-creds` secret (only in `dev` ns so far). Decommissioning these VMs
depends on the Prox7→9 migration finishing.

## Proxmox 7→9 migration — decommission Prox7
Migrating all VMs from Prox7 (nl2) to Prox9 (nl2_c4) via PBS backup/restore + TF
import, to decommission Prox7. Project: `projects/proxmox-migration/` (migration-plan.md,
vm-assignments.csv, run-plan.sh). **The full procedure + disk-string safety rules live
in the `company-proxmox` skill — use it.** Durable decisions worth remembering: every
VM gets a Linear issue (project "Proxmox 9 VM Migration in NL"); silence alerts BEFORE
any action via the AM v2 tailnet API (NOT the stale `silence-vm.sh` — see
`grafana-monitoring` skill + `company-proxmox` skill for the current AM path); merge
TF `removed` blocks before stopping VMs; do NOT start VMs after restore (user moves
disks ceph→local-ZFS first); max 10 VMs/MR; never hand-construct disk strings — read
the live string and flip only the differing flags.

## Filecoin voter node — Lotus, and the fork-check
ChainLayer's Filecoin **governance/voting** node is **Lotus** (ArgoCD
`filecoin-lotus-mainnet`, nl-oven, ns `filecoin`), **not** the separate bare-metal
ChainSafe **Forest** deployment (`chainlayer/nodes/filecoin-infra`). Filecoin **NVxx
upgrades are mandatory and epoch-gated**: a too-old Lotus silently forks onto a dead
minority chain while `lotus sync status` still says "complete". Detect by comparing
tipset CIDs at a fixed height against glif (`api.node.glif.io`) vs in-pod
`lotus chain list`; fix = bump the image to the NV release + Argo rollout (binary-only;
the chainstore is preserved). History: OPS-2343, missed NV28 on v1.35.0 → v1.36.0.

## QuickNode RPC URL structure
Endpoints are `https://<prefix>.<network>.quiknode.pro/<token>`:
- `<prefix>` = **`side-convincing-emerald`** — fixed for the ChainLayer account, all chains.
- `<network>` = QuickNode network slug, varies per chain (not secret).
- `<token>` = the credential — store ONLY this, in **GCP Secret Manager project
  `mythic-fulcrum-424015-f9`** (surfaced via the `k8s-shared` ClusterSecretStore on
  nl-oven), secret name `quiknode-rpc-key`. Prefix + slug are non-secret (chart values).

## Co-authored-by commit hook — disabled at the workspace setting
The Multica daemon installs a git `prepare-commit-msg` hook (in each bare repo's
`hooks/` dir under `.repos/<workspace_id>/<repo>.git/hooks/`) that injects a
`Co-authored-by: multica-agent <github@multica.ai>` trailer on every agent commit —
which violates our no-`Co-Authored-By` rule. **The toggle is a server-side workspace
setting, `co_authored_by_enabled`, NOT a daemon binary flag or env var.** It is
**disabled (`false`) for the Chainlayer workspace** — Peter set it via the Multica web
UI workspace settings (admin/owner). The daemon reads it at `multica repo checkout`
time and skips the hook when it's off. Verify with `multica workspace get` →
`settings.co_authored_by_enabled` (the `multica workspace update` CLI does not expose
this flag — it's UI-only). This reconciles the CHA-175 finding that no config flag
existed in the daemon binary: the control was never daemon-local, it's the workspace
record the daemon queries. With it off, a fresh checkout no longer reinstalls the hook
and agent commits carry no trailer and stay SSH-signed (verified Good). If the trailer
ever reappears, first check `co_authored_by_enabled` is still `false`. (CHA-175/CHA-177)
