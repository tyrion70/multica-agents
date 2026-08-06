---
name: Composite adapter annotation system
description: How composite adapters are detected and handled in the service registry — annotations on k8s Services, bridge aliases, and the CVI bridge-alias special case
type: project
---

Composite adapters (single k8s service handling multiple data sources) are marked with:
- `app.chainlayer.io/composite-adapter: "true"` annotation on the Service
- Optional `app.chainlayer.io/bridge-alias: "cvi"` for shortened bridge name prefixes
- Optional `app.chainlayer.io/bridge-aliases: "icap=?streamName=ic"` for virtual bridges pointing to another adapter's URL with custom suffix

**Composite adapters:** vesper, xsushi-price, set-token-index, defi-dozen, dxdao, linear-finance, savax-price, synth-index, apy-finance, crypto-volatility-index (alias: cvi)

**NOT composite (orchestrators):** implied-price, proof-of-reserves, ondo-calculated, tokenized-equity, market-status, multi-address-list, gm-token

**How to apply:** When adding new adapters, check if they use `*_ADAPTER_URL`/`*_DATA_PROVIDER_URL` env vars pointing to data sources (composite) vs other adapters (orchestrator). Only true composites get the annotation.
