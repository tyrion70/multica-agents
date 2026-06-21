---
name: cloudflare
description: Operate ChainLayer's Cloudflare account — DNS records, load balancers, origin pools, Access / Zero Trust applications, service tokens, and Zero Trust policies across the chainlayer.network / chainlayer.cloud / cinternal.com zones. Use for DNS changes, LB pool management, Access app creation/policy edits, and service-token lifecycle. All changes are API/dashboard (no IaC for these zones). NOT for Cloudflare Workers/Pages/dev-platform. Credentials fetched at runtime from vault company via the bitwarden skill.
---

# Cloudflare — ChainLayer infra

## Account inventory

| Field | Value |
|---|---|
| **Account owner** | Chris (`C@ynodes.com`) |
| **Account ID** | `76b067be0ed98530dddf47cdccebf25b` |
| **API base** | `https://api.cloudflare.com/client/v4/` |

The ChainLayer zones all live on this single account. Peter's personal account
(`tremorsonline.com`) is a **different account** — never use its token here.

## Zone inventory

| Zone | Zone ID | Access-walled? | Purpose |
|---|---|---|---|
| `chainlayer.network` | `462c20b57d4eb6be05b58c3f0b656e9e` | No | Public RPC DNS + LB (`broadcast-*.`, `haproxy-nl/no` pools) |
| `chainlayer.cloud` | confirm in dashboard | No (public) | k8s IC hostnames (`*.nl-oven.chainlayer.cloud`); external-dns managed |
| `cinternal.com` | confirm in dashboard | **Yes — CF Access** | Internal services (`alertmanager.cinternal.com`, etc.) |
| `.chosts.io` | out of scope | No | Managed by `infrastructure/dns-chosts` (netbox-driven IaC sync) — **do not touch via API** |

> **Open — confirm in dashboard:** zone IDs for `chainlayer.cloud` and
> `cinternal.com`, and the full hostname list for each. The `chainlayer.network`
> zone ID is confirmed (CHA-50, 2026-06-19). Add confirmed IDs here when
> obtained.

### Resolved: Is DNS/LB managed in IaC?

**No — it is API/dashboard-only** for `chainlayer.network`, `chainlayer.cloud`,
and `cinternal.com`. Confirmed via group-wide GitLab code search (CHA-50,
2026-06-19): zero matches for CF resource types, LB IDs, or zone-specific
hostnames across all `chainlayer` GitLab repos. The only CF IaC is
`infrastructure/dns-chosts`, a **netbox-driven sync for `.chosts.io` only** —
it does not touch the zones above.

**Consequence:** when executing a write (DNS add/change/delete, LB mutation,
Access policy change), there is no MR to open — it is a direct Cloudflare API
call or dashboard action, not a `git-mr`. Still requires a Linear issue
(`linear-company` skill) created first, and the §4 permission tier governs
whether it needs ask-first or can proceed on a change-tier issue.

## Shared LB origin pools

These pools are **shared** across multiple LBs; never delete them when removing
an LB that references them — only detach.

| Pool name | Pool ID | Origins | Notes |
|---|---|---|---|
| `haproxy-nl` | `a504898ffc120c7b582d38d4b5828212` | `89.149.218.8`, `89.149.218.9` | nl2 HAProxy main nodes |
| `haproxy-no` | `c56a7f0f457cc336087eb9b42ffd550b` | `86.111.48.8`, `86.111.48.9` | no1 HAProxy main nodes |

Both pools are shared general HAProxy main-node pools used by multiple Cloudflare
LBs (including the k8s IC external LB and any future LBs). Deleting an LB
detaches it from these pools; the pools themselves stay.

## Credentials model

### Zero standing secrets — runtime fetch only

The CF API token is **never baked into `custom_env`**. Fetch at runtime:

```bash
# Via bitwarden skill, company folder:
CF_TOKEN=$(bw get password "Cloudflare API token - chainlayer write" --session "$BW_SESSION")
export CLOUDFLARE_API_TOKEN="$CF_TOKEN"
```

Then use with `curl -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN"` or
`flarectl` / `cf-terraforming` if installed.

### Vault state (as of 2026-06-19)

| Vault item | Scopes | Usable for writes? |
|---|---|---|
| `readonly chainlayer credentials` → `CLOUDFLARE_CHRIS_TOKEN` | All read scopes | **No** |
| `readonly chainlayer credentials` → `CLOUDFLARE_PETER_TOKEN` | All read scopes | **No** |
| `CLOUDFLARE_TOKEN_PETER` | tremorsonline.com personal | **No** (wrong account) |
| Write-scoped token | **Does not exist yet** | — |

> **Human gate for writes:** Minting a write-capable scoped token (or any token
> beyond read-only) requires dashboard admin on the `C@ynodes.com` account —
> that is Chris or Peter. If a write operation is needed and the vault has only
> read-only tokens, **stop and surface this as a blocker** (`blocked_reason` on
> the issue, @mention Peter). Do NOT widen an existing token's scope yourself.
> See [CHA-50](mention://issue/9f572d48-bbb0-4d3e-88a9-a494875792ae) for the
> blocked precedent.

### Least-privilege token scopes

When a write token is eventually minted (or when scoping a new one), use these
permission groups — no broader:

| Permission group | Level |
|---|---|
| Zone · Zone · Read | Read |
| Account · Account Settings · Read | Read |
| Zone · DNS · Edit | Edit |
| Account · Load Balancing: Monitors and Pools · Edit | Edit |
| Zone · Load Balancers · Edit | Edit |
| Account · Access: Apps and Policies · Edit | Edit |
| Account · Access: Service Tokens · Edit | Edit |

Scope the token to the ChainLayer account + only ChainLayer zones (never global).
Store the new token in the vault `company` folder via the `bitwarden` skill;
never hardcode, paste into issues/comments, or store in `custom_env`.

## Permission tiers

### ✅ Read-only — proceed without asking

- GET zone details, DNS records, LB configuration, health monitor results
- List Access applications, policies, service tokens, tunnel configurations
- Query analytics, firewall events, audit logs
- `GET /zones/:id/dns_records`, `GET /accounts/:id/load_balancers/pools`
- `/user/tokens/verify` to confirm a token is valid

### 🔶 Change tier — Linear issue first, then proceed

- Add / edit DNS records (A, CNAME, TXT, etc.)
- Add / edit LB health monitors
- Create new Access applications or service tokens for **new** services (not
  touching active ones)
- Adjusting pool health thresholds (not enabling/disabling pools)

### 🛑 Ask a human first — stop and confirm before any API call

- Deleting or cutting DNS records / LBs that front **production traffic**
  (user-visible cutover — see CHA-50 for the gate precedent)
- Any change to Access policies that could lock humans out of internal services
- Creating, rotating, or deleting a CF Access service token that is
  **already in use** by a running service
- Enabling or disabling an entire LB or origin pool (pool drain affects all
  consumers)
- Any change to `cinternal.com` auth walls that could cut off monitoring or
  alerting pipelines
- Widening an Access policy scope (e.g. allowing public access to a protected
  app)

### ❌ Never

- Touch non-ChainLayer accounts or zones (no personal, no `tremorsonline.com`)
- Widen any Access policy to public
- Read, copy, store, or reference the global Cloudflare API key (vs scoped tokens)
- Paste any API token or secret into an issue, comment, or commit

## CF Access / Zero Trust — service-token pattern

CF Access guards internal services on `cinternal.com` (and potentially
`chainlayer.cloud`). Non-browser callers authenticate with **service tokens**
(client ID + secret pair), not mTLS certificates.

### Creating a service token

```bash
# POST /accounts/:account_id/access/service_tokens
curl -X POST "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/access/service_tokens" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "<service-name> consumer token"}'
# Response contains: client_id, client_secret (shown ONCE — store immediately)
```

Store `client_id` and `client_secret` in vault `company` folder via
`bitwarden` skill before the API call returns from context — the `client_secret`
is shown only once.

### Wiring the token into an Access policy

The Access application for `alertmanager.cinternal.com` (and similar) uses an
**Allow** policy with the service-token principal. After creating a token, add
it to the relevant application's policy:

```bash
# GET the app ID first
curl "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/access/apps" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN"
# Then PUT/PATCH the policy to include the new service token client_id
```

### How a caller uses the token

```bash
curl -H "CF-Access-Client-Id: $CLIENT_ID" \
     -H "CF-Access-Client-Secret: $CLIENT_SECRET" \
     https://alertmanager.cinternal.com/api/v2/alerts
```

### Dependency note — CHA-56 / alertmanager token

**Do NOT mint a new CF Access service token for `alertmanager.cinternal.com`
from this skill.** [CHA-56](mention://issue/1405f845-b1d5-4be4-9c28-a9ae7b2ca2db)
(Create & wire up a monitoring agent) owns creating and storing that specific
consumer token. This skill / agent owns CF Access **administration going
forward** (future tokens, policy changes, rotation) — not the first-time setup
for the alertmanager token that CHA-56 is already handling.

If a future run encounters an existing `alertmanager.cinternal.com` service
token in the vault, treat it as already provisioned by CHA-56 and do not
duplicate it.

## Tooling

No `flarectl` or `cf-terraforming` is guaranteed on the runtime. Use `curl`
with `Authorization: Bearer $CLOUDFLARE_API_TOKEN` as the primary interface:

```bash
# Verify token (account-owned tokens use the account endpoint, not /user/tokens/verify)
curl -s "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/tokens/verify" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | python3 -m json.tool

# List DNS records
curl -s "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | python3 -m json.tool

# List LBs in a zone
curl -s "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/load_balancers" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | python3 -m json.tool

# List origin pools (account-level)
curl -s "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/load_balancers/pools" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | python3 -m json.tool

# List Access apps (account-level)
curl -s "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/access/apps" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | python3 -m json.tool
```

If `jq` is installed, prefer it over `python3 -m json.tool` for filtering.

## Relationship to HAProxy pools

The `haproxy-nl` and `haproxy-no` CF LB pools point at the ChainLayer HAProxy
bare-metal nodes (`89.149.218.8/9`, `86.111.48.8/9`). LB health monitors
check these origins; the `haproxy` skill owns the backend-level configuration
(which chains are served). Changes to DNS/LB that affect RPC traffic should
be coordinated with `haproxy` skill ops.
