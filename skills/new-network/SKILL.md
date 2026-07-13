---
name: new-network
description: "Spin up a NEW network as a VM-based, publicly-reachable RPC node, end to end. Use when onboarding a network that does not yet run anywhere (existence check → snapshot bootstrap → proxmox VM → <network>-infra repo/pipeline → HAProxy → monitoring → docs → smoke test). This skill is the thin entrypoint: it points at the canonical runbook and the owning domain skills — it does NOT restate their steps. Runs the `new-network` orchestration (bundled `new-network.sh`) or walks the runbook by hand. Scope ends at a live, syncing, public RPC; Chainlink/DON/oracle config is out of scope (Joakim's handoff)."
---

# new-network — spin up a VM RPC network

The single entrypoint for bringing a **new** network online as a VM-based,
publicly-reachable RPC node. This skill is intentionally **thin**: it names the
ordered steps and links to the runbook section and the domain skill that owns
each one. It does **not** duplicate the runbook — the runbook is the contract.

**Canonical runbook (the contract):**
[documentation:docs/operations/spin-up-a-network.md](https://docs.chainlayer.cloud/operations/spin-up-a-network/)
— every step there names its repo, files, command, and a falsifiable done-check.

## Entrypoint

```bash
new-network <network> --client <client> [--snapshot-url <url>] [--cluster <dir>] [--site <site>]

# Flags may go before or after the network — validate scope first with a dry-run:
new-network --dry-run testnetx --client reth
```

- `<network>` — short lowercase slug, reused for the NetBox tag, the
  `<network>-infra` repo, and the HAProxy backend.
- `--client` — node software (`reth`, `geth`, …).
- `--snapshot-url` — override the default RustFS snapshot
  (`http://quicksync-2a-nl2m.chosts.io:9000/chainlink/<network>/latest.tar.zst`).
- `--dry-run` — print the complete ordered artifact/MR plan with **no side
  effects** (use this first, every time, to validate scope before provisioning).

The orchestration script is bundled here: [`new-network.sh`](new-network.sh). It
runs the read-only steps (existence check, snapshot discovery/sizing, smoke test)
live and opens the mutating steps as **reviewed MRs** — infra applies on merge, so
it stops at each merge boundary. It is glue, not new deploy mechanics.

## Ordered steps → runbook section + owning skill

Run `--dry-run` first, then work the steps in order. Each links to the runbook
section for the *how* and the domain skill for the mechanics.

| # | Step | Runbook section | Owning skill |
|---|---|---|---|
| 1 | Existence check (gate) | [Step 1](https://docs.chainlayer.cloud/operations/spin-up-a-network/#step-1-existence-check-gate) | — (present in any source → record & close) |
| 2 | Snapshot discovery & disk sizing | [Step 2](https://docs.chainlayer.cloud/operations/spin-up-a-network/#step-2-snapshot-discovery-disk-sizing-standard) · [Standard bootstrap commands](https://docs.chainlayer.cloud/operations/snapshot-bootstrap/#standard-snapshot-bootstrap-commands-per-network) | — (documented `curl -f \| tar` commands, **not** a role) |
| 3 | `<network>-infra` repo via gitlab-iac | [Step 3](https://docs.chainlayer.cloud/operations/spin-up-a-network/#step-3-create-the-network-infra-repo-via-gitlab-iac) | `new-repo-company` |
| 4 | Provision VM + placement | [Step 4](https://docs.chainlayer.cloud/operations/spin-up-a-network/#step-4-provision-the-vm-proxmox-iac-placement) | `company-proxmox` |
| 5 | Configure node (Ansible via CI) | [Step 5](https://docs.chainlayer.cloud/operations/spin-up-a-network/#step-5-configure-the-node-ansible-via-gitlab-ciyml) | — (`<network>-infra` CI runs `deploy-rpc.yml`) |
| 6 | Expose RPC via HAProxy | [Step 6](https://docs.chainlayer.cloud/operations/spin-up-a-network/#step-6-expose-the-rpc-via-haproxy) | `haproxy` |
| 7 | Monitoring | [Step 7](https://docs.chainlayer.cloud/operations/spin-up-a-network/#step-7-monitoring-monitoring2) | `grafana-monitoring` |
| 8 | Documentation | [Step 8](https://docs.chainlayer.cloud/operations/spin-up-a-network/#step-8-documentation) | `chainlayer-docs` |

All MRs follow **`git-mr`** (Linear-issue-first, SSH-signed, no Co-Authored-By).

## Done / not-done

- **Done** = the terminal smoke test passes: the public RPC URL
  (`https://<network>.rpc.chainlayer.cloud/`) answers with the correct
  `eth_chainId` **and** a strictly-advancing `eth_blockNumber`.
- **Two external inputs** the orchestration cannot invent:
  - **Placement** — which Proxmox host/cluster the VM lands on (Step 4). One
    labeled input (`vm_host`/`cluster`), filled from Peter's capacity data.
    Non-blocking for everything except the actual VM apply; new VMs default to
    **Prox9** (`clusters/nl2_c4`).
  - **The snapshot object key** under the `chainlink` bucket, maintained by
    Peter/Chris — confirm it (or pass `--snapshot-url`) before Step 2 apply.

## Scope boundary

Ends at a **live, syncing, publicly-reachable RPC node**. Chainlink node / DON /
oracle-job configuration is **out of scope** (handed to Joakim once the RPC is up).
VM-only — there is no Kubernetes path in this flow.
