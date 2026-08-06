---
name: Homelab + Hetzner cluster topology
description: Pointer to the canonical overview of Peter's home Proxmox cluster + off-site hetzner backup + UniFi Terraform scaffold
type: project
originSessionId: 31e6e6f5-20fa-4d51-a874-93b98763a5d4
---
Peter runs a 4-node Proxmox VE cluster `Cluster` (proxmox/proxmox2 towers with GPUs, proxmox3/4 EPYC rack servers) plus a standalone Proxmox node at hetzner.252h.org for off-site backup. UniFi UDM Pro Max ("Putten") is the gateway. Tailscale subnet routing connects the home LAN to hetzner's 10.99.0.0/24.

**Why:** Architecture spans many moving parts (PBS chain, MinIO S3-backed datastore, PDM, Tailscale subnet routing, GPU passthrough, UniFi LAGs/static routes/VLANs) — easy to forget without a reference.

**How to apply:** When working on anything in this stack, **read `/Users/petervanmourik/claude/projects/proxmox/README.md` first** — that's the canonical entry point. It points to:

- `cluster-overview-2026-04-27.md` — full topology, VM inventory, PBS data flow, automation roadmap, hard rules from 2026-04-29 incident, TODO list
- ⚠️ `docs/postmortem-2026-04-29-wan-outage.md` — **read before any UniFi API write**. Caused a WAN outage. Documents UniFi partial-commit behavior + forbidden imports.
- `docs/network-topology.md` — physical L2 topology (root bridge = USW Pro Aggregation, prio 4096), AP placement, port utilization, decision flow for adding new devices. **Includes target-topology section** for the planned schuur → tuinkantoor + bijkeuken rack relocation
- `docs/network-relocation-plan.md` — phased migration plan for the relocation (pre-flight, procurement, cutover order, rollback)
- `snapshot-20260427-121821/` — point-in-time configs from the cluster-join day
- `infra/terraform/unifi/` — UniFi Terraform scaffold (key in `.secrets/unifi.env`, gitignored)
- `inventory/` — VM/cluster JSON dumps for reference
- `scripts/` — reusable helper scripts (unifi inventory, vm list, network template, port-profile creator, generated-config cleaner)

Verify current state with `ssh root@<ip>` before acting on anything from these docs — they're point-in-time snapshots, not live state.

## Critical access notes

- SSH to hetzner is on port **2822** (not 22): `ssh -p 2822 root@135.181.22.118` (or `root@hetzner.252h.org`).
- DNS naming under `252h.org`: `hetzner.252h.org` = off-site PVE+PBS; `pbs.252h.org` = local PBS VM 109 (192.168.19.1); `proxmox2.252h.org` = cluster master alias.
- Cluster master = proxmox2 = 192.168.16.151 (this is the IP PDM has registered as the homelab remote — only that one IP, not proxmox/proxmox3/proxmox4).
- Cluster join token IP for adding nodes is 192.168.16.200 (= `proxmox` host, original founder).
- PDM (Proxmox Datacenter Manager) lives on hetzner as **CT 101**, web UI on `:8443` reachable as `10.99.0.52:8443` via tailnet.
- MinIO lives on hetzner as **CT 100** (10.99.0.51:9000), bucket `pbs`, used as S3 backend for PBS datastore `minio`.
- UniFi API key is at `/Users/petervanmourik/claude/projects/proxmox/.secrets/unifi.env` (gitignored, chmod 600). Network app v10.3.55 on UDM Pro Max.

## Pending decisions blocking further automation work

- Secrets-management tool (sops+age, Vault, 1Password?) — needed before expanding Terraform secrets handling.
- IaC repo location (new vs existing, GitHub vs GitLab) — affects where to migrate `infra/terraform/`.
- Migration philosophy (rebuild from declarative vs `terraform import` existing) — different per VM class.
