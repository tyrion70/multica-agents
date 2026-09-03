---
name: datafeeds-health-findings
description: Run the chainlink-datafeeds-health report READ-ONLY and turn its findings into deduplicated Multica issues. Use whenever an agent (e.g. a scheduled findings sweep) must check Chainlink data-feeds health and file/refresh findings as issues. Defines the exact finding→issue mapping, the dedup metadata keys (adapter_id / feed_contract), the new/known/recovered lifecycle (never auto-close), the N-consecutive-window debounce on new degraded-adapter issues (CHA-197), where issues are placed (the "Datafeeds health — open findings" project, not as sub-issues), and the hard zero-mutation guardrail. Pairs with bitwarden (token) and grafana-monitoring (Loki enrichment).
---

