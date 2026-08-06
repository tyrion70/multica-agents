---
name: UniFi API PUTs are partial-commit
description: A 4xx response from UniFi's REST API does NOT mean "no fields were applied" — earlier fields in the body may have already been committed
type: feedback
originSessionId: 31e6e6f5-20fa-4d51-a874-93b98763a5d4
---
UniFi's controller validates fields in a `PUT /rest/<resource>/<id>` body **incrementally**, not transactionally. Fields are committed as they're processed; if a later validation step fails, the API returns an error but **does not roll back already-applied fields.**

**Why:** This caused a real incident on 2026-04-29 — a `PUT /rest/networkconf/<wan-id>` with `enabled: false` plus a conflicting `wan_networkgroup` field returned `WanConfigurationForNetworkGroupAlreadyExists`. I assumed "rejected → no effect". UniFi's audit log clearly logged a "Config Paused" event for the WAN, and 2 minutes later the UDM gateway failed over to the secondary WAN. Result: ~6 hour fiber outage, 5G data cap saturated, user unable to manage their network from off-site. Full timeline in `projects/proxmox/docs/postmortem-2026-04-29-wan-outage.md`.

**How to apply:** When operating against UniFi:
1. Treat any 4xx PUT response as "some fields *may* have been written"; verify with a follow-up GET.
2. For *any* fix, prefer **GET → modify exactly one field → PUT the same body** instead of re-deriving the body from terraform's schema. Terraform's schema drifts from live values; live values are authoritative.
3. The UniFi **audit log** (Settings → System → Audit) is the source of truth for what changed, not the API response code.
4. Never run `terraform apply` against a remote UniFi site without an out-of-band recovery path (someone physically there, or non-SDWAN WAN).
