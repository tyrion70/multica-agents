---
name: rag-consumer
description: How ChainLayer agents consume the RAG MCP server — the `rag_ask` tool for querying internal knowledge. Bound to agents that have the RAG MCP server in their mcp_config. NOT the rag-ops skill (that's for operating the RAG system itself).
---

# rag-consumer — querying the RAG from agent sessions

Every lifecycle agent (Refiner, Coder, QA, Deployer) across all squads, plus
Tech Leads, Communicators, Maintainers, and domain specialists, has the **RAG
MCP server** configured as an MCP tool. This means you can call `rag_ask`
directly in your session — the model decides when context is needed.

## The tool: `rag_ask`

```
rag_ask(query: str) -> str
```

Takes a natural-language question about ChainLayer infrastructure, operations,
runbooks, incidents, deployments, or codebase history. Returns a **grounded
answer with numbered source citations** (`[n]`), retrieved from the in-house
RAG corpus (270+ repos, nightly-refreshed).

Use it whenever you need internal context: before writing code, refining an
issue, verifying a fix, or deciding a deploy strategy.

## When to use it

- **Refiner:** ask "What does this system do?" before scoping a change
- **Coder:** ask "How is this configured in production?" before implementing
- **QA:** ask "What are the known failure modes?" before testing
- **Deployer:** ask "What is the rollout order?" before deploying
- **Anyone:** ask "Has this been done before?" before starting work

## What it returns

A typical response looks like:

```
The chainlink-tools platform consists of three apps under a monorepo... [1]

Sources:
  [1] chainlink-ops:README.md
  [2] linear-ops-cll:OPS-1179.md
```

If no relevant context is found, it returns `"No relevant context found."` —
do not treat this as a failure; it means your question falls outside the
ingested corpus.

## Architecture

| Property | Value |
|---|---|
| Transport | SSE (`GET /sse` + `POST /messages/`) |
| Endpoint | `http://100.69.200.97:8041/sse` |
| Auth | None (Tailscale-only binding — any tailnet host can query) |
| Host | `claude-readonly-01` |
| Retrieval | Hybrid (dense Qdrant ANN + lexical full-text, RRF fusion) |
| Model | Qwen3-30B-A3B-Instruct on `gx10-f018` |

## Binding to an agent

To give an agent the RAG MCP tool, add the following to its `mcp_config` in
`agent.json`:

```json
"rag": {
  "type": "sse",
  "url": "http://100.69.200.97:8041/sse"
}
```

Then run `scripts/sync.py` in the multica-agents repo to push the config to
Multica, or wait for the sync autopilot.

## See also

- `rag-ops` skill — operating the RAG system itself (ingestion, secret filter,
  eval, deploy)
- `claude-config/chainlayer/mcp/README.md` — general MCP connector management
