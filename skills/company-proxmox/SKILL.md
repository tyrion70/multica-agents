---
name: company-proxmox
description: Operate ChainLayer's work Proxmox clusters — Prox7 (10.24.0.16) and Prox9 (10.34.0.163) — and the proxmox-iac Terraform/OpenTofu repo. Use for VM migrations (Prox7→9), restores, hardware fixes, TF imports/state moves, and any Proxmox API call against the work clusters. NOT for the homelab cluster (proxmox1-4 / 192.168.16.200) — that's the homelab skill. Contains hard safety rules from a real destroyed-OS-disk incident.
---

# ChainLayer Proxmox (Prox7 / Prox9 + proxmox-iac)

## Which cluster am I talking to?

| Cluster | Endpoint | Role |
|---|---|---|
| **Prox7** | `https://10.24.0.16:8006` | Legacy (nl2), being decommissioned |
| **Prox9** | `https://10.34.0.163:8006` | Target (nl2_c4) |

The homelab cluster (`proxmox1..4`, master `192.168.16.200`) is a **different
environment** — personal workloads. If the task says "clone the workstation
VM" you're in the wrong skill; use homelab. Tokens for the work clusters:
`projects/proxmox-migration/.env` (`FORTIOS_TOKEN_*`, Prox7/Prox9/PBS tokens)
and GCP Secret Manager project `gitlab-412312`. If a credential is missing
from both, look it up via the **bitwarden** skill (`company` folder) — and
store newly minted tokens there too.

## ⚠️ Rule #1 — disk-string PUT safety (caused a destroyed OS disk)

Any `PUT /nodes/<n>/qemu/<vmid>/config` touching `scsiN`, `virtioN`, `sataN`,
`netN`, `efidiskN`, `ideN`:

1. **GET the current config first.** Read the exact device string.
2. **Flip only the flags you intend to change** (`backup=1`→`0`, add `ssd=1`,
   `firewall=0`, …). Preserve volume name, size, MAC, bridge, VLAN, every
   other flag. **Never construct a disk/net string from memory.**
3. **Never use a placeholder MAC** — breaks networking + cloud-init binding.
4. **Watch disk numbering after restore** — Prox9 reassigns volume names (EFI
   can land at `disk-0`, OS at `disk-1`). Read before writing.
5. **Never blindly `delete=unused0`** — it may be the real OS disk that got
   bumped. If its size matches an expected disk, re-attach, don't delete.

Single-scalar PUTs (`ciupgrade=0`, `cpulimit=N`, `lock=backup`) are safe.
History: heimworks-dev-hx-signer (2026-04-29) — a from-memory `scsi0` string +
`delete=unused0` destroyed the OS disk; full PBS re-restore required.

## Migration conventions (Prox7 → Prox9)

- **VMID**: next-free scanning up from 100 on Prox9 (`/cluster/resources?type=vm`).
  **Never reuse the Prox7 VMID.** Record the chosen vmid for the TF import.
- **Silence alerts BEFORE any action** — use the AM v2 tailnet API (see the
  `grafana-monitoring` skill for the full silence contract and example payload).
  POST to any monitoring2 AM peer (`http://alertmanager-node-{1a-nl2v,2a-no1v,3a-de2v}.chosts.io:9093/api/v2/silences`);
  match `instance` + `job` narrowly; set explicit `endsAt` (~48 h for migrations);
  include the Linear issue key in `comment`. Silences gossip to all 3 peers within
  ~30s. The old `silence-vm.sh` script in `projects/proxmox-migration/` is stale —
  do not use it.
- **`removed` blocks merged BEFORE stopping VMs** — otherwise TF restarts them.
- **Two-pass backup**: snapshot while running, then stop + incremental. Max 2
  concurrent backups, one per vmhost. PBS shows 0GB while in progress — don't
  judge size immediately.
- **After restore: do NOT start the VM.** Fix hardware stopped, report ready,
  stop. The user moves it to the target host and starts it themselves.
- **Hardware-fix checklist** (stopped VM, after restore):
  `ciupgrade=0` · `scsihw=virtio-scsi-single` · disks `backup=0,discard=ignore,ssd=1`
  (+`iothread=1` only with virtio-scsi-single) · `aio` per TF module (`threads`
  if module sets it, else `io_uring`) · net `firewall=0,mtu=9000` ·
  `cpulimit=<cores>,cpuunits=100` · cloud-init on **ide0**.
- **Cloudinit ide2→ide0**: two PUTs — `delete=ide2` first, then
  `ide0=<storage>:cloudinit`. Setting both at once fails AND pollutes pending
  state; recover a stuck `ide0 ... already attached at 'ide2'` loop with
  `revert=ide2` (verify via `GET /pending` — a stuck delete shows `delete: 1`).
- **Validators/signers → `clusters/nl2_c4_protected/`** (module
  `proxmox_vm_ubuntu_protected`). RPC/statesync/relay/archive → `nl2_c4`. If
  the VM's network is missing from the protected cluster's `proxmox-hosts.tf`,
  **add the network there** — don't demote the VM to non-protected.

## Terraform / OpenTofu rules

- **Relocating modules between cluster states: `tofu state mv`, not
  removed+import** — import only re-registers ~4 physical resources and the
  plan shows ~6 noisy "creates" per VM for bookkeeping (netbox, firewall
  options, null_resources). Runbook: pull both states → snapshot copies →
  `tofu state mv -state=source -state-out=target module.X module.X` → push
  **target first, then source** → verify both plans. Sequence vs the MR:
  CI plan green → state move → merge promptly. Use removed+import only when
  the resource was never in the source state (Track B) or the module schema
  genuinely differs.
- **LVM disk-size off-by-one**: the module adds `+1`, so
  `sum(vm_os_disk_size_lvm) = target_disk - 1` (99 for 100G, 49 for 50G).
  Sum == disk size → cosmetic 1G resize on every plan.
- **Persistent drift catalog** (recurs every plan, apply doesn't fix):
  - `mtu: 1500 -> 0` → `PUT .../config -d "delete=mtu"` on the VM.
  - dns servers removal → `PUT .../config -d "delete=nameserver"` (no reboot
    impact; only affects next cloud-init run).
  One-time drift (vga block, comment text, fortios subnet format,
  `enabled: null->true` on protected moves) applies clean once — just apply.
  Diagnostic: plan twice; persists → structural; persists after apply → use
  the API delete trick. Prefer that over `ignore_changes`.
- **Import gotchas**: check IP conflicts (cloud-init vs DNS vs netbox); check
  BIOS (`vm_bios = "seabios"` for some Track B VMs); import IDs use the node
  the VM is actually on now; CF record IDs change if external scripts recreate
  them — look up last; delete netbox entries right before merge (TF recreates);
  max 10 VMs per MR; `tofu fmt -recursive` before pushing (CI enforces).
- Local plan: `source projects/proxmox-migration/run-plan.sh` (`-lock=false`).

## Reference endpoints

- Netbox: `https://thebox2.cinternal.com/` (NOT netbox.chosts.io). Token:
  `gcloud secrets versions access latest --secret=netbox-terraform-rw-access-key --project=gitlab-412312`
- Alertmanager: `https://alertmanager.cinternal.com/`
- Tracking: `projects/proxmox-migration/vm-assignments.csv` + `migration-plan.md`.
- Every migrated VM gets a Linear issue (project "Proxmox 9 VM Migration in NL")
  — see the `linear-company` skill.

## Permission model

✅ Without asking: all GETs (config, status, pending, cluster resources,
storage), `tofu plan`, rendering TF changes locally.

🛑 Ask first: starting/stopping/deleting VMs, any disk-string PUT (state the
exact before→after string in the confirmation), `delete=unusedN`, PBS restore
target/vmid choice, `tofu apply` or `state push`, removing backups. **Starting
a VM after restore is never yours to do** — report ready and stop.

## Reference detail (folded from memory)

Concrete invocations, JSON shapes, math examples, and dated incidents behind
the summarized rules above. Nothing here contradicts the sections above; it's
the long-form detail that was previously held in retired memories.

### Persistent-drift API delete trick — exact commands

The BPG provider can't unset some Proxmox attributes via the API, so the drift
recurs on every plan even after `tofu apply`. Clear the underlying Proxmox
attribute directly:

```bash
# mtu: 1500 -> 0 drift  (Proxmox stores explicit mtu, API re-reads it as 0/default)
curl -sk -X PUT -H "Authorization: PVEAPIToken=$PROX9_TOKEN" \
  "$PROX9_URL/api2/json/nodes/<node>/qemu/<vmid>/config" -d "delete=mtu"

# dns servers removal drift  (cloud-init nameserver line carried over from Prox7 origin)
curl -sk -X PUT -H "Authorization: PVEAPIToken=$PROX9_TOKEN" \
  "$PROX9_URL/api2/json/nodes/<node>/qemu/<vmid>/config" -d "delete=nameserver"
```

- `delete=mtu` clears the explicit mtu so state and config both consistently
  read 0/default. (Setting `vm_mtu = 0` in the module also clears it but is the
  wrong direction.)
- `delete=nameserver` clears the cloud-init nameserver line. **No reboot
  impact** — running VMs keep their `/etc/resolv.conf`; only matters on the
  next cloud-init reboot.
- Prefer this over `lifecycle { ignore_changes = [...] }`, which is permanent
  but masks legitimate future changes. Only reach for `ignore_changes` if the
  drift recurs even after the API delete trick (rare), or the attribute is one
  TF should never manage.

**One-time drift detail** (applies clean once, then stays clean — just apply):

| Drift | Cause |
|---|---|
| `+ vga { memory=16, type=std, clipboard=null }` | import doesn't populate `vga` block in state, but module sets it |
| `comment: "Managed by Terraform - Protected" -> "Managed by Terraform in proxmox-iac"` | older provider/module wrote one tag, current default is the other |
| `fortios subnet: "IP MASK" -> "IP/32"` | fortios provider serialization changed between versions; recurs only if provider version downgrades |
| `network_device.enabled: null -> true` | non-protected module's dynamic network_device doesn't set `enabled`; protected module sets it explicitly (only on non-protected → protected moves) |

**Dated incident references:**
- mtu drift first observed: OPS-1738 fuel migration (2026-04-29) — never goes
  clean even after apply.
- dns drift first investigated: OPS-1764 minecraft pilot review (2026-04-30) —
  paloma-validator (vmid 238) showed it persisting after the OPS-1741 apply.
- enabled drift: OPS-1744 protected-relocation MR !995 (2026-04-30) — only on
  non-protected → protected module moves.

### Cloudinit ide2 → ide0 — pending-state shapes and recovery

The naive "set both at once" PUT fails because Proxmox tracks an internal
cloudinit-drive attachment separate from `/config`:

```bash
# FAILS — 400: "ide0 - cloud-init drive is already attached at 'ide2'"
PUT /qemu/<vmid>/config -d "delete=ide2&ide0=<storage>:cloudinit"
```

Working sequence is two separate PUTs (`delete=ide2`, then `ide0=...`);
Proxmox auto-creates the ide0 volume on attach (reusing the old
`vm-<vmid>-cloudinit` volume if it still exists). The trap: any FAILED ide0 PUT
run *before* `delete=ide2` queues the ide2 delete as a **pending change** (even
on a stopped VM), and the API then refuses every later ide0 PUT with the same
"already attached at 'ide2'" error — even though `/config` shows `ide2=null`.

Recover the stuck state, then redo the two-step sequence:

```bash
PUT /nodes/<node>/qemu/<vmid>/config -d "revert=ide2"
```

Confirm pending pollution via `GET /qemu/<vmid>/pending`:
- Stuck delete: `{key: ide2, value: ..., delete: 1}`
- Healthy:      `{key: ide2, value: ...}`  (no `delete` field)

Incidents: paloma-validator (vmid 235, 2026-04-29) used the original 3-step
DELETE-volume + regenerate workaround; lava-test1-signer (vmid 240,
2026-04-30) refined it to the two-PUT form once the pending-pollution
mechanism was understood. The DELETE-volume + regenerate dance still works but
is unnecessary if you never queue a failed PUT first.

### `tofu state mv` — full pull→snapshot→mv→push runbook

Why state mv beats removed+import: `removed`+`import` only re-registers ~4
physical resources per VM (VM, CF, fortinet NL2, fortinet NO1). The other ~6
bookkeeping resources (netbox VM/interface/IP/primary, `null_resource.netbox`,
`proxmox_virtual_environment_firewall_options`) aren't in the new state, so the
plan shows ~6 noisy "creates" per VM. `state mv` moves the whole module — every
resource slots in with no diffs, leaving only attribute drift.

```bash
mkdir -p ~/tf-state-mv-$ISSUE && cd ~/tf-state-mv-$ISSUE

# Pull both states (read-only)
( cd <repo>/clusters/<src> && tofu state pull ) > source.tfstate
( cd <repo>/clusters/<tgt> && tofu state pull ) > target.tfstate

# Snapshot
cp source.tfstate source.tfstate.$(date +%Y%m%d-%H%M)
cp target.tfstate target.tfstate.$(date +%Y%m%d-%H%M)

# Move whole module(s)
tofu state mv -state=source.tfstate -state-out=target.tfstate \
  module.<name> module.<name>

# Push back: target FIRST, then source
( cd <repo>/clusters/<tgt> && tofu state push ~/tf-state-mv-$ISSUE/target.tfstate )
( cd <repo>/clusters/<src> && tofu state push ~/tf-state-mv-$ISSUE/source.tfstate )

# Verify
( cd <repo>/clusters/<src> && tofu plan -lock=false )   # expect: nothing for moved VMs
( cd <repo>/clusters/<tgt> && tofu plan -lock=false )   # expect: only attribute drift
```

Merge ordering matters because MR config and state must land close together
(either inversion makes one cluster plan "destroy" and the other "create"):
1. CI plan green on the MR (plan-only)
2. Run the state-move runbook
3. Merge MR promptly (apply against the new state is near no-op)

The `proxmox_vm_ubuntu` vs `proxmox_vm_ubuntu_protected` modules are **not
byte-identical**: protected uses a static single `network_device` (vs the
non-protected `dynamic "network_device"` with `vm_extra_interface` support) and
adds `enabled = true` plus `lifecycle { prevent_destroy = true }`. These cause
some first-plan attribute drift after relocation regardless of method.

### LVM disk-size off-by-one — module formula and sum table

`modules/proxmox_vm_ubuntu/main.tf` computes the Proxmox OS disk size as:

```hcl
vm_os_disk_size_combined = (
  var.vm_os_disk_size_lvm.tmp +
  var.vm_os_disk_size_lvm.home +
  var.vm_os_disk_size_lvm.var +
  var.vm_os_disk_size_lvm.varlog +
  var.vm_os_disk_size_lvm.root + 1   # ← THIS +1
)
```

So set `sum(vm_os_disk_size_lvm) = target_disk_size - 1`. Setting sum = target
size produces a cosmetic but reviewer-confusing `disk_size_gb: 100 -> 101`
resize on every plan. Common sums in use:

| Target disk | Sum used | # of existing VMs |
|---|---|---|
| 50G | 49 | 27 |
| 76G | 75 | 9 |
| 85G | 84 | 8 |
| 100G | 99 | 27 |
| 150G | 149 | 13 |

Worked example for 100G: `root=71, tmp=4, home=5, var=5, varlog=15` sums to 100
(wrong); drop `root` to 70 so the sum is 99. Discovery: OPS-1795 (2026-05-01) —
initial 7-module commit set all sums equal to disk size; fix was a single `-1`
on `root` per module.

### Disk-string PUT safety — concrete failure mode

The destroyed-disk incident in detail (heimworks-dev-hx-signer, Phase 3,
2026-04-29): a `scsi0` string was rebuilt from memory using `vm-233-disk-0`
(which was actually the 1M EFI disk) plus a placeholder MAC. The 20G OS disk
got pushed to `unused0`; the follow-up "fix" included `delete=unused0`, which
destroyed the OS disk and required a full PBS re-restore. Specific flag flips
that are legitimate on a read-flip-write: `backup=1`→`backup=0`,
`discard=on`→`discard=ignore`, `aio=native`→`aio=threads`, add `ssd=1`, set
`firewall=0`. Preserve storage path, volume name (e.g. `vm-233-disk-1`), size,
MAC, bridge, VLAN tag, and every other flag. If `unused0` matches the size of
an expected disk, re-attach it (`scsi0=<vol>,...`) — don't delete.
