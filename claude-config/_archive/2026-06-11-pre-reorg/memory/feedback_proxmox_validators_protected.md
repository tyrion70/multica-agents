---
name: Validators and signers go in nl2_c4_protected, not nl2_c4
description: When migrating Cosmos/EVM validators or signers to Prox9, place them in clusters/nl2_c4_protected (using proxmox_vm_ubuntu_protected source), not the non-protected nl2_c4 cluster
type: feedback
originSessionId: 9fbf0170-b405-4e85-80f9-b25d22615a9d
---
When migrating a Cosmos/EVM **validator** or **signer** VM to Prox9 (Proxmox 7→9 migration), place its TF module in `clusters/nl2_c4_protected/`, not `clusters/nl2_c4/`.

**Why:** the protected cluster is the one with the hardened module (`modules/proxmox_vm_ubuntu_protected`), restricted user set (`vm_environment = "restricted-low"`), and tighter firewall defaults. Validators and their signers carry consensus keys and need the higher-trust environment. RPC nodes, statesync nodes, relays, archives, etc. go in the non-protected cluster.

**How to apply:**
- Track A migrations: if the source module lives in `clusters/nl2_protected/`, the target lives in `clusters/nl2_c4_protected/`. Same for non-protected → non-protected.
- Track B migrations (no Prox7 module): use the role to decide. Validator/signer → protected. RPC/statesync/relay/archive → non-protected.
- Module source: `../../modules/proxmox_vm_ubuntu_protected` (note suffix). Same providers stanza as non-protected (`fortios.by_site["nl2"]` / `fortios.by_site["no1"]`).
- The protected cluster's `proxmox-hosts.tf` may not have every network defined. If a validator is on `public_range3` (89.149.218.x/24) or another non-default range, **add the network to nl2_c4_protected/proxmox-hosts.tf** rather than putting the validator in non-protected — the historical convention of "range3 stays non-protected" is wrong, it was a missing-network workaround.

**Reference:**
- OPS-1741 (this MR): added `public_range3` to `nl2_c4_protected/proxmox-hosts.tf` so q-main-validator-1b could live there properly.
- Existing protected modules to mirror style: `nl2_c4_protected/vms-axone.tf`, `vms-ethereum.tf`, `vms-polygon.tf`, `vms-wormchain.tf`.

**Outstanding tech debt** (separate MR needed): earlier migrations dropped these validators/signers in non-protected `nl2_c4` and need relocating: fuel-main-node-1a, fuel-main-hx-{signer,validator}, fuel-test-{signer,validator}, axelar-main-{statesync-1a,signer-1a,amplifier-verifier-1a,statesync-2a}, lido-main-standby-validator-1a/2a, lido-test-validator-2a, lido-test-dvt-curated-1a/2a, lido-main-obol-1a, q-main-{root-1c,full-2a}, heimworks-dev-rpc-1a (RPC, debatable).
