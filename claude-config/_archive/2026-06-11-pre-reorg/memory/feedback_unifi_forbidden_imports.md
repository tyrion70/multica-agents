---
name: UniFi resources that must NEVER be imported into Terraform
description: Hard list of UniFi objects that are system-managed and break when terraform tries to manage them
type: feedback
originSessionId: 31e6e6f5-20fa-4d51-a874-93b98763a5d4
---
Some UniFi objects are system-managed (`attr_no_edit=true` or `attr_no_delete=true` in the API response). The `ubiquiti-community/unifi` provider tries to round-trip them with field changes UniFi rejects — and **rejected PUTs still partially apply** (see [feedback_unifi_partial_writes.md](feedback_unifi_partial_writes.md)). Importing them caused a real outage on 2026-04-29.

**Forbidden — never import or write:**

- `unifi_wan.*` (every WAN profile — system-managed; PUT triggers `WanConfigurationForNetworkGroupAlreadyExists`)
- `unifi_network` where `purpose != corporate` — i.e. `wan`, `vlan-only`, `site-vpn`, `remote-user-vpn`, `guest` — these reject PUTs as `NotImplemented` or partially apply destructively
- `unifi_radius_profile.default` — system-managed; PUT returns `CannotModifyDefaultRadiusProfile`
- `unifi_device.<gateway>` (the UDM/UXG itself) — the gateway is the management plane; never write to it via the API in production
- Any other object the API returns with `attr_no_edit=true` or `attr_no_delete=true`

**Why:** Even read-only-shaped imports go through PUT round-trips during `terraform apply`, and partial-commit behavior means rejected PUTs leave the live config in a half-changed state. There is no safe way to import these.

**How to apply:**
- In `infra/terraform/unifi/imports.tf`: keep these listed as **forbidden** with a comment pointing to `docs/postmortem-2026-04-29-wan-outage.md`. Don't move them to "deferred"; deferred drifts back to "let's try it".
- For configuration changes to these resources: do them in the UniFi UI only.
- If a later UniFi or provider release claims to fix this, **do not test on the production UniFi site at home** — set up a UniFi controller in a VM and validate there first.
