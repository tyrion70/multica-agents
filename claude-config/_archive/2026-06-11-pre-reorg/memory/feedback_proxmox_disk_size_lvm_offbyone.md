---
name: vm_os_disk_size_lvm sum convention is disk_size minus 1 (module adds +1)
description: The proxmox_vm_ubuntu module computes Proxmox disk size as sum(vm_os_disk_size_lvm) + 1. Convention in proxmox-iac is sum = target_disk_size - 1 (e.g. 99 for 100G, 49 for 50G, 749 for 750G). Setting sum = target_disk_size produces a 1G plan drift on every imported VM.
type: feedback
originSessionId: 9fbf0170-b405-4e85-80f9-b25d22615a9d
---
The shared module `modules/proxmox_vm_ubuntu/main.tf` computes the Proxmox OS disk size as:

```hcl
vm_os_disk_size_combined = (
  var.vm_os_disk_size_lvm.tmp +
  var.vm_os_disk_size_lvm.home +
  var.vm_os_disk_size_lvm.var +
  var.vm_os_disk_size_lvm.varlog +
  var.vm_os_disk_size_lvm.root + 1   # ← THIS +1
)
```

Convention across proxmox-iac is: `sum(vm_os_disk_size_lvm) = target_disk_size - 1`, e.g.

| Target disk | Common sum used | # of existing VMs |
|---|---|---|
| 50G | 49 | 27 |
| 76G | 75 | 9 |
| 85G | 84 | 8 |
| 100G | 99 | 27 |
| 150G | 149 | 13 |

If you set sum = target_disk_size, every plan after import shows a 1G in-place resize (`disk_size_gb: 100 → 101`). Cosmetic but reviewer-confusing.

**How to apply:** when writing a new VM module for a Track-B import where actual disk on Prox9 is N GB, set the LVM values so they sum to **N - 1**. E.g. for 100G: `root=71, tmp=4, home=5, var=5, varlog=15` works (sum 100 → wrong); use `root=70` instead (sum 99). Verify before pushing with:

```python
import re; sum(int(v) for v in re.findall(r'(\w+)\s*=\s*(\d+)', body)['vm_os_disk_size_lvm'])
```

**Discovery:** OPS-1795 (2026-05-01). Initial commit of 7 modules all set sums equal to disk size; CI plan showed `disk_size_gb` updates of `+1` on every imported VM. Fix was a single -1 to `root` per module.
