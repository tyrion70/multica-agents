---
name: Move cloudinit from ide2 to ide0 — needs cloudinit regenerate first
description: After PBS restore the cloudinit drive often lands on ide2; the new TF module hardcodes ide0. Naively setting ide0 fails with "cloud-init drive is already attached at 'ide2'" even after delete=ide2. Fix is to call PUT /qemu/<vmid>/cloudinit (regenerate) first.
type: feedback
originSessionId: 9fbf0170-b405-4e85-80f9-b25d22615a9d
---
After a PBS restore the cloudinit drive sometimes lands on `ide2` instead of `ide0`. The Prox9 TF module hardcodes `interface = "ide0"` so we need to relocate it before TF imports the VM.

**The naive sequence fails:**

```bash
# Doesn't work — Proxmox keeps an internal cloudinit attachment record
PUT /qemu/<vmid>/config -d "delete=ide2&ide0=<storage>:cloudinit"
# → 400: "ide0 - cloud-init drive is already attached at 'ide2'"
```

Even running `delete=ide2` first and then `ide0=...` in a separate PUT fails. Proxmox is checking some internal "cloudinit-drive-currently-attached" state, not the config.

**The working sequence (simpler than the original — found 2026-04-30):**

```bash
# 1. With ide2 currently set to the cloudinit volume and NO pending changes on ide2:
PUT /nodes/<node>/qemu/<vmid>/config -d "delete=ide2"

# 2. Then attach on ide0:
PUT /nodes/<node>/qemu/<vmid>/config --data-urlencode "ide0=<storage>:cloudinit"
```

That's it. Two PUTs. Proxmox auto-creates the volume on ide0 attach if it doesn't exist; if the old `vm-<vmid>-cloudinit` volume still exists in storage it gets reused (and the API stops complaining once ide2 has no pending state).

**The trap that wastes hours:** if you run any FAILED PUT for ide0 before deleting ide2 (e.g. tried to "set both at once" first), the failed delete on ide2 gets queued as a **pending change** even on a stopped VM. The API now keeps refusing every subsequent ide0 PUT with `ide0 - cloud-init drive is already attached at 'ide2'` because the pending delete hasn't applied yet — even though `/config` shows ide2=null.

To recover from that stuck state:

```bash
# Clear the pending delete on ide2 (resets it back to its original value)
PUT /nodes/<node>/qemu/<vmid>/config -d "revert=ide2"
# Verify: GET /pending — ide2 should show value=... but no `delete: 1` field
# Then proceed with the two-step working sequence above.
```

You can confirm pending pollution by hitting `GET /qemu/<vmid>/pending` — a stuck delete shows up as `{key: ide2, value: ..., delete: 1}`. Healthy state has just `{key: ide2, value: ...}` with no `delete` field.

**Why:** observed during paloma-validator migration (vmid 235) on 2026-04-29 (original 3-step DELETE+regenerate workaround), and refined on lava-test1-signer (vmid 240) on 2026-04-30 once the pending-pollution mechanism was understood. The original DELETE-volume + regenerate dance also works but is unnecessary if you don't queue a failed PUT first.

**How to apply:** during Phase 3 hardware fixes, if `ide2` is set on the restored VM and `ide0` isn't, run the three-step sequence above before/instead of trying a single config PUT.
