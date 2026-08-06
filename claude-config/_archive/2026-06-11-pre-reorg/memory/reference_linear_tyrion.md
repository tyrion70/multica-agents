---
name: reference_linear_tyrion
description: "Personal/private Linear workspace (Tyrion) — API key location, team/workspace IDs for non-company projects"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 6f7e3d23-66bd-4564-b0a2-fb8855572bab
---

Peter has a **personal Linear workspace** (separate from the company one) for PRIVATE projects.

- **Workspace:** Tyrion
- **Team:** `Tyrion`, key **`TYR`**, id `ecd62fd2-138b-4a46-958e-c870ae4b10fd`
- **API key:** stored gitignored at `~/.claude/secrets/linear-tyrion.env` (var `LINEAR_TYRION_API_KEY`,
  chmod 600 — NOT committed). Use via direct Linear GraphQL: `POST https://api.linear.app/graphql`
  with header `Authorization: <key>` (personal keys go raw in Authorization, no "Bearer").
- Viewer on this key = peter@chainlayer.io.

The **MCP Linear tools (`mcp__claude_ai_Linear__*`) target the COMPANY Linear** (DevOps team), NOT this
one. For private projects use the API key + direct GraphQL against the TYR team.

Routing rule: [[feedback_linear_private_vs_company]]. Tremor lives here (private) — see [[project_earthquakes]].
