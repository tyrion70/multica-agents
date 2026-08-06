---
name: project-optimism-migration
description: "Optimism mainnet bare-metal → k8s op-reth migration; full-node only on k8s, archive deferred indefinitely because OP's published reth-archive snapshot is structurally broken"
metadata: 
  node_type: memory
  type: project
  originSessionId: cf026f25-e5cc-4b15-8f3a-6a96f7c943a3
---

OPS-2135. Migrating Optimism mainnet from 4 Hetzner bare-metal hosts (2 archive + 2 full-node) to k8s op-reth on nl-oven.

**As of 2026-05-26 15:25 UTC:** Full-node-only scope. Archive deferred indefinitely.

**Archive deferred — why:** OP's published `mainnet-reth-archive-*.tar.zst` is structurally broken — every reth version (v1.11.3, v2.2.0, v2.2.4) crashes at `StaticFileProducer` init with `trying to append row to Receipts at index #267197258 but expected index #265123619`. Confirmed across fresh PVC + extract, fresh PVC + `init-state --without-ovm` + extract, post-`migrate-v2` (13h35m), and cross-tests. The 2.9 TiB `mainnet-legacy-archival.tar.zst` turned out to be a *legacy l2geth chaindata* (LevelDB `.ldb`), not RLP — would need testinprod-io op-geth migration tool to convert (multi-day). MR !1469 removed the archive env from the appset; ArgoCD pruned `optimism-reth-mainnet-archive`; 20 TiB freed on LINSTOR worker-5.

**Why:** OP-published OVM legacy file isn't usable as-is for `op-reth import-op` (expects RLP, not l2geth chaindata). The 16.6 TiB `mainnet-2025-12-16.tar.zst` IS a usable bedrock op-geth datadir but would require switching the archive role from reth to op-geth — not worth the chart + ops work right now. Bare-metal Hetzner archive (`optimism-main-archive-{1a-de1m,2a-fi1m}`) keeps serving archive RPC indefinitely; revisit when OP fixes their reth snapshot.

**How to apply:** Treat OP archive as bare-metal-only for the foreseeable future. Don't re-attempt the published reth-archive snapshot without first checking if OP has fixed it (date later than 2026-05-19) — we've exhausted all known workarounds. Linear OPS-2135 has the full MR trail and reasoning in the 2026-05-26 status comment.

**Full-node status:** `optimism-reth-mainnet-full-node-0` is alive, syncing toward tip from `mainnet-reth-full-2026-05-18.tar.zst`. Chart pinned op-reth v1.11.3 + op-node v1.16.9 (matches bare-metal full-nodes — proven combo). Bedrock-only snapshot is self-contained and works fine; only the *archive* snapshot is broken.

Related: [[project-chainlink-platform]]
