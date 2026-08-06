---
name: tofu state mv vs removed+import for cluster relocation
description: When relocating a TF module from one cluster's state to another, prefer 'tofu state mv' between the two state files over the removed+import block flow — it preserves all bookkeeping resources (netbox, firewall_options, null_resources) and avoids ~6-per-VM noisy "creates" in the plan
type: feedback
originSessionId: 9fbf0170-b405-4e85-80f9-b25d22615a9d
---
When moving a module between two TF state files (e.g. `nl2_c4` → `nl2_c4_protected`), prefer the manual `tofu state mv` flow over the `removed { destroy = false }` + `import { }` blocks flow.

**Why state mv is cleaner:**

- `removed`+`import` only re-registers ~4 resources per VM (the actual physical things: VM, CF, fortinet NL2, fortinet NO1). The other ~6 bookkeeping resources (netbox VM/interface/IP/primary, null_resource.netbox, proxmox_virtual_environment_firewall_options) are NOT in the new state, so plan shows ~6 "creates" per VM. Reviewers can't easily tell what's a real change vs bookkeeping noise.
- `state mv` moves the entire module — all resources slot into the new state file with no diffs. Plan shows only attribute drift between the source and target module's serialization.

**Runbook (always pull → snapshot → mv → push):**

```bash
mkdir -p ~/tf-state-mv-$ISSUE && cd ~/tf-state-mv-$ISSUE

# Pull both states (read-only)
( cd <repo>/clusters/<src>      && tofu state pull ) > source.tfstate
( cd <repo>/clusters/<tgt>      && tofu state pull ) > target.tfstate

# Snapshot
cp source.tfstate source.tfstate.$(date +%Y%m%d-%H%M)
cp target.tfstate target.tfstate.$(date +%Y%m%d-%H%M)

# Move whole module(s)
tofu state mv -state=source.tfstate -state-out=target.tfstate \
  module.<name> module.<name>

# Push back: target FIRST, then source
( cd <repo>/clusters/<tgt> && tofu state push ~/tf-state-mv-$ISSUE/target.tfstate )
( cd <repo>/clusters/<src> && tofu state push ~/tf-state-mv-$ISSUE/source.tfstate )

# Verify with plans
( cd <repo>/clusters/<src> && tofu plan -lock=false )   # expect: nothing for moved VMs
( cd <repo>/clusters/<tgt> && tofu plan -lock=false )   # expect: only attribute drift
```

**Order of operations relative to MR merge:**

The state move and the MR merge must land close together. The MR config says module is in target and not in source; if state move happens before MR merge, plan in source = "destroy" and target = "create". If merge happens before state move, the same inversion. The right order is:

1. CI plan green on the MR (plan-only, not apply)
2. Run state-move runbook
3. Merge MR promptly (apply against the new state is near no-op)

**Caveat — the modules are not byte-identical even when they look similar:**

`proxmox_vm_ubuntu` vs `proxmox_vm_ubuntu_protected` differ in:
- `dynamic "network_device"` (with `vm_extra_interface` support) vs static single `network_device`
- protected adds `enabled = true` and `lifecycle { prevent_destroy = true }`

These cause some attribute drift on the first plan after relocation regardless of whether you use state mv or import. See `feedback_proxmox_persistent_drift.md`.

**When import (the removed+import flow) is still appropriate:**

- The source state never had this resource (Track B migration of a VM that was never in TF)
- Module schema is meaningfully different (different resource types, not just attribute drift)

For pure relocations across clusters where the same module family wraps the same provider resources, prefer state mv.
