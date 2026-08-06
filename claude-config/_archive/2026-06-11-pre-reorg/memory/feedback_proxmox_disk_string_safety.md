---
name: Proxmox disk-string PUT safety — read first, flip flags only
description: When updating scsi/net device config on a Proxmox VM, always GET the current string first and only flip the specific flags you intend to change. Never construct disk strings from memory, never use placeholder MACs, never delete unused0 without verifying it isn't the real disk.
type: feedback
originSessionId: 9fbf0170-b405-4e85-80f9-b25d22615a9d
---
When applying hardware fixes to a Proxmox VM via `PUT /nodes/<n>/qemu/<vmid>/config`, **never construct disk or net strings from scratch**. Always:

1. **GET the current config first.** Read the exact string for each `scsiN`, `virtioN`, `netN`, `efidiskN`, `ideN` device.
2. **Flip only the flags you intend to change** (e.g. `backup=1`→`backup=0`, `discard=on`→`discard=ignore`, `aio=native`→`aio=threads`, add `ssd=1`, set `firewall=0`). Preserve the storage path, volume name (e.g. `vm-233-disk-1`), the size, the MAC address, the bridge, the VLAN tag, and every other flag.
3. **Never use a placeholder MAC** like `BC:24:11:00:00:01`. The MAC must be exactly what's already on the device, otherwise networking and cloud-init associations break.
4. **Be alert to disk numbering.** After a Prox9 restore the volume names get reassigned (e.g. EFI lands at `vm-XXX-disk-0`, the OS disk at `vm-XXX-disk-1`). The new ordering is not the same as Prox7's. Read `scsiN`/`efidiskN` in the actual config before writing back.
5. **Never blindly `delete=unused0`.** A disk in `unused0` may be the real OS disk that got bumped because something earlier overwrote `scsi0` to point elsewhere. Inspect first; if `unused0` matches the size of an expected disk, re-attach it (`scsi0=<vol>,...`) instead of deleting.

**Why:** During the heimworks-dev-hx-signer migration (Phase 3, 2026-04-29), I rebuilt the `scsi0` string from memory using `vm-233-disk-0` (which was actually the 1M EFI disk) and a placeholder MAC. The 20G OS disk got pushed to `unused0`. My follow-up "fix" included `delete=unused0`, which destroyed the OS disk. Recovery required a full re-restore from PBS. A careful read-flip-write would have avoided both the mistake and the destructive recovery step.

**How to apply:** This rule covers ALL config PUTs that touch `scsiN`, `virtioN`, `sataN`, `netN`, `efidiskN`, `ideN`, or any disk reference. Single-flag PUTs like `lock=backup`, `ciupgrade=0`, or `cpulimit=N` are safe because they don't touch composite strings.
