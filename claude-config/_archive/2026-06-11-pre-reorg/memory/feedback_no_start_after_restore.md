---
name: Don't start VMs after restore
description: Never start restored VMs — user moves them to target host first, then starts manually
type: feedback
originSessionId: 49c8f697-fba4-45d4-9fc7-93f696d11ebc
---
Do NOT start VMs after fixing hardware on vmhost3. The user wants to live-migrate/move the VM to the target host first, then start it themselves.

**Why:** Starting on vmhost3 is pointless — it's a staging host. The VM needs to be on its target host before starting. Starting it prematurely wastes time and could cause issues.

**How to apply:** After restore + hardware fix, report the VM is ready and stop. Let the user handle the move + start.
