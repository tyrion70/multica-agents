---
name: Proxmox 7 to 9 Migration
description: Decommissioning Proxmox 7 (nl2) by migrating VMs to Proxmox 9 (nl2_c4) via PBS backup/restore + Terraform import
type: project
originSessionId: 49c8f697-fba4-45d4-9fc7-93f696d11ebc
---
## Overview
Migrating all VMs from Proxmox 7 (nl2 cluster) to Proxmox 9 (nl2_c4 cluster) to decommission Prox7.

**Project location:** `projects/proxmox-migration/` — CLAUDE.md, migration-plan.md, vm-assignments.csv, .env, run-plan.sh

## Current Status (2026-04-21)
- **67 VMs migrated** to Prox9, running on target hosts (42% of 157 total)
- **33 pending** across waves 2-8, **15 validator-defer** in wave 8
- **24 decommission**, **17 deleted**
- **MRs:** !964 (27 VM imports) merged, !967 (11 removed blocks) merged, !969 (8 imports batch1) open, !970 (8 imports batch2) open
- 6 first-pass backups done for wave 4-5 VMs (306,314,338,158,272,124), 14 remaining (PBS space limited — clean old backups before more)
- External scripts (dns-chosts, proxmox-netbox) disabled during migration
- **Notifications:** ntfy.sh topic `ac4cbdd7f1ba30b9118f6f1c8815f9cb` for migration alerts
- **Silences:** `./silence-vm.sh create <name> 48 <network>` — silences instance + network + chainlayer_network
- **Grid VMs need custom networks** in proxmox-hosts.tf: grid-exit uses 194.169.245.x, grid-router uses 10.26.0.x/VLAN 26
- **axelar-main-statesync renamed** from 1b to 2a in TF (new CF record created, old one kept for now)
- **axelar-main-validator excluded** from current migration — potential issue starting VM with >4TB base disk

## Key Decisions
- Restore <6TB VMs directly to **target host** on ceph (no vmhost3 needed). VMs ≥6TB to vmhost3 local ZFS.
- Two-pass backup: snapshot while running (bulk data), then stop + incremental (minimal downtime)
- `skip_provisioning = true` + `unmonitored = true` for all imported VMs
- Netbox: delete old entries before merge, TF creates fresh (NL2-CLUSTER4)
- Fortinet addresses + Cloudflare DNS: import existing
- Check for fortinet services+policies on VMs with `firewall_internet_ports_tcp/udp`
- Every VM gets a Linear issue in project "Proxmox 9 VM Migration in NL"
- Max 2 concurrent backups on different vmhosts. One per vmhost at a time.
- `removed` blocks must be merged BEFORE stopping VMs (prevents TF from restarting them)
- Silence alerts BEFORE any migration action: `./silence-vm.sh create <name> 48 <network>`
- Do NOT start VMs after restore — user moves disks from ceph to local ZFS first, then starts
- PBS snapshot size shows 0GB while in progress — don't check size immediately after vzdump

## Critical Procedure: After Restore, Before Starting VM
Fix ALL hardware while VM is stopped on vmhost3:
1. `ciupgrade=0`
2. `scsihw=virtio-scsi-single` (if currently `virtio-scsi-pci`)
3. Disks: `backup=0,discard=ignore,ssd=1`. Only add `iothread=1` if scsihw=virtio-scsi-single
4. `aio`: keep `threads` if TF module explicitly sets it, otherwise `io_uring`
5. Network: `firewall=0,mtu=9000`
6. CPU: `cpulimit=<cores>,cpuunits=100`
7. Cloud-init: ensure on `ide0` (not `ide2`)
**Never construct disk strings manually** — read actual string and only flip the flags that differ

## Critical: Creating TF Import Blocks
- Check for IP conflicts before migrating (compare cloud-init IP vs DNS vs netbox)
- Check BIOS type: Track B VMs may use seabios → set `vm_bios = "seabios"`
- Check fortinet services+policies (not just addresses) for VMs with firewall ports
- Import IDs must use actual current node (check where VM really is, not where it was restored)
- Cloudflare record IDs change if external scripts recreate them — look up last
- Run local `tofu plan` to verify before pushing MR: `./run-plan.sh` (from project dir)
- Delete netbox entries immediately before merge (TF creates fresh ones)
- After restoring from ceph, update TF host reference to final location once migrated
- LVM root value: set so `root + tmp + home + var + varlog + 1 = actual_disk_size`. Module adds +1.
- VMs with OS disk < 50GB cannot match (module minimum is 50GB) — accept expansion
- Non-LVM VMs: add comment explaining LVM values control disk size
- Max 10 VMs per MR to keep reviews manageable
- Renamed VMs need new CF record created (old one can be kept temporarily)
- Check `proxmox-hosts.tf` for network definitions — VMs on unusual VLANs may need new entries
- `tofu fmt` before pushing — CI checks formatting

## API Access
- `.env` at `projects/proxmox-migration/.env` — source for Prox7/Prox9/PBS/fortinet tokens
- **Netbox URL:** `https://thebox2.cinternal.com/` (NOT netbox.chosts.io)
- **Alertmanager URL:** `https://alertmanager.cinternal.com/` (NOT alertmanager-node-1a-nl2v.chosts.io)
- **Netbox token:** `gcloud secrets versions access latest --secret="netbox-terraform-rw-access-key" --project="gitlab-412312"`
- **Cloudflare token:** `gcloud secrets versions access latest --secret="proxmox-automation-cloudflare-api-token" --project="gitlab-412312"`
- GCP Secret Manager project: `gitlab-412312`
- Prox9 token needs: VM.Audit, VM.PowerMgmt, VM.Backup, VM.Allocate, VM.Config.Disk, VM.Config.CPU, VM.Config.Cloudinit, SDN.Use, Datastore.AllocateSpace
- Local plan: `source projects/proxmox-migration/run-plan.sh` (uses `-lock=false`, needs `tofu init` after new modules)

## Files
- `vm-assignments.csv` + `vm-assignments.xlsx` — master tracking with wave, status, target_host, 1st backup, moved columns
- `migration-plan.md` — full procedure + lessons learned
- `run-plan.sh` — local tofu plan script with all secrets + plan summary parser
- `silence-vm.sh` — alertmanager silence script (instance + network + chainlayer_network)
- `host-inventory.xlsx` — hardware inventory with disk serials for all vmhosts

## Wave Structure
- Waves 1-4: standard migrations (mostly done)
- Wave 5: validator nodes (coordinated migration)
- Wave 6: database VMs (postgres migration)
- Wave 7: >5TB VMs (special handling)
- Wave 8: remaining validator-defer (TBD)
