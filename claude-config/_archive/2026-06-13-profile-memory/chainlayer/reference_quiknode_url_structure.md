---
name: reference-quiknode-url-structure
description: ChainLayer QuickNode RPC endpoint URL structure + which GCP project/ESO store holds the token
metadata: 
  node_type: memory
  type: reference
  originSessionId: dd22d539-38b4-41f8-ad3c-75f7ee7e9afd
---

ChainLayer's QuickNode RPC endpoints follow `https://<prefix>.<network>.quiknode.pro/<token>`:

- **`<prefix>` = `side-convincing-emerald`** — FIXED for the ChainLayer account across all chains/networks.
- **`<network>`** — the QuickNode network slug, varies per chain (e.g. `worldchain-mainnet`, `xdai`). Not secret.
- **`<token>`** — the credential. Store ONLY this in GCP Secret Manager, never in git. The fixed prefix + network slug are non-secret and may live in chart values.

ESO plumbing on nl-oven: general k8s apps use ClusterSecretStore **`k8s-shared`** → GCP project **`mythic-fulcrum-424015-f9`**. (Other stores: `chainlink`→plasma-raceway-438008-b6, `solana`→ambient-empire-448816-r7.) So the QuickNode token secret `quiknode-rpc-key` belongs in `mythic-fulcrum-424015-f9`, surfaced into a namespace via an ExternalSecret referencing the `k8s-shared` ClusterSecretStore.

Used by the HAProxy IC 3rd-party external-fallback (see [[project_haproxy_control_plane]] if present): chart assembles host `<prefix>.<network>.quiknode.pro`, controller injects `/<token>` from the secret into the external backend path. VM HAProxy stores the equivalent `path_prefix` (token) directly in `haproxy-gitlab/backends.yaml` (git plaintext) under `external.nodes` — different handling than the k8s path which keeps it in Secret Manager.
