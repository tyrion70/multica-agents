---
name: homelab
description: Operate Peter's homelab — 4-node Proxmox cluster (proxmox/proxmox2/proxmox3/proxmox4), UniFi UDM-Pro Max network, Hetzner off-site box, Mikrotik CRS812 switch. Use whenever running API/CLI commands against any of these systems, especially anything that mutates state. Contains hard DON'Ts around UniFi and Proxmox API keys that have already caused outages.
---

# Peter's homelab

A 4-node Proxmox cluster at the user's home, plus a UniFi-managed network (UDM-Pro Max + UniFi switches), a Mikrotik CRS812 100G/400G switch, and an off-site Hetzner box that holds the backup mirror.

Use this skill whenever you touch the homelab. It is **not** the chainlayer prod environment — that lives under separate context. Homelab boxes are Peter's personal infra; some pieces (his email, his ISP, his family's WiFi) ride on it, so outages are real.

## Step 0 — what NOT to do (read this first)

### UniFi UDM-Pro Max API

The UniFi controller has burned us once already. A **6-hour WAN1 outage on 2026-04-29** was caused by a Terraform PUT against `/rest/networkconf/<internet-delta-id>`. The full postmortem lives at `/home/peter/claude/projects/proxmox/docs/postmortem-2026-04-29-wan-outage.md` — read it before any write.

**Hard rules, no exceptions:**

1. **PUTs are partial-commit.** A 4xx response does *NOT* mean "no fields applied". UniFi accepts and writes field-by-field; if validation later in the body fails, earlier fields stay written. Treat every PUT as a possibly-half-applied transaction.
2. **GET → modify exactly one field → PUT the same body back.** Never re-derive the body from a Terraform schema or a hand-written template. The live object is authoritative; Terraform's view drifts.
3. **Never write to a UniFi site without an out-of-band recovery path.** If you're running over Tailscale/SDWAN into the same UDM you're modifying, you have *no* path back if the write breaks routing. Either: (a) someone is physically at the site, or (b) the management traffic does not depend on what you're changing.
4. **`-target` for first applies.** Never bulk-apply 10 resources where one mis-PUT can chain.
5. **Read the diff.** `enabled: false` on a WAN is a stop sign even if Terraform claims it's "no change".

**Forbidden imports / forbidden writes — never touch via API or Terraform:**

- `unifi_wan` (any) — WAN config is UI-only
- `unifi_network` where `purpose != corporate` (i.e. `wan`, `vlan-only`, `site-vpn`, `remote-user-vpn`, `guest`) — system or VPN-managed
- `unifi_radius_profile.default` — system-managed
- `unifi_device.<udm>` — never write to the gateway device itself
- Anything in the API response with `attr_no_edit=True` or `attr_no_delete=True`

**UDM-Pro Max API does not support:**
- `portforward` with `proto=gre` or `proto=47` — TCP/UDP only (per direct probe).
- "DMZ host" via API — no `dmz_*` field exposed in `wan-networkconf`.
- Anything below L4 — no IP-protocol-level routing tweaks.
- Workaround for GRE / extra public IPs: terminate the GRE on the Hetzner box (it has a real public IP) or use a small VPS as relay. SSH-then-iptables on the UDM is NOT durable — UniFi-OS clobbers it on upgrade unless persisted in `/mnt/data/on_boot.d/*.sh`.

### Proxmox API / CLI

The Proxmox 4-node cluster has its own foot-guns, all related to mutating disk state.

**Hard rules:**

1. **Disk-string PUTs: GET first, flip exactly the flag you mean to change.** Never use a placeholder MAC. Never blindly delete `unused0` etc. — those entries are the only remaining pointer to a real ZVol; deleting the line deletes the data.
2. **VMIDs are never reused.** Scan from 100 upward with `pvesh get /cluster/nextid` or the documented homelab map (see `/home/peter/claude/projects/proxmox/cluster-overview-2026-04-27.md`). The cluster has gaps; that's fine. Reusing a freed VMID is asking for confusion later.
3. **`local-zfs` storage uses `sparse 1` by default.** If you create a ZVol manually with `zfs create -V`, it'll be thick-provisioned and reserve the full size. To match Proxmox-managed behavior, `zfs set refreservation=none <vol>` afterwards.
4. **Cloud-init slot moves (`ide2 → ide0` etc.)** can't be done with a naive PUT — you get "already attached". Need to delete the cloudinit volume and call the cloudinit regenerate endpoint first.
5. **For cluster relocations of Terraform-managed VMs**, prefer manual `tofu state mv` between state files over remove-then-import. Cleaner plan, no bookkeeping-resource creates.
6. **LVM disk-size off-by-one**: the proxmox-iac module adds +1 to `vm_os_disk_size_lvm`; set sum so that final size = target − 1 (e.g. `99` for 100 G).
7. **`virtio-scsi-pci` silently ignores `iothread=1`.** Use `virtio-scsi-single` if you actually want one iothread per disk. The legacy controller will not warn at config time — only at VM start, in a non-fatal `WARN:` line.
8. **PBS VM is migratable BECAUSE its backing is a ZVol on `local-zfs`.** If anyone proposes "let's bind-mount a host ZFS dataset via virtiofs", that breaks `qm migrate`. The migration story is the whole point of PBS-as-VM, not PBS-on-host.
9. **Persistent drift catalog** (these come back if you don't watch for them): `mtu`, `dns`, `comment`, `vga`, subnet. Documented fixes in memory `feedback_proxmox_persistent_drift`.

### Mikrotik CRS812-8DS-2DQ-2DDQ

- Cable EEPROMs that report `Memory Map Revision >= 5` (i.e. CMIS, not SFF-8636) **will not link with ConnectX-5 Ex** even on latest FW 16.35.8008. CMIS predates CX-5's silicon. Use SFF-8636 cables (plain QSFP28-to-QSFP28 100G NRZ DACs).
- QSFP-DD cages physically accept QSFP28 modules (backward-compatible). Lanes 5-8 are unused with a QSFP28 inserted.
- `qsfp56-*` ports are 200G PAM4 native, accept QSFP28 100G NRZ modules.
- Default `RouterOS speed=` on QSFP-DD sub-interfaces is one-lane-per-sub-iface (8×50G). To get 4×100G breakout: `set [find name=qsfp56-dd-1-1] auto-negotiation=no speed=100G-baseCR2` — pairs adjacent lanes (1+2, 3+4, 5+6, 7+8).

### Hetzner (off-site)

- SSH port is **2822**, not 22: `ssh -p 2822 root@hetzner.252h.org`
- Default `iptables -P INPUT DROP`. Custom allowlist rules go in `/mnt/data/on_boot.d/*.sh` to survive boot — `iptables-save` is **not** persisted by default.
- Self-signed cert on PVE/PBS UI; reachable from home WAN (`62.45.81.180`) and Tailscale only.
- Don't `apt-get update` and panic — `proxmox-enterprise` repo returns 401 because there's no subscription. Debian core still installs fine.
- Never use `python3 -m http.server` for serving multi-GB files. Use the nginx config already on the box (port 51234, `/tank/video` root).

## Topology cheat-sheet

| Box | Role | LAN IP | Tailscale | Notes |
|---|---|---|---|---|
| `proxmox` | PVE node, GPU passthrough (plex/jellyfin Intel Arc A380) | `192.168.16.200` | — | VMs that need the GPU stay here |
| `proxmox2` | PVE node, RTX 5070 passthrough (windows11-1) | `192.168.16.151` | — | VMs that need the 5070 stay here |
| `proxmox3` | PVE node, ConnectX-5 Ex 100G installed (empty otherwise) | `192.168.19.81` | — | Available as a workhorse |
| `proxmox4` | PVE node, claude-workstation-01 + PBS VM live here | `192.168.19.82` | — | Most VMs land here today |
| `pbs` (VM 109 on proxmox4) | Proxmox Backup Server | `192.168.19.1` | — | 8 vCPU / 16 GB RAM, XFS on tuned ZVol; see `cluster-overview-*.md` for retention policy |
| `tailscale` (VM 112 on proxmox4) | Tailscale subnet router | `192.168.16.x` | yes | Advertises `192.168.6.0/24` + `192.168.16.0/22`; exit-node-capable. **SPOF** for off-site sync. |
| `hetzner` | Off-site PVE/PBS + MinIO + PDM | `135.181.22.118` (public) / `10.99.0.1` (TS) | `100.85.45.86` | SSH on **2822**. Advertises `10.99.0.0/24` over Tailscale. |
| `mikrotik` | CRS812-8DS-2DQ-2DDQ, RouterOS 7.19.6 | `192.168.19.250` | — | Username `admin`, see BW |

Per-VM map (current): `/home/peter/claude/projects/proxmox/cluster-overview-*.md`. The Markdown is a point-in-time snapshot — verify before acting.

## Public-IP and gateway facts

- **Home WAN (Putten, behind UDM-Pro Max, Caiway uplink):** `62.45.81.180`
- **ChainLayer corporate egress NAT:** `89.149.216.9`
- **UDM internal gateway:** `192.168.16.1` (cross-VLAN routing for `.16/22`, `.17/22`, etc.)
- **Hetzner public:** `135.181.22.118` (`hetzner.252h.org`)

## Storage classes inside the homelab

- Proxmox local-zfs (`rpool/data`, `sparse 1`) — primary VM storage on each PVE node, NVMe mirror-of-mirrors. Healthy at 10-20% used.
- PBS datastore `backups` (`192.168.19.1:8007/backups`) — local backup target. Now on **XFS on a tuned ZVol** (`volblocksize=64K`, `logbias=throughput`, `primarycache=metadata`, sparse, compression off). Was EXT4 on default zvol until 2026-06-10 maintenance window.
- PBS datastore `pbs` (on Hetzner, port 8007) — long-term offsite mirror. Pushed from local PBS via hourly sync.
- MinIO bucket `pbs` (Hetzner CT 100, `10.99.0.51:9000`) — S3-backed alternate datastore. ~817 GB of duplicate data; pending decommission.

## DNS & naming

- `<role>.252h.org` is the split-horizon convention (`hetzner.252h.org`, `pbs.252h.org`, `proxmox2.252h.org`). Configured in the `dns-chosts` repo for chainlayer; locally Pi-hole/UDM resolves these to LAN addresses.
- VMIDs 100–199 standard; 200+ for "special" cases (GPU passthrough).
- ZFS pool name `rpool` on every node so cluster-wide `local-zfs` works without per-node overrides.

## Backup schedule (post-2026-06-10 maintenance)

```
:10  vzdump --all → local PBS (fleecing enabled=1,storage=local-zfs)
:30  PBS prune (keep-last 2, hourly 24, daily 14, weekly 8, monthly 12, yearly 3)
:40  PBS sync local → Hetzner (push, verified-only true)
:50  PBS verify (ignore-verified true, outdated-after 30)
02:30  daily PBS garbage collection
21:00  daily vzdump of VM 109 (PBS itself) directly → Hetzner storage
```

GC was hourly until 2026-06-10; that was the root cause of a 7-hour backup hang and the rebuild. **Don't put it back to hourly.**

## Where the docs live

| Doc | Path |
|---|---|
| Cluster overview | `/home/peter/claude/projects/proxmox/cluster-overview-2026-04-27.md` |
| Network topology (current + target) | `/home/peter/claude/projects/proxmox/docs/network-topology.md` |
| Network relocation plan | `/home/peter/claude/projects/proxmox/docs/network-relocation-plan.md` |
| **UniFi WAN outage postmortem** | `/home/peter/claude/projects/proxmox/docs/postmortem-2026-04-29-wan-outage.md` |
| Project README | `/home/peter/claude/projects/proxmox/README.md` |

Snapshots are dated. Verify with live state (`ssh root@<ip>`, `pvesh get`, `qm config <vmid>`) before acting on what's written.

## Secrets

- **Bitwarden** (Vaultwarden at `https://192.168.19.11:8443`, account `peter@tyrion.nl`):
  - "UniFi UDM-Pro Max — homelab API keys" (item id `5573f432-...`) — `UNIFI_API_URL`, `UNIFI_API_KEY`, `WLAN_PSK`, `GUEST_PORTAL_PASSWORD`, `RADIUS_DEFAULT_X_SECRET`
- **Local env files** (gitignored):
  - `/home/peter/claude/projects/proxmox/.secrets/unifi.env` — same fields as the BW item
  - `~/.claude/secrets/bw-bootstrap.env` — BW client creds + master password (used by BW unlock automation)
- **Mikrotik**: BW item "Mikrotik CRS812-8DS-2DQ-2DDQ — homelab switch" (`MIKROTIK_HOST`, `MIKROTIK_USER`, `MIKROTIK_PASSWORD`)
- **Proxmox**: SSH key authentication (Tailscale-routed via VM 112). Root SSH allowed. No password expected.
- **IPMI** (Gigabyte boards on `proxmox3` + `proxmox4`): `proxmox3` BMC `192.168.16.240`, `proxmox4` BMC `192.168.16.241`. Custom admin password — not in BW yet, in the user's password manager. Confirmed working from his laptop.

## Useful operational queries

```bash
# Cluster master + per-node status
ssh root@192.168.19.82 'pvesm status; qm list; lxc list 2>/dev/null'

# ZFS pool health on a node
ssh root@<node> 'zpool list; zpool status'

# PBS datastore + GC + prune status
ssh root@192.168.19.82 'qm guest exec 109 -- /bin/sh -c "proxmox-backup-manager datastore list; proxmox-backup-manager garbage-collection list; proxmox-backup-manager prune-job list; proxmox-backup-manager verify-job list"'

# Mikrotik live ethernet state (creds in BW)
SSHPASS=<pw> sshpass -e ssh admin@192.168.19.250 '/interface ethernet print where running'

# UniFi via API (READ-ONLY by default; do not chain writes from this!)
. /home/peter/claude/projects/proxmox/.secrets/unifi.env
curl -sk -H "X-API-KEY: $UNIFI_API_KEY" "$UNIFI_API_URL/proxy/network/api/s/default/stat/device-basic" | jq '.data[].name'
```

## Things that surprise people

- **`bond-proxmox` on the Mikrotik (sfp56-7+8 LACP) IS the live link for proxmox4's old 10G card.** The comment in `proxmox4:/etc/network/interfaces` referencing "USW Pro Aggregation" is stale. Confirm with the LACP partner system-id before changing anything.
- **Mellanox MCX516A "CDAT" suffix = tall PCIe bracket**, not silicon revision. PSID `MT_0000000013` is what determines firmware compatibility. (Same firmware applies to MCX516A-CDA and MCX516A-CDAT.)
- **The `pbs:` and `hetzner:` storage names in PVE storage.cfg both have `prune-backups keep-all=1`.** That's a *PVE-side* hint; the real retention is enforced by **PBS prune-jobs** configured inside PBS (`/etc/proxmox-backup/prune.cfg`). Don't conclude "you keep everything forever" from the storage.cfg alone — check PBS-side first.
- **`/etc/network/interfaces` on PVE nodes uses custom NIC names (`nic0..nic4`)** via `/usr/local/lib/systemd/network/50-pmx-nicN.link` files that match by MAC. Replacing a NIC = rewrite that `.link` file with the new MAC; the names stay stable.

## What to do when something feels off

1. **First hypothesis is always "what did I just do".** Time-correlation between your last write and the user's reported problem is the strongest signal, not the weakest.
2. **Audit logs are the source of truth, not API responses.** UniFi audit log: Settings → System → Audit. Proxmox: `cat /var/log/pve/tasks/active`.
3. **STOP and ask on unexpected.** This is a rule the user explicitly set. Don't try to fix something forward; surface the surprise.
