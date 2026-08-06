---
name: reference-filecoin-lotus-node
description: "ChainLayer's Filecoin governance/voting node — Lotus on k8s nl-oven; how to fork-check it after a network upgrade"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 75ed9b41-2df1-417a-835b-586484d4749b
---

ChainLayer's Filecoin **governance/voting** node is **Lotus**, not Forest:
ArgoCD app `filecoin-lotus-mainnet`, cluster `nl-oven`, ns `filecoin`, StatefulSet
`filecoin-lotus-mainnet-full-node` (2 replicas). Image tag in
`k8s-apps/apps/blockchain-nodes/filecoin/lotus/mainnet/base/statefulset.yaml`
(`docker.io/filecoin/lotus-all-in-one:<ver>`). RPC svc `filecoin-lotus-rpc-full-node.filecoin:1234/rpc/v0`.
`chainlayer/nodes/filecoin-infra` is a *separate* bare-metal ChainSafe **Forest**
deployment — NOT the voter.

**Filecoin NVxx upgrades are mandatory and epoch-gated.** A too-old Lotus forks off
mainnet at the upgrade epoch and silently follows a dead minority fork; `lotus sync
status` still says "complete". Detect by comparing tipset CIDs at a fixed height
against glif (`https://api.node.glif.io/rpc/v0`, `Filecoin.ChainGetTipSetByHeight`)
vs `lotus chain list --count 1 --height <h>` in-pod — binary-search to find the
divergence epoch (it equals the NV epoch). Fix = bump image to the NV release, merge,
Argo rollout; binary-only because the `/var/lib/lotus/.initialized` guard preserves
the chainstore; new binary reorgs onto the heavier canonical chain.

History: OPS-2343 — node on v1.35.0 missed **NV28 "Fire Horse"** (epoch 6052800,
2026-05-27 14:00 UTC), bumped to v1.36.0. Renovate should track this image; investigate
why the bump wasn't auto-proposed before the deadline. See [[reference-k8s-deploy-guide]].
