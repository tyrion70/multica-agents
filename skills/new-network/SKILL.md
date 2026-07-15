---
name: new-network
description: "Spin up a NEW network as a publicly-reachable RPC node, end to end — the single entrypoint for BOTH the VM plane (Proxmox + Ansible + HAProxy) and the Kubernetes plane (op-stack/op-reth on ArgoCD). Use when onboarding a network that does not yet run anywhere: Step 0 is a VM-vs-k8s class-branch that routes to the matching runbook (VM: existence check → snapshot → proxmox VM → <network>-infra pipeline → HAProxy → monitoring → docs; k8s: chart choice → snapshot on PV → ApplicationSet → AppProject allowlist → config → Cilium LB → monitoring → docs). This skill is the thin entrypoint: it points at the canonical runbook and the owning domain skills — it does NOT restate their steps. Runs the `new-network` orchestration (bundled `new-network.sh`, VM) or walks the runbook by hand. Scope ends at a live, syncing, public RPC; Chainlink/DON/oracle config is out of scope (Joakim's handoff)."
---

# new-network — spin up an RPC network (VM or k8s)

The single entrypoint for bringing a **new** network online as a
publicly-reachable RPC node. This skill is intentionally **thin**: it names the
ordered steps and links to the runbook section and the domain skill that owns
each one. It does **not** duplicate the runbook — the runbook is the contract.

## Step 0 — VM or k8s? (class-branch — do this first)

There are **two deployment planes** and they diverge from the very first step.
Decide the plane before anything else, then follow the matching runbook — this
skill is the single entrypoint for both.

| Class | When (CHA-698 placement rule) | Canonical runbook (the contract) | Mechanics |
|---|---|---|---|
| **VM** | Heavier chains, non-OP-stack clients, or archive-scale disk | [spin-up-a-network](https://docs.chainlayer.cloud/operations/spin-up-a-network/) | Proxmox VM + Ansible + HAProxy — the flow **below** |
| **k8s** | Light **OP-Stack** L2, roughly **RAM 8–16 GB and disk < 1 TB** | [spin-up-a-network-k8s](https://docs.chainlayer.cloud/operations/kubernetes/spin-up-a-network-k8s/) | op-stack/op-reth chart on ArgoCD (GitOps, no `kubectl apply`) |

Both runbooks are **RPC-only** and stop at a live, syncing, publicly-reachable
node; Chainlink/DON/oracle config is Joakim's handoff. The `new-network.sh`
orchestration automates the **VM** flow; the **k8s** flow is a reviewed set of
`k8s-apps` MRs walked by hand per its runbook (its steps name the AppProject
allowlist, snapshot-on-PV, Cilium LB exposure, and the ArgoCD sync boundaries).

Everything below is the **VM** flow. For the k8s flow, follow its runbook.

**Canonical VM runbook (the contract):**
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
- `--snapshot-url` — override with a direct archive URL. By default the object(s) +
  format are resolved from the network's manifest at
  `http://quicksync-2a-nl2m.chosts.io:9000/chainlink/<network>/latest.json` — there is
  **no** fixed `latest.tar.zst`.
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

- **Done** = the terminal smoke test passes: the internal RPC URL
  (`https://<network>.rpc.cinternal.com/`) answers with the correct
  `eth_chainId` **and** a strictly-advancing `eth_blockNumber`.
  - **Endpoint caveat:** `*.rpc.cinternal.com` is a **grey-cloud (DNS-only)**
    wildcard — it already resolves, so no per-network DNS/Cloudflare work is
    needed. The origin serves a `*.quickapi.com` Origin-CA cert (not a
    browser-trusted public cert), so run the done-check curl **from inside the
    network** (Tailscale) and with `-k` — which is what `new-network.sh` does.
- **Two external inputs** the orchestration cannot invent:
  - **Placement** — which Proxmox host/cluster the VM lands on (Step 4). One
    labeled input (`vm_host`/`cluster`), filled from Peter's capacity data.
    Non-blocking for everything except the actual VM apply; new VMs default to
    **Prox9** (`clusters/nl2_c4`).
  - **The snapshot object(s)** under the `chainlink` bucket — resolved from the
    network's `latest.json` manifest at Step 2 (not a fixed `latest.tar.zst`).
    Confirm the network has a manifest, or pass `--snapshot-url`, before Step 2 apply.

## Scope boundary

Ends at a **live, syncing, publicly-reachable RPC node**. Chainlink node / DON /
oracle-job configuration is **out of scope** (handed to Joakim once the RPC is up)
on **both** planes. The plane is chosen at [Step 0](#step-0--vm-or-k8s-class-branch--do-this-first);
the steps above are the VM flow, the [k8s runbook](https://docs.chainlayer.cloud/operations/kubernetes/spin-up-a-network-k8s/)
is the Kubernetes flow.
