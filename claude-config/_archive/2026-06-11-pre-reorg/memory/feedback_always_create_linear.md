---
name: Always create Linear issues before coding
description: Never skip Linear issue creation, even for small fixes — user expects full traceability
type: feedback
---

Always create a Linear issue BEFORE starting any work, even small fixes and one-liner changes. Use the Linear branch name for the git branch. Every MR must reference a Linear issue.

**Why:** User relies on Linear for tracking all work across the team. Untracked MRs are invisible to the rest of the org and break the audit trail. During a fast iteration session (CLL-160 through CLL-171+), I stopped creating issues after CLL-169 and shipped ~15 MRs without Linear tracking.

**How to apply:** Before writing any code, create the Linear issue first. Use the branch name from Linear. Reference the issue in the commit and MR description. No exceptions, even for "quick fixes."
