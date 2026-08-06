---
name: feedback-linear-assignment
description: "Every Linear issue Claude creates must be assigned to the user, never left unassigned."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f6667cd3-59c9-42fa-b4ab-d3851e3dc376
---

When creating a Linear issue (via `mcp__claude_ai_Linear__save_issue` or any equivalent), always set `assignee` to the user (use `"me"` or "Peter"). Never leave issues unassigned.

**Why:** Unassigned issues fall out of the user's "my issues" view and get forgotten. The user noticed this after several issues (OPS-2339, OPS-2345, OPS-2366, OPS-2420) were created unassigned and asked it be permanent. Codified in [[../../../rules/common/linear.md]] under "## Assignment".

**How to apply:** Add `assignee: "me"` to every `save_issue` call when creating a new issue. Same applies for follow-up issues created during other work. If you already created an unassigned issue earlier in the session, fix it with a follow-up `save_issue` call passing the existing `id`.
