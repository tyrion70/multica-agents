---
name: Adapter traffic metrics for decommissioning
description: Which Prometheus metrics to use for verifying adapter usage before removal — http_request_duration_seconds_sum alone is insufficient, must cross-reference bg_execute_total for WebSocket traffic
type: project
---

Adapter traffic verification requires TWO metrics (CLL-211):
- `http_request_duration_seconds_sum{namespace="chainlink-ea"}` — HTTP request traffic
- `bg_execute_total{namespace="chainlink-ea"}` — WebSocket background execution

**Why:** Most Chainlink EA adapters receive traffic via WebSocket (bg_execute), not HTTP. Using HTTP metrics alone incorrectly flags ~29 active adapters as idle.

**How to apply:** When checking if an adapter is unused, query BOTH metrics over 24h. Only adapters with zero on both are safe to decommission. Even then, some (like PoR sub-adapters) may run infrequently.

Prometheus datasource: `deexgsum1bz7ka` (prometheus-nl-oven)

Truly idle adapters (2026-04-08): bitcoin-json-rpc, celsius-address-list, chain-reserve-wallet, etherchain, fluent-finance, paxos, renvm-address-set, stasis
