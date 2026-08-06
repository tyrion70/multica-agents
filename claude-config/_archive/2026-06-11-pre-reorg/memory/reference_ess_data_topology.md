---
name: ESS data topology
description: Where ess data lives — hosts, ports, retention. Used by ess-ai-planner adapters.
type: reference
originSessionId: fa334a32-d673-46bc-b583-c3fb19af4168
---
**Two hosts, easy to confuse:**

| Host | IP | What's there |
|---|---|---|
| `dev.252h.org` | 192.168.16.72 | ess-dashboard (docker), influxd LOCAL (8086), mqtt-influx bridge — but NO Prometheus, NO Grafana on this box. Live ess Prometheus *exporter* on :9100 (ports 3000+9100 published from container). |
| `grafana.252h.org` | 192.168.17.28 | **Prometheus (9090)**, **Grafana (3000)**, and the **InfluxDB v2 (8086) the ess dashboard actually queries**. Prometheus retention `10y`, data starts 2026-04-04. |

**ess InfluxDB connection** (from `/root/ess/config/config.json` on `dev`):
- URL: `http://grafana.252h.org:8086`
- org=`prod`, bucket=`mqtt`
- (the influxd on dev itself is unrelated — different InfluxDB instance, not what ess writes to)

**Price cache** lives at `dev:/root/ess/config/cache/prices/YYYY-MM-DD.json` — 2000+ daily files going back to 2021. Both root-only.

**Why:** Trying to backtest the ess scheduler from a dev machine other than `dev` itself.

**How to apply:**
- Don't trust "the grafana box" naming — confirm by hostname/DNS, not by which IP someone names. The user once said 192.168.16.72 was the grafana host; it isn't.
- For ess-ai-planner adapters: point InfluxDB and Prometheus at `grafana.252h.org`. Read prices via SSH from `dev:/root/ess/config/cache/prices/` (rsync recent days locally for offline use).
- Token: read from `dev:/root/ess/config/config.json` via `ssh root@dev` (you have key access).
