---
name: feedback_linear_private_vs_company
description: "Route Linear work by project ownership: private→Tyrion/TYR (API key), company→Chainlayer DevOps (MCP). Always issue-first + link GitHub."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 6f7e3d23-66bd-4564-b0a2-fb8855572bab
---

Before any Linear work, determine whether the project is **PRIVATE (Peter's own)** or **Chainlayer
(company)**, and route accordingly:

- **Private** (e.g. Tremor, ess-ai-planner, weekend-escape-radar) → **Tyrion workspace, team `TYR`**,
  via the API key (see [[reference_linear_tyrion]]). Direct Linear GraphQL, not the MCP tools.
- **Company** → the **Chainlayer Linear, team `DevOps`** (the `mcp__claude_ai_Linear__*` MCP tools),
  per the global Linear rules.

**Why:** Peter keeps personal and company work in separate Linear instances; mixing them is wrong.

**How to apply:** For BOTH, same discipline as company work — **create the issue FIRST, then link the
GitHub/GitLab changes** (PR/commit) to it. Every change ties to an issue. Assign issues to Peter.
For private projects on GitHub, link the `github.com/tyrion70/<repo>` PR/commit URLs.
