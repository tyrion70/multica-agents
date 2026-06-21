---
name: private-knowledge
description: Durable cross-cutting knowledge about Peter's private/personal projects — Tremor (earthquakes), the ESS energy projects, the homelab VPN/proxy fleet, Minecraft AMP, Weekend Escape Radar — plus personal-device access preferences. Read this for background/state and key decisions when working any private project; it points you at the domain skill (tremor, homelab, …) for HOW-TO. Keep it updated (PR) when a durable fact changes.
---

# Private / personal knowledge

Background facts, decisions, and gotchas about Peter's personal projects — the
stuff worth carrying between issues. **HOW-TO lives in the domain skills**
(`tremor`, `homelab`, `homeassistant`, …); this skill is durable *knowledge*, not a
runbook, and not volatile status (don't pin "phase N next as of <date>" — that
rots; project STATUS files in-tree own that). Update via a PR against
`tyrion70/claude-skills` and tell the user when a durable fact changes.

## Tremor — worldwide earthquake monitor
Public site **https://tremorsonline.com** (open access by design, via Cloudflare
Tunnel on Peter's **personal** CF account). Runs as a docker-compose stack
(PostGIS + FastAPI + sync worker + cloudflared + Umami) on **VM 115 `tremor`** on
proxmox4 (**192.168.17.88**, root SSH from workstation, **no Tailscale by design**).
Deploy target `/opt/tremor/app` = clone of **github.com/tyrion70/tremor** (private;
VM has read-only deploy key). Geofenced sources use the per-country gluetun proxy
fleet on VPN VM 102 (see below). Tracked in **Tyrion Linear (team TYR), project
"Tremor"** (private project still uses Tyrion Linear, not Multica — confirm before
assuming). **HOW-TO (providers, deploy/reconcile, proxy-port allocation) → `tremor`
skill; QA → `tremor-testing`.**

## ESS (home energy storage) — three related efforts
- **`tyrion70/ess`** — the live ESS system. Normal workflow applies; treat as
  **read-only** from the planner project.
- **`tyrion70/ess-ai-planner`** (private, **no Linear** — just commit/push) —
  replaces the heuristic ESS scheduler with a forecast layer + MILP optimizer,
  validated by a backtest harness. Plan: `projects/ess-ai-planner/PLAN.md`.
- **saas-pi-appliance** (in `tyrion70/ess`) — resume guide is in-tree at
  `.planning/projects/saas-pi-appliance/STATUS.md`; **read that first**. Its
  load-bearing rule is **local-first with public-data exception**: cloud holds only
  identity/billing + public-data history (prices/solar/weather) + aggregates +
  heartbeat; all customer-specific data (energy series, overrides, creds) stays on
  the Pi. When designing any cloud table/endpoint, classify it as public /
  identity-billing / aggregate — anything else must live on the Pi.
- **ESS data topology (easy to confuse):** `dev.252h.org` (192.168.16.72) runs the
  ess-dashboard + a *local* influxd + the exporter; **`grafana.252h.org`
  (192.168.17.28)** runs Prometheus (9090), Grafana (3000), and **the InfluxDB v2
  (8086) the ess dashboard actually queries** (org `prod`, bucket `mqtt`). Point
  planner adapters at `grafana.252h.org`; confirm hosts by DNS, not by which IP
  someone names. Price cache: `dev:/root/ess/config/cache/prices/YYYY-MM-DD.json`.

## Homelab VPN VM 102 + per-country proxy fleet
VM 102 `vpn` on proxmox4 (192.168.16.163) = NordVPN WireGuard gateway/DNS for VPN
clients, plus a docker/gluetun **per-country HTTP proxy fleet** in `/opt/vpn-proxy/`
(LAN-only, one container per country, `http://192.168.16.163:<port>`) feeding
Tremor's geofenced sources. **`docker-compose.yml` is GENERATED** — edit
`gen-compose.sh` and re-run, never hand-edit. Hard-won gotchas:
- eth0 must stay **static** (dhcp4 blackholes egress).
- `netplan apply` flushes wg-quick policy-routing rules → restart `wg-quick@wg0`
  after; the fleet permanently guards this via `ManageForeignRoutingPolicyRules=no`.
- Proxmox `localtime: 1` caused boot clock skew that poisoned WireGuard anti-replay
  (set `--localtime 0`); recover by switching NordVPN endpoint (NL servers share a
  WG pubkey).
- NordVPN limit is 10 simultaneous/account; the fleet runs ~12 — over quota, can
  cause intermittent handshake drops. HK/JP/TW/SG datacenters won't handshake from
  the home WAN; cn uses the Myanmar exit.

## Minecraft AMP server — licence pinned to machine-id
`minecraft-1a-nl2v.chosts.io` (ssh port 2822) runs CubeCoders AMP; instances are
dockerized. **AMP Pro licences are bound to a hardware machine-id** — any
migration/clone/restore that changes the DMI UUID + `/etc/machine-id` breaks every
instance with `NoMatchingMachineId`, fixed per-instance via
`ampinstmgr reactivate <Instance>`. The Prox7→9 migration already triggered this.
If instances won't start after any host change, check
`/home/amp/.ampdata/instances/<Name>/AMP_Logs/` for `NoMatchingMachineId` first.

## Weekend Escape Radar
Personal MVP (`tyrion70/weekend-escape-radar`, private; **no Linear**, conventional
commits). Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic, Postgres 16, Redis 7;
local dev via `compose.yml`. A travel concierge that scans free weekends + Amadeus
fares and alerts on unusually good deals. Amadeus keys go in `.env` as
`AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET`.

## Personal-device access — prefer the Tailscale IP
When telling Peter how to reach a dev service from his phone/laptop, **lead with the
host's Tailscale IP (`100.x.x.x:<port>`), not the LAN IP** — he runs Tailscale on
all personal devices, and LAN IPs have failed (AP isolation / different SSID /
cellular). Bind the server to `0.0.0.0` so both work; this is just which URL to hand him.
