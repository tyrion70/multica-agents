---
name: Always ask user when something unexpected happens
description: NEVER make autonomous decisions when something goes wrong — always stop and ask the user
type: feedback
originSessionId: 49c8f697-fba4-45d4-9fc7-93f696d11ebc
---
If ANYTHING doesn't go as planned during migration (backup fails, wrong size, restore error, unexpected state, VM not stopping, etc.) — STOP immediately and ask the user what to do. Do NOT make a judgment call and proceed.

**Why:** User restored hyperliquid from a 4-day-old snapshot without being asked, because the incremental backup came out 0GB. This resulted in stale data on a running VM. The user should have been consulted before using an old snapshot.

**How to apply:** When any step produces an unexpected result:
1. Stop all automation
2. Report exactly what happened
3. Present options
4. Wait for explicit user instruction before proceeding
