---
name: Prox9 VMID convention — next-free from 100
description: When restoring a VM onto Prox9 during the Proxmox 7→9 migration, always pick the next-free VMID starting the search from 100, never reuse the original Prox7 VMID
type: feedback
originSessionId: 9fbf0170-b405-4e85-80f9-b25d22615a9d
---
When restoring a VM to Prox9 (`clusters/nl2_c4/`), pick the next-free VMID by scanning upward from 100. Never reuse the original Prox7 VMID — it may already be taken on Prox9, or its reuse can collide with later migrations.

**Why:** This is the established convention for the Proxmox 7→9 migration — the user pointed it out twice now. The migration plan says "Use next available VMID (not the original — may conflict)." Skipping the lookup and reusing the source VMID has caused conflicts before.

**How to apply:**
- Before each restore, query `/cluster/resources?type=vm` on Prox9, collect taken vmids, find smallest free integer ≥ 100.
- Pass that vmid to the restore POST and record it for the TF `import` block in Phase 4.
- Earlier migrations landed in the 156–229 range — that's still the working zone.
