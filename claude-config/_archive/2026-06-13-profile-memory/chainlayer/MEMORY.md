# ChainLayer memory index

One line per memory. Behavioral rules and domain how-to live in `CLAUDE.md`
and the skills (`tyrion70/claude-skills`) respectively — this store is for
durable, recall-on-relevance facts about live **company** projects and resources.

## Projects (live)
- [chainlink-tools platform](project_chainlink_platform.md) — three-app chainlink-tools build (service-registry, delete-jobs, jira-sync) replacing static sites.json
- [Postgres migration](project_postgres_migration.md) — migrate 82 Chainlink PG DBs from VMs to the Zalando operator in k8s
- [Proxmox migration](project_proxmox_migration.md) — Prox7→9 VM migration status/decisions (the procedure → `company-proxmox` skill)
- [Optimism migration](project_optimism_migration.md) — OP mainnet → k8s op-reth; archive deferred (OP reth snapshot broken)

## Reference
- [Filecoin Lotus node](reference_filecoin_lotus_node.md) — Filecoin Lotus voter node on k8s + fork-check after network upgrades
- [QuickNode URL structure](reference_quiknode_url_structure.md) — RPC URL structure + which GCP project/ESO store holds the token
