---
name: tremor
description: Operate "Tremor", the worldwide earthquake-monitor web app (PostGIS + FastAPI + Leaflet, ~49 seismic providers) running on homelab VM 115. Use whenever adding/debugging a seismic data provider, deploying or reconciling the stack, allocating a per-country gluetun proxy port, or touching the Cloudflare tunnel/backup/analytics plumbing. Live oracle for nothing — but a public site, so deploys are zero-downtime and reconcile has real footguns.
---

# Tremor operations

Tremor fans out to dozens of seismic data sources (FDSN datacenters + custom
national-network adapters), dedups overlapping events, and serves a dark Leaflet
map at https://tremorsonline.com. The differentiator is small-quake completeness
from local national networks that the global catalogs (USGS/EMSC/GFZ) miss.

This skill is the **repeatable how-to**. Live state (VM IP, current provider
count, status) lives in the `project_earthquakes` memory and in **Multica**
(project "Tremor") — Tremor is a private project, so it's tracked in Multica,
not Linear (`multica-private` skill). Issue-first + link commits/PRs.

## Architecture in one breath

- Stack = `docker compose` project `tremor` on the VM: **PostGIS** + **FastAPI app**
  (gunicorn master + 1 uvicorn worker) + a sync **worker** (polls every 60s,
  auto-reconciles) + **cloudflared** (tunnel out) + **umami** (analytics, separate
  DB on the same Postgres).
- Code at `/opt/tremor/app` = clone of `github.com/tyrion70/tremor` (PRIVATE,
  read-only deploy key `~/.ssh/tremor_deploy` on the VM).
- `web/` and `quakes/` are **directory** bind-mounts → UI/code edits go live on
  restart, no rebuild. `providers.yaml` is a **single-file** mount → has the
  stale-inode trap (see below).
- Source working tree (fallback / dev) at `~/claude/projects/earthquakes/`.
  Research docs: `PROVIDERS.md`, `DATA-SOURCES.md`, `STORAGE.md`. The durable
  provider checklist is `app/PROVIDER-WORKLIST.md`; full deploy/restore runbook
  is `app/DEPLOY.md`.

## Adding a new seismic data provider

The provider hunt is tracked as per-country "Local source — <Country>" issues in
the Multica "Tremor" project. Work top-down through `app/PROVIDER-WORKLIST.md`, marking each
✅/❌. The procedure is **probe → add → backfill → let-the-worker-reconcile**.

### 1. Probe the source from where the VM lives (NL)

- **FDSN datacenters** are the easy tier. Only ~14–17 of 31 FDSN datacenters
  serve *events*, and there is no event federator — you fan out and dedup
  yourself. Prefer the **text** format (`format=text`); geojson is often
  non-standard or HTML (INGV/GSI). `/count` is NOT universal (INGV redirects,
  some 404) → backfill is **count-free**: query a window with a limit, and if it
  comes back full, bisect the window.
- If FDSN works, it's pure config: add an entry to `providers.yaml` (kind defaults
  to `fdsn`). Auth tier and base URL matter — watch for sources whose real base
  differs from the obvious host (e.g. France's RéNaSS is `api.franceseisme.fr`,
  not `renass.unistra.fr` which 404s). Config-level `params` passthrough exists
  for FDSN providers, and `fmt: xml|quakeml` selects `_parse_quakeml`.
- **No usable FDSN** → write a custom adapter. Each is a `quakes/<name>.py` with a
  `normalize()` + a fetch, plus dispatch branches in `ingest.py`. Model it on an
  existing one (`quakes/sgc.py` is the canonical example). kind != fdsn.

### 2. Custom-adapter gotchas (learned the hard way)

- **Timezones lie.** Many national feeds emit local time without saying so.
  Verify each new source's timestamps against a known global event (USGS/EMSC for
  the same quake) before trusting them. Real cases: several Central-American nets
  are UTC-6, Panama is UTC-5, but inpres/igepn/ROB/Bulgaria/Armenia/Vietnam feeds
  turned out UTC despite local-looking pages.
- **Scrape defensively.** Sources have shipped: coords inside HTML comments (regex
  still matches), magnitude as `"M = 1.7"` (regex the number), `var lat/lng`
  preceding `bindPopup` in Leaflet JS, Joomla/Atom/RSS bulletins, 6MB folium dumps
  (marker-hash join), broken cert chains (unverified TLS fallback), and pages that
  intermittently 503.
- **Geofencing / WAF.** If a source is blocked from NL (403/empty), it goes to the
  per-country proxy fleet (next section) or is retried via the Hetzner egress.
  Some are genuinely SPA-blocked and stay deferred (e.g. Geoscience Australia).

### 3. Backfill, then DO NOTHING but watch

- Backfill via a one-shot container: `docker compose run … ` (a fresh container,
  so it always picks up the new code/config). This lands the rows.
- Then **let the worker's 60s auto-reconcile dedup them**. The worker already
  routes a big dirty set (>5000, e.g. a fresh backfill) to a full pass on its own.
  Poll `merged` until it goes >0 and stabilizes.
- **Do NOT launch a manual `quakes.cli reconcile`/`reconcile --all` while the
  worker is up.** See the reconcile footguns below — this is the #1 way to break
  prod.

## Deploy / reconcile flow

**Deploy:** push to `main` → on the VM run `/opt/tremor/app/deploy.sh`.

- Code deploys are **zero-downtime**: `deploy.sh` SIGHUPs the gunicorn master
  (socket stays open, the worker swaps from the bind-mounted `./quakes`). It only
  **recreates** the app container (~10s of 502) when the pulled diff touches
  `Dockerfile` / `requirements.txt` / `docker-compose.yml` / `providers.yaml`, or
  when run with `--full`.
- All services are `restart: unless-stopped` → the stack survives reboot.

### Branch preview — let Peter click a branch before release

Prod (`https://tremorsonline.com`, compose project `quakes`, port 8080) only ever
serves an **approved release tag**. To let Peter **click around a feature branch**
before it ships, stand that branch up as an **isolated preview** on the same VM,
on a non-prod LAN port — reusing the test-stack framework
(`docker-compose.test.yml` + `app/deploy-test.sh`), NOT `deploy.sh` (that pulls
`main` and mutates prod).

- `deploy-test.sh` takes `-p/--project NAME` and `--port N` **before** the command
  (env fallbacks `TEST_PROJECT`/`TEST_PORT`), passed through as
  `docker compose -p <name>`. Each project name is its own container + volume
  namespace, so multiple previews run side by side without clobbering each other
  or prod, and `down --wipe` only ever drops that one preview's DB volume.
- The script **refuses prod's identity** — project names `quakes`/`tremor` and
  port `8080` — so a preview can never recreate prod containers or drop a
  prod-namespaced volume. A port override alone is NOT enough: give each preview
  its own `-p` name (before PRI-100 the project was hardcoded to `quakes-test`, so
  two previews on different ports still shared containers/volume).
- Previews are **LAN-only by design**: no cloudflared, no umami, no tunnel — the
  public site only serves release tags. Hand Peter `http://192.168.17.88:<port>`
  (pick 8091+; prod is 8080, the standing test stack defaults to 8090).
- Previews are **disposable** — tear down when review is done (`down --wipe` +
  `rm -rf` the branch checkout). Full procedure (clone branch, port selection,
  reseed, parallel previews, teardown) is `app/TEST-ENV.md` → "Previewing a
  feature branch", with a short pointer in `app/DEPLOY.md`.

### Reconcile footguns — read before touching reconcile

These have each caused real outages. The worker auto-reconciles every 60s; that
is almost always all you need.

- **⚠️ Stale-inode trap (single-file mounts):** editing `providers.yaml` then
  `docker compose restart worker` does NOT take effect — the restart keeps the OLD
  inode (an atomic Edit creates a NEW inode). Backfills via `docker compose run`
  see the new file, but `/api/meta` and the live sync loop stay on the old list.
  **Fix:** `docker compose up -d --force-recreate app worker`. Directory mounts
  (`web/`, `quakes/`) are immune.
- **⚠️ Don't `deploy.sh` / `--force-recreate` while a reconcile is in flight.**
  `--force-recreate` restarts db/worker and kills the reconcile's DB connection
  mid-`_DEMOTE` (asyncpg `ConnectionDoesNotExistError`), leaving the table
  **all-primary** (every quake plots 2–4×) until the worker's next FULL pass
  self-heals.
- **⚠️ NEVER run a manual `quakes.cli reconcile` (incl. `--all`) while the worker
  is up — they DEADLOCK.** Both do `UPDATE raw_events SET is_primary…`; two
  concurrent full passes deadlock and PG kills one. If you genuinely need a manual
  full pass: `docker compose stop worker` → reconcile → start the worker.
- **Full-pass timing is normal-looking breakage:** a full pass shows `merged=0`
  for its whole RESET→DEMOTE window — expected mid-pass, not a fault. Full-pass
  time scales with row count (~6 min at ~390k rows, ~11–12 min at ~457k).
- **Reconcile model:** cross-source dedup only (±20s / ≤100km, different
  providers), primary = lowest `authority` (local nets=1 beat usgs=2), tie-break
  newest `updated_at`; stored on `raw_events` as `is_primary`/`cluster_id`/
  `authority`, API serves `WHERE is_primary`. Dedup correctly demotes global
  aggregators under local auth1 nets where they overlap. Routing: ≤5000 dirty rows
  → scoped incremental (~1–2s); >5000 → full bulk pass. An incremental with an
  **unset cursor degenerates to an all-pairs self-join** (runs forever,
  ACCESS-EXCLUSIVE-blocks app startup) — guarded now (no cursor ⇒ run full).
- **App must NOT run schema DDL on startup** (`init_schema` is out of the
  api.py lifespan) — ACCESS EXCLUSIVE locks would block startup behind a running
  reconcile. The worker / `cli initdb` own the schema.

### Load-testing the origin

CF has a rate-limit rule that returns **429 at ~10 req/s/IP** — load-test the
origin **directly** (`192.168.17.88:8080` from LAN), not through Cloudflare.

## Per-country proxy fleet (gluetun)

When a source is geofenced or WAF-blocks NL, route Tremor's fetch for that source
through a per-country HTTP proxy. The fleet lives on the **homelab VPN VM 102
`vpn`** (proxmox4), in `/opt/vpn-proxy/`. Tremor uses
`http://192.168.16.163:<port>` as the per-source HTTP proxy.

- **`docker-compose.yml` is GENERATED** — edit the `MAP` in `gen-compose.sh` and
  re-run; never hand-edit the yaml. WG key is reused from `wg0.conf` into
  `/opt/vpn-proxy/.env` (chmod 600). Reference: `~/claude/projects/vpn-proxy/README.md`.

### Allocating a port → country

Ports run from **8881 upward**, one container per country, each bound LAN-only to
`192.168.16.163`. To add one: pick the next free port, add a `MAP` entry
(port → NordVPN country code), re-run `gen-compose.sh`, bring it up, then point
the Tremor provider at `http://192.168.16.163:<port>`. File the Multica issue
link alongside (the fleet tracks which port serves which provider).

### Proxy fleet gotchas

- **Per-country tunnel, not double-tunneled:** an ip rule `from 172.30.0.0/16
  lookup main pref 30000` (systemd `vpnproxy-egress-bypass.service`) lets each
  gluetun build its own tunnel straight out `ens19`, decoupled from the host's NL
  client-gateway. `ManageForeignRoutingPolicyRules=no` keeps netplan/networkd from
  flushing those rules.
- **DoT (853) is blocked at some exits** (HK, Pakistan). Add the country to the
  `DOT_OFF` list in `gen-compose.sh` (sets plain DNS via 1.1.1.1:53). Symptom:
  container unhealthy, `tun0` has traffic but healthcheck logs
  `lookup github.com: i/o timeout`.
- **Some NordVPN datacenters won't handshake from the home WAN:** HK/JP/TW/SG stay
  `tun0 RX = 0` across every server and both egress paths. Workaround: use a
  neighboring exit that does connect (e.g. China sources go through the **Myanmar**
  exit — CEIC `ceic.ac.cn` isn't China-geofenced anyway, returns 200 from any
  non-EU exit).
- **NordVPN simultaneous-connection cap = 10/account; the fleet runs ~12** (11
  proxies + host wg0). Works today because manual WG configs aren't strictly torn
  down, but it's over quota and can drop handshakes intermittently. If reliability
  matters, trim the fleet or move proxies to a second account.
- **Diagnostic that lies:** a standalone `wgtest` interface on the host (same
  account key) gives unreliable rx skewed by the concurrent sessions. Trust the
  actual container `tun0` rx_bytes.

## Cloudflare, backups, analytics — operational notes

- **Public access is a Cloudflare Tunnel** (`cloudflared` service dials out →
  `app:8080`; no inbound ports, home IP hidden). Domain on Peter's **PERSONAL**
  Cloudflare account (not the chainlayer one — the GCP
  `proxmox-automation-cloudflare-api-token` can't see this domain). Tunnel ingress
  is remotely-managed: edit via `PUT /accounts/{acct}/cfd_tunnel/{id}/configurations`.
  The CF API token is the personal Tunnel+DNS+Zone token; it lives in
  `~/claude/projects/earthquakes/.env` (`CLOUDFLARE_TOKEN`, gitignored).
- **CF caching rules:** origin sends `no-cache` on HTML/app.js/style.css (instant
  deploys) and `public,max-age=86400` on immutable assets. CF caches images by
  default but **NOT `.json` by extension** — `.json` paths need an explicit Cache
  Rule (rulesets API, `http_request_cache_settings` entrypoint). While iterating
  on JS/CSS, use CF **Development Mode** (CF force-caches `.js`/`.css` 4h
  otherwise); do NOT version URLs (that disables edge caching). SSL mode = strict.
- **Backups (nightly cron 03:47 UTC on the VM):** `app/backup.sh` does
  `pg_dump` of quakes+umami → client-side AES-256 → MinIO on the Hetzner box
  (`https://10.99.0.51:9000`, reached directly over the UniFi route to
  10.99.0.0/24 — no VPN/SSH on the public VM). Upload key is **PutObject-only**;
  bucket has versioning + 35d lifecycle. Secrets on the VM under
  `/root/tremor-backup/`, **escrow copies** on the workstation under
  `~/.claude/secrets/`. Restore runbook in `app/DEPLOY.md`, tested end-to-end.
  Hetzner CT's `mc` is Midnight Commander, not MinIO client — use
  `docker run minio/mc --insecure` from the workstation.
- **Analytics:** self-hosted Umami (`umami` service, separate `umami` DB on the
  same Postgres) at analytics.tremorsonline.com. Cookieless/no-PII → no consent
  banner. Umami password-change API is `POST /api/users/{id} {password}` (NOT
  `/password` — that 404s).

## Pitfalls that have caused outages

- **NEVER put Tailscale on the public VM.** It's off the tailnet **by design** so
  the public service can't reach the internal/prod tailnet. Internal access is the
  LAN IP `http://192.168.17.88:8080`, not Tailscale.
- **PVE backup froze the VM's disk (2026-06-10):** an hourly vzdump with
  `fleecing 0` to a slow PBS target made guest writes wait on copy-before-write →
  site-wide 524s and D-state postgres. Don't run fleeceless vzdump against a slow
  target on VM 115.
- **`.gitignore` must NOT match `*.sql`** — it would drop `quakes/schema.sql` that
  `initdb` needs. Ignore `*.sql.gz` instead.
- **WebAuthn RP_ID = tremorsonline.com** → the "I'm safe" passkey feature works
  ONLY on the https domain, never on the LAN IP.
- **Never paste tokens into tracked files.** CF token, tunnel run-token, push
  VAPID keys, umami/backup secrets are all gitignored on the VM with escrow copies
  under `~/.claude/secrets/`.
