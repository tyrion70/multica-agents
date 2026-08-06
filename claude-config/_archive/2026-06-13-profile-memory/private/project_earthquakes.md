---
name: project_earthquakes
description: "Tremor — worldwide earthquake-monitor web app (PostGIS+FastAPI+Leaflet) on the workstation, accessed over Tailscale"
metadata: 
  node_type: memory
  type: project
  originSessionId: 6f7e3d23-66bd-4564-b0a2-fb8855572bab
---

Personal project: a modern worldwide earthquake-monitoring site (better than earthquaketrack/
volcanodiscovery), with trend data + an "I'm safe" notification feature. Started 2026-06-08.

> **HOW-TO lives in the `tremor` skill** (claude-skills/tremor) — adding a provider, deploy/reconcile
> flow + footguns, proxy-port→country allocation, Cloudflare/backup/analytics ops, outage pitfalls.
> This file is durable LIVE STATE only.

## Where it runs
- **VM:** `tremor` = VMID 115 on proxmox4 (Ubuntu 24.04, 4 vCPU/8GB/50GB, onboot=1).
  LAN IP **192.168.17.88**, root SSH from workstation. **NO Tailscale (by design).**
- **Deploy target:** `/opt/tremor/app` = clone of **github.com/tyrion70/tremor** (PRIVATE; VM has
  read-only deploy key `~/.ssh/tremor_deploy`). Deploy = push to main → on VM `app/deploy.sh`.
- **Source / dev working tree:** `~/claude/projects/earthquakes/` (also a git repo → origin tremor).
  Old workstation stack is **stopped, not removed** (fallback).
- Per-country gluetun proxy fleet for geofenced sources lives on homelab VPN VM 102 (192.168.16.163),
  `/opt/vpn-proxy/` — see [[project_homelab_vpn_vm]] for the port→country map.

## Key URLs
- Public: **https://tremorsonline.com** (+www) — open-access, no auth (intentional), via Cloudflare Tunnel.
- Analytics: **analytics.tremorsonline.com** (self-hosted Umami).
- Internal: **http://192.168.17.88:8080** (LAN, not Tailscale).
- Cloudflare: PERSONAL account `11c195ddb38b83a917bc07f8445c4b73`, zone `3c89c4aafb9143e796ef55e13e0f17d0`,
  tunnel `tremor` id `a6c205c8-769f-4f7f-aeff-9d1f2228ca06`. CF API token in `~/claude/projects/earthquakes/.env`.

## Current status (2026-06-11)
- **Stack:** docker compose project `tremor` — PostGIS + FastAPI app + sync worker + cloudflared + umami.
- **Providers live: 49** (~385k raw rows, ~346k unique after dedup). Mix of FDSN-text datacenters +
  custom national-network adapters. Backlog of per-country source tickets in Linear.
- **"I'm safe" feature:** passkey-only (WebAuthn), shareable status link/QR + optional location sharing
  + safety circles; PWA + web push live. Core passkey flow confirmed working.
- **Backups:** nightly cron 03:47 UTC on VM 115 → encrypted pg_dump to MinIO on Hetzner. Restore tested.

## Tracking
- **PRIVATE project → Tyrion Linear (team TYR), project "Tremor"**:
  https://linear.app/tyrion70/project/tremor-7d6d8c7b24ad (via API key — see [[reference_linear_tyrion]]).
  Issue-first + link commits/PRs. Durable provider backlog = per-country "Local source — <Country>" tickets.
- Runbook/checklists in-repo: `app/DEPLOY.md`, `app/PROVIDER-WORKLIST.md`; research docs `PROVIDERS.md`,
  `DATA-SOURCES.md`, `STORAGE.md`. See also [[reference_k8s_deploy_guide]] if it ever moves to the cluster.
