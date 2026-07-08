---
name: skill-index
description: Index of every ChainLayer workspace skill — name, description, and which squad members are bound to it. Agents read this at start to know what domain skills exist, what each covers, and who to route domain work to. NOT a replacement for full skill content; just enough metadata for routing decisions.
---

# ChainLayer Skill Index

This index lists every skill registered in the ChainLayer workspace. Use it to
decide which squad member has the domain expertise for a given task.

Skill slugs in **bold** are the canonical name used in `agent.json` `skills[]`
and `Chainlayer/skills.json`.

---

## Company domain skills

| Skill | Description | MCP required | Bound squad members |
|---|---|---|---|---|
| **bitwarden** | Read/create/update secrets in Peter's self-hosted Bitwarden vault. | — | All Claude/ChatGPT/DeepSeek lifecycle agents + RAG Tech Lead + Maintainer. *Not bound:* Docs squad. |
| **chainlayer-docs** | Write, review, publish ChainLayer docs on docs.chainlayer.cloud (Retype). | — | Doc Writer, Doc Reviewer/Publisher (Docs squad). |
| **chainlayer-knowledge** | Cross-cutting infra facts: chainlink-tools, migrations, Filecoin voter, QuickNode RPCs. | — | Every agent in every squad. |
| **chainlink-ops** | Operate Chainlink node fleet: RPC config, adapter lifecycle, token refresh, topup. | — | *(No agent currently bound — gap)* |
| **company-k8s** | Operate k8s clusters (nl-oven, nl-spud, no-fryer): kubectl, manifests, ArgoCD, storage. | — | CF/HAProxy expert (all squads), Monitoring Operator (all squads), Issue Deployer (Claude/ChatGPT), Issue QA (all squads), Doc Reviewer/Publisher, Doc Writer. |
| **company-proxmox** | Operate Proxmox clusters (Prox7, Prox9): VM migrations, restores, TF IaC. | — | Issue Coder (all squads), Monitoring Operator (all squads). |
| **datafeeds-health-findings** | Run the chainlink-datafeeds-health report read-only and turn findings into deduped Multica issues (mapping, dedup keys, lifecycle, zero-mutation guardrail). | — | *(Bound in Stage 3 — the periodic datafeeds-health findings sweep agent)* |
| **deploy-app** | Deploy new apps to k8s GitOps pipeline: repo, CI, secrets, ArgoCD, Renovate. | — | Issue Deployer (Claude/ChatGPT). |
| **deploy-verify-rollback** | Generic deploy/verify/rollback for approved changes. | — | Issue Deployer (Claude/ChatGPT). |
| **fortigate** | Operate Fortigate firewalls (nl2, no1): address objects, allowlisting, API. | — | *(No agent currently bound — gap)* |
| **git-mr** | Ship company code to GitLab: Linear-first, MR template, SSH-signed commits. | — | Most lifecycle agents. *Not bound:* Lead (uses index), Communicator (Claude), Doc Writer. |
| **grafana-monitoring** | Build dashboards, run PromQL/LogQL, manage Alertmanager silences, operate monitoring stacks. | — | Monitoring Operator (all squads), Doc Reviewer/Publisher, Doc Writer. |
| **haproxy** | HAProxy RPC load balancing: bare-metal fleet + k8s Ingress Controller. | — | CF/HAProxy expert (all squads). |
| **incidentio** | incident.io: incident management, alerts, on-call schedules, follow-ups. | `mcpServers.incidentio` | Communicators (all squads), all lifecycle agents (all squads). |
| **linear-company** | ChainLayer Linear workspace (OPS/CLL/MAN): issue-first rule before any code change. | `mcpServers.linear` | All lifecycle agents except Maintainer. *Not bound:* Docs squad, Maintainer, Maintainer Private. |
| **multica-sync** | Bidirectional agent/skill sync between multica-agents repo and workspace. | — | Maintainer, Maintainer Private. |
| **new-repo-company** | Create new GitLab chainlayer/* repos via Terraform. | — | Issue Coder (Claude, DeepSeek). |
| **rag-consumer** | Query the RAG MCP server for grounded, cited answers about ChainLayer infra, operations, and codebase history. | `mcpServers.rag` | Every agent with the RAG MCP server bound (all Claude/ChatGPT/DeepSeek lifecycle agents, Tech Leads, Communicators, domain specialists, Maintainers, Docs squad, RAG Tech Lead). |
| **rag-ops** | Operate/extend the in-house RAG ops assistant: ingestion, secret filter, retrieval, eval, deploy. | `mcpServers.rag` | Issue Coder (DeepSeek), Issue Refiner (DeepSeek), Issue QA (Claude), Issue Deployer (Claude), RAG Tech Lead. |
| **slack** | Slack workspace: read channels, post messages, manage threads and reactions. | `mcpServers.slack` | Communicators (all squads), all lifecycle agents (all squads). |
| **ssh** | SSH keys, git auth (GitHub/GitLab), commit signing, tailnet host access. | — | Most lifecycle agents. *Not bound:* Docs squad, Communicator (ChatGPT). |
| **gdrive** | Google Drive / Docs / Sheets: read, write, create, format documents. | `mcpServers.gdrive` | Communicators (all squads), all lifecycle agents (all squads). |

## Private / homelab skills (not company domain)

These exist in the multica-agents repo but belong to the Private workspace.
ChainLayer agents should NOT route company work to them:

`cloudflare`, `eryndal-*`, `homelab`, `homeassistant`, `tremor-*`,
`cancer-*`, `private-knowledge`, `linear-private`, `new-repo-private`,
`multica-private`

---

## MCP dependency rule

When a skill requires an MCP server (e.g. `linear-company` → `mcpServers.linear`),
the agent **must** have that MCP server configured in its `mcp_config` at agent
create/update time. Skills document which MCP server they need in the **MCP required**
column above.

**Creating a new agent with an MCP-dependent skill:** include the matching
`mcpServers.<name>` in the agent's `--mcp-config` alongside the skill binding.
The actual API tokens are secret — store them in Bitwarden and use
`#Bitwarden item name#` placeholders in the repo's `agent.json` (the sync
autopilot resolves them at runtime via `bw unlock`).

## Maintenance

When adding, removing, or changing a skill in the multica-agents repo, update
this index at the same time so squad leads can route accurately.

**Update checklist:**
1. Add/remove the row in the table above.
2. If the skill needs an MCP server, add the `mcpServers.<name>` to the **MCP required** column.
3. Update `Chainlayer/skills.json` if the skill belongs to the Chainlayer workspace.
4. If binding an existing skill to a new agent, update the "Bound squad members" column.
