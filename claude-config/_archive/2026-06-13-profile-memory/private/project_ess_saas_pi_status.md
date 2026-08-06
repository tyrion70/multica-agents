---
name: ESS saas-pi-appliance — work-in-progress status pointer
description: Where to look first when resuming saas-pi-appliance work after a context compaction.
type: project
originSessionId: 1fdc6b8e-07b1-48ce-9987-7daf406c5d29
---
The full resume guide lives in-tree at
`repositories/ess/.planning/projects/saas-pi-appliance/STATUS.md`.
Always read that file first when picking up this project.

**Why:** the saas-pi-appliance build spans 30+ commits across 5
branches with tags `poc-1.0`, `m0-1.0`, `m1-1.0` and an in-progress
M3 branch. STATUS.md is updated each time a session ends so the
next session has the branch, the next sub-task, and the test
commands at hand.

**How to apply:**
- After any context compaction, read STATUS.md before touching
  code.
- Branch state: `feat/m3-cloud-relay` (HEAD as of 2026-05-11) is
  current; M3.4 done, M3.5 (full 3-service E2E) is next.
- A `/loop 60m continue next step` (job `4979cf4f`) fires hourly
  in this session; expires 7 days from creation.
