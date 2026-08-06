---
name: project_earthquakes
description: "Tremor — worldwide earthquake-monitor web app (PostGIS+FastAPI+Leaflet) on the workstation, accessed over Tailscale"
metadata: 
  node_type: memory
  type: project
  originSessionId: 6f7e3d23-66bd-4564-b0a2-fb8855572bab
---

Personal project: a modern worldwide earthquake-monitoring site (better than earthquaketrack/
volcanodiscovery). Wants trend data + a later "I'm safe" notification feature. Started 2026-06-08.

**DEPLOYED (2026-06-09):** runs on a dedicated homelab VM **`tremor` = VMID 115 on proxmox4**
(Ubuntu 24.04, 4 vCPU/8GB/50GB, onboot=1, LAN IP **192.168.17.88**, root SSH from workstation).
Stack at **`/opt/tremor/app`** = clone of **`github.com/tyrion70/tremor`** (PRIVATE; VM has a
read-only deploy key `~/.ssh/tremor_deploy`). **Deploy flow:** push to main → on VM run
`/opt/tremor/app/deploy.sh`. Since TYR-170 (2026-06-10) code deploys are **ZERO-downtime**: the app
container runs a gunicorn master + 1 uvicorn worker; deploy.sh SIGHUPs the master (socket stays
open, worker swaps from the bind-mounted ./quakes) and only RECREATES the app container (~10s 502)
when the pulled diff touches Dockerfile/requirements.txt/docker-compose.yml/providers.yaml
(single-file mount stale-inode), or with `--full`. Verified: 601 reqs at 25/s during a deploy,
0 failures. CF rate-limit rule returns **429 at ~10 req/s/IP** — load-test the origin directly
(192.168.17.88:8080 from LAN), not through Cloudflare.
⚠️ **After deploying a new provider: run the backfill, then let the worker's 60s auto-reconcile
handle dedup — do NOT launch a manual `docker compose run … reconcile` and do NOT re-run deploy.sh
while a reconcile is in flight.** `deploy.sh`'s `--force-recreate` restarts the db/worker and kills
the reconcile's DB connection mid-`_DEMOTE` (asyncpg `ConnectionDoesNotExistError`), leaving the
table **all-primary** (every quake plots 2–4× from each source) until the worker's next FULL pass
self-heals — ~6 min on 391k rows (observed 2026-06-09: prod sat merged=0 for 6 min, recovered to
merged=39055). A full pass shows merged=0 for its whole RESET→DEMOTE window; that's expected mid-pass,
not breakage. **Full pass time scales with row count: ~11–12 min at 457k.**
⚠️ **NEVER run a manual `quakes.cli reconcile` (incl. `--all`) while the worker is up — they DEADLOCK.**
Both do `UPDATE raw_events SET is_primary…`; two concurrent full passes deadlock and one is killed by
PG's detector (observed 2026-06-09 on the TYR-14 deep backfill: manual `--all` vs the worker's
auto-pass → deadlock, 11 min wasted). The worker ALREADY auto-reconciles every 60s and routes a big
dirty set (>5000, e.g. a fresh backfill) to a full pass on its own. So after ANY backfill: just let the
worker do its one full pass and poll `merged` until >0 — do not launch your own. If you truly need a
manual full pass, stop the worker first (`docker compose stop worker`), reconcile, then start it.
All 4 services `restart: unless-stopped` → survives reboot (verified). **NO Tailscale on the VM by
design** (public service must not reach the internal/prod tailnet). Moved off claude-workstation-01
(which has kubectl+prod creds); the old workstation stack is **stopped, not removed** (fallback) —
its repo source still lives at `~/claude/projects/earthquakes/` (now also a git repo → origin tremor).
**BACKUPS (TYR-132, live 2026-06-10):** nightly cron 03:47 UTC on VM 115 (`/etc/cron.d/tremor-backup`
→ `app/backup.sh`): pg_dump quakes+umami → client-side AES-256 → MinIO on the Hetzner box at
`https://10.99.0.51:9000` (VM reaches it DIRECTLY via the UniFi route to 10.99.0.0/24 — no public
exposure, no VPN/SSH on the VM). Upload key = MinIO user `tremor-backup`, **PutObject-only**;
bucket `tremor-backups` has versioning + 35d lifecycle. Secrets: `/root/tremor-backup/{backup.env,
backup.key}` on the VM; **escrow copies on the workstation** `~/.claude/secrets/
tremor-backup-{encryption.key,minio.secret}`. Restore runbook in app/DEPLOY.md — tested end-to-end
(537k rows). MinIO admin = root creds in CT 100 `/etc/default/minio` on hetzner; the CT's `mc` is
Midnight Commander, use `docker run minio/mc --insecure` from the workstation instead.
⚠️ 2026-06-10 outage lesson: hourly PVE vzdump job with `fleecing 0` to a crawling PBS target
froze VM 115's disk (guest writes wait on copy-before-write at the backup's speed) → site-wide
524s, D-state postgres. Peter cancelled the job; PBS perf investigation = separate session.

TODO follow-up: segregate VM 115 onto its own VLAN (outbound-only egress, no LAN). Data migrated via
`pg_dump --data-only -t raw_events -t ingest_state` → initdb → psql load (~305k rows, 32MB gz).
⚠️ `.gitignore` must NOT match `*.sql` (it'd drop `quakes/schema.sql` which initdb needs) — use `*.sql.gz`.

**Where (source):** working tree at `~/claude/projects/earthquakes/`. Code in `app/` (docker-compose stack).
Research docs in the project root: `PROVIDERS.md` (worldwide provider registry + 4 access tiers),
`DATA-SOURCES.md` (Colombia/Bogotá deep-dive — original example region, a Tier-3 hard case),
`STORAGE.md` (ingestion + DB design).

**Stack (running on claude-workstation-01 via docker compose, project name `quakes`):**
PostGIS + FastAPI API + a sync `worker`, dark Leaflet map UI. Two providers (~157k events): **USGS**
(global FDSN, public domain) + **SGC** (Colombia small quakes). Worker polls every 60s. UI has a
region selector (continents + ~45 countries) that zooms + bbox-filters events/charts. web/ is
bind-mounted into the app container → UI edits are live without rebuild; quakes/ code needs rebuild.

**SGC Colombia endpoint (the breakthrough — durable fact):** SGC has NO FDSN; saeprod is geo-fenced;
the old sismo.sgc.gov.co/ajax/query returns a `{"message":true}` stub. The WORKING live API (reachable
from NL, no auth) is the React viewer's backend:
`POST https://apicatalogador.sgc.gov.co/api/events/search/?page=N` (header Origin: https://www.sgc.gov.co,
body `{}`). 389k events, newest-first, 100/page; `page` is a QUERY param (body filters ignored).
Returns small quakes to ~M0.3. Colombia 30d: ~2095 SGC events vs ~6 USGS — that's the differentiator.
Adapter = `quakes/sgc.py` (kind `sgc_catalogador`); backfilled 2024→now.

**PUBLIC: https://tremorsonline.com** (+ www) — open-access, no auth (intentional). Served via a
Cloudflare **Tunnel** (`cloudflared` compose service, dials out → routes to app:8080; no inbound
ports, home IP hidden). Domain on Peter's PERSONAL Cloudflare account `11c195ddb38b83a917bc07f8445c4b73`
(same as playitsafe). Zone `3c89c4aafb9143e796ef55e13e0f17d0`, tunnel `tremor` id
`a6c205c8-769f-4f7f-aeff-9d1f2228ca06`. Tunnel run-token in `app/cloudflared.env` (chmod600, gitignored).
Ingress is remotely-managed (edit via `PUT /accounts/{acct}/cfd_tunnel/{id}/configurations`). Full
deploy notes: `app/DEPLOY.md`. cloudflared now runs on **VM 115** (not the workstation); internal
access is the LAN IP **http://192.168.17.88:8080** (NOT Tailscale — VM is off the tailnet by design).
Cloudflare API token for tremorsonline.com is Peter's personal token (Tunnel+DNS+Zone scoped); NOT
stored on disk — re-ask for it for future CF changes. The GCP secret
`proxmox-automation-cloudflare-api-token` is a DIFFERENT (chainlayer) account, can't see this domain.

**Providers live: 42 active** (sync-only custom adapters incl. jma, ssn, ign, ipma, bgs, tmd, cwa,
igp, csn, phivolcs — see the 2026-06-10 sprint note at the end; the old "IGP/CSN are blocked SPAs"
finding is OBSOLETE: IGP has a clean per-year JSON at ultimosismo.igp.gob.pe/api/ultimo-sismo/ajaxb/<yr>
and CSN has static per-day catalog HTML. Geoscience Australia (TYR-24) remains deferred/SPA-blocked.)
**Per-country coverage backlog in Linear (TYR):** created ~92 "Local source — <Country>" tickets
(13 covered→Done, 79 Backlog w/ candidate national agency) for the seismically-relevant countries,
flat in the Tremor project — the durable backlog for ongoing provider hunting. Belgium/Spain/Norway/UK
etc. are Backlog (find their EIDA/FDSN or JSON feed); Canada(31)/Iceland(29)/etc. keep their dedicated
tickets. Accessible new sources go in one-by-one as before (FDSN config or small custom adapter). (~385k raw rows, ~346k unique after dedup). Custom adapters (kind != fdsn,
each a `quakes/<name>.py` with `normalize()` + fetch + dispatch branches in ingest.py): sgc (Colombia),
**geonet** (NZ — quakesearch history + realtime feed; 22.5k events), **afad** (Türkiye — apiv2/event/filter,
M0.8 floor; 56.7k events), **bmkg** (Indonesia — gempaterkini+gempadirasakan, SYNC-ONLY no history, synth
event_id). Chile **CSN blocked** (WAF: csn.uchile.cl 403, map.json empty). JMA/Peru-IGP/Australia-GA still TODO.
**Reconcile scaling DONE (TYR-10, PRs #3-5):** dedup scopes on `ingested_at` (wall-clock, stamped now()
on upsert) + routes by dirty-set size — ≤5000 dirty rows → scoped incremental (live sync ≈1-2s); >5000
→ full bulk pass (affected-set spatial join explodes on clustered data, so 56k incremental ≈15min vs
8min full). Small adapter backfills auto-dedup; big ones take a one-time full. Future limit: full is
O(total) → needs spatial-temporal bucketing once DB hits millions (deeper history). **CF API token now
on the VM-source repo at `~/claude/projects/earthquakes/.env` (CLOUDFLARE_TOKEN, gitignored)** → unblocks
TYR-15 (WAF/rate-limit/Brotli/cache-purge). Cache staleness fixed (origin no-cache; CF respects it).
**Analytics: self-hosted Umami (TYR-16)** — `umami` compose service, reuses the Postgres (separate
`umami` DB), APP_SECRET in gitignored app/umami.env. Public via tunnel at **analytics.tremorsonline.com**
(dashboard login `admin` / pw in app/umami.env `UMAMI_ADMIN_PASSWORD` on VM; default rotated). Website
"Tremor" id 6f084540-f5df-42ef-ae28-2d5a0fdbe87e; beacon in index.html. Cookieless/no-PII → NO consent
banner; same for the localStorage UI prefs (TYR-17, key `tremor.prefs`: since/region/panel-collapsed).
Umami pw-change API = `POST /api/users/{id} {password}` (NOT /password — that 404s). TYR-11/12/15/16/17
all done.
**"I'm safe" feature (TYR-18, In Review — needs browser tap-test):** anonymous, passkey-only
(WebAuthn discoverable credential = the account, NO PII), bearer session in localStorage (no cookie),
shareable status link/QR + public read-only page at /safe/<token>. Code: quakes/safe.py (router
/api/safe: register|login begin/finish, /me, /status, /label, public /s/<token>), safe_* tables,
web/safe.html + safe-ui.js (uses @simplewebauthn/browser + qrcode CDN libs), webauthn==2.5.2 dep,
spec app/SAFE-FEATURE.md. RP_ID=tremorsonline.com → ONLY works on the https domain (not LAN IP).
v1: optional nickname, no recovery (passkey sync); quake-tagging stubbed (schema/API) not in UI yet.
Passkey flow CONFIRMED working by Peter. QR was broken (qrcode@1.5.4 has no CDN browser build → 404;
switched to qrcodejs@1.0.0). **Optional location sharing (TYR-35):** clicking "I'm safe" asks to add
current location (opt-in, browser geolocation) → lat/lon on safe_status → mini Leaflet map on the public
status page. Both QR-fix + location In Review pending Peter's re-test. Umami pw-change API quirk noted above.
**TYR-15 CF hardening DONE (Free plan, zone-level via API):** Brotli on, Browser-Cache-TTL=0
(respect origin), min-TLS 1.2, Always-HTTPS, HSTS 6mo, 0-RTT, Bot Fight Mode + AI-bots block, rate
limit /api* 50req/10s per IP (rule 99eece62106f44d68389896b8add50aa). Deferred: /api edge-caching
(would delay live pulse), purge-on-deploy (unneeded w/ no-cache — if added, mint least-priv purge
token for VM, don't put zone-edit token on the public box). Full details in app/DEPLOY.md. FDSN-text tier (below) was the earlier 14: (in app/providers.yaml, bind-mounted). usgs (geojson, auth2), sgc
(Colombia catalogador, auth1), ingv (Italy, text), gsi (Israel, text), usp (Brazil, text, auth1),
geofon (global, text, auth2), emsc (Euro-Med/global, text, auth2 — covers Greece since NOA is off),
**ethz** (Switzerland, text, auth1), **renass** (France+overseas, text, auth1 — real base is
`https://api.franceseisme.fr/fdsnws/event/1`, NOT renass.unistra.fr which 404s), **knmi** (NL incl.
Groningen induced, text, auth1), **lmu** (Germany/Austria regional, text, auth1 — node ignores
`limit`, harmless), **ncedc** (N.California+NV, text, auth1), **scedc** (S.California, text, auth1 —
needed a `_parse_iso` tweak in fdsn.py for slash-dates `2026/05/09 23:59:08`), **ipgp** (French
overseas volcano obs, text, auth1). noa (Greece) **disabled** (unreachable).
**Rejected:** geonet (FDSN 400s → use its own api.geonet.org.nz/quake), auspass (garbage lat0/lon0),
iris/earthscope (event svc retired ~2026-06), niep Romania (catalog stale, 204 for 2026), icgc
Catalonia (FDSN empty), ign Spain (serves nothing via FDSN — needs custom adapter). **Deferred:** ISC
(works on text but ~2yr-delayed historical only → no live benefit, huge volume). INGV/GSI geojson is
non-standard/HTML → use text. **~305k raw → ~279k unique after dedup (25.9k merged).** Dedup correctly
demotes global aggregators (usgs/geofon/emsc) under local auth1 nets where they overlap.
**⚠️ DOCKER SINGLE-FILE BIND-MOUNT TRAP:** editing `providers.yaml` then `docker compose restart
worker` does NOT take effect — restart keeps the OLD inode (Edit replaces the file atomically → new
inode). New backfill data lands (`docker compose run` = fresh container) but `/api/meta` + the live
sync loop stay on the old provider list. **Fix: `docker compose up -d --force-recreate app worker`.**
Directory mounts (web/, quakes/) are immune. Next worklist tier = custom adapters (GeoNet, Chile CSN,
BMKG, JMA, GA, AFAD, IGP) — each needs a small adapter like quakes/sgc.py. Region menu is server-driven: `/api/regions?since=&minmag=`
returns continents (always) + countries that have ≥1 event in the TF (with counts), via a VALUES
join + ST_Intersects; UI rebuilds the dropdown on TF change. Map adaptive cap = ~500 largest in
view (`/api/events?target=500`), slider reflects the effective floor (0–9, step 0.1).
**App must NOT run schema DDL on startup** (init_schema removed from api.py lifespan) — ACCESS
EXCLUSIVE locks block app startup behind a running reconcile; worker/`cli initdb` own the schema.
**Cloudflare force-caches .js/.css 4h (overrides origin headers); use CF Development Mode while
iterating** (don't version URLs — that disables edge caching). Origin sets no-store on /api only.
FDSN /count is NOT universal (INGV redirects, NOA/GSI 404) → backfill is **count-free** (query a window
with limit; if full, bisect). FDSN sync polls a recent window (sync_hours), not updatedafter.

**Dedup is DONE** (`app/quakes/dedup.py`): cross-source only (±20s / ≤100km, different providers),
primary = lowest `authority` (local nets=1 beat usgs=2), tie-break newest updated_at. Stored on
raw_events as `is_primary`/`cluster_id`/`authority`; API serves `WHERE is_primary`. ~364 merged
(usgs demoted under sgc/ingv/gsi; eastern-Med overlaps between ingv/noa/gsi). reconcile runs full
once (`cli reconcile --all`, ~3min over 172k) then incremental in the worker loop each 60s.
**LESSON: incremental reconcile with an unset cursor degenerates to an all-pairs self-join** that
runs forever and ACCESS-EXCLUSIVE-blocks app startup — guarded now (no cursor → run full instead).
quakes/ is bind-mounted into app+worker so code edits need only a restart.

**Key design facts (from research):** FDSN is the unifying standard. Only ~14-17 of 31 FDSN
datacenters serve *events*; no event federator exists → fan-out + dedup yourself. Events get revised
(automatic→reviewed), so upsert on `(provider, event_id)` keyed by `updated` timestamp.

**Live "new quake" pulse:** UI polls every 30s; pulses events occurred <10min ago OR newly appeared
since last poll (app/web/app.js syncPulses). web/ bind-mounted → UI edits are instant on refresh.
Local national networks (SGC Colombia, BMKG Indonesia, etc.) give small-quake completeness the
global catalogs lack — that's the differentiator. Licensing: USGS public domain, EMSC/GeoNet/INGV
CC BY, SGC CC BY-SA — all need per-source attribution in UI.

**ACTIVE TASK (resume here after compaction):** add more providers one-by-one, working top-down
through `app/PROVIDER-WORKLIST.md` (durable checklist with the exact probe→add→backfill→reconcile
procedure, what's done/blocked, and the prioritized TODO queue: FDSN-text nets first — ETHZ, RéNaSS,
KNMI, LMU, NCEDC, … — then custom adapters GeoNet/Chile/BMKG/JMA). Mark each ✅/❌ as you go.

**PRIVATE project → tracked in the Tyrion Linear (team TYR), project "Tremor"**
(https://linear.app/tyrion70/project/tremor-7d6d8c7b24ad) via the API key — see
[[reference_linear_tyrion]] + [[feedback_linear_private_vs_company]]. Issue-first + link GitHub
commits/PRs, same as company work. Past work seeded as TYR-5..TYR-20 (TYR-5..9 Done; TYR-10..20 open:
reconcile-scaling, panel bug, favicon, VLAN, history, Cloudflare, analytics, prefs, I'm-safe, more
adapters, CSN). Repo github.com/tyrion70/tremor.
See also [[reference_k8s_deploy_guide]] if it ever moves to the cluster.

**2026-06-10 evening sprint:** PWA (TYR-142, sw.js network-first + offline banner; Playwright
set_offline does NOT reach SW fetches — offline tests spawn+kill their own server; opaque tile
responses cost ~7MB quota padding → tiles load crossOrigin), web push (TYR-141, VAPID keys in
/opt/tremor/app/push.env on VM + escrow ~/.claude/secrets/tremor-push.env; worker notify_tick
after reconcile, push_sent dedup, <2h freshness gate), safety circles (TYR-143, /circle/<token>),
3 new providers: igp (Peru JSON), csn (Chile per-day HTML, WAF currently NOT blocking), phivolcs
(Philippines table scrape, broken cert chain → unverified fallback; ~1350 events/day densest net).
30 providers total. TYR-178 filed (source freshness in main UI).

**2026-06-10 late batch 2+3:** country investigation report at repo root
(PROVIDER-INVESTIGATION-2026-06-10.md); 33 covered-by-global tickets closed; 12 adapters shipped
across PRs #45/#46: ineter (C.America, local UTC-6), inpres (idSismo IS UTC), igepn (UTC column),
arso (Slovenia M<1), eqalert (RAS-origin only — skip EMSC/USGS/GFZ merged), gsdcy (Cyprus RSS),
snet/ovsicori (local UTC-6), igcup (Panama 12h UTC-5), uwi (E-Caribbean), nsc (Nepal AD+UTC cells),
insivumeh (Guatemala 6MB folium, marker-hash join, local UTC-6). Remaining open: ~10 implementable
(Belgium/Serbia/Bulgaria/Armenia/Romania-QuakeML/Vietnam/Tunisia/S.Africa/KZ/KG fiddly ones),
2 needs-key (Malaysia instant, S.Korea pending), 13 blocked-from-NL (retry via Hetzner egress).

**CF caching (TYR-15, 2026-06-11):** app sends `no-cache` on HTML/app.js/style.css (instant deploys) but `public,max-age=86400` on immutable assets (plates.json, icons, favicon, manifest) via `_IMMUTABLE` in api.py middleware. CF edge caches the IMAGES (png HIT) but NOT plates.json — **Cloudflare does not cache .json by extension default**, needs a Cache Rule (path /plates.json → eligible). Token in ~/claude/projects/earthquakes/.env CLOUDFLARE_TOKEN; zone 3c89c4aafb9143e796ef55e13e0f17d0. ssl mode = full (not strict; low risk via tunnel). Source-freshness pill (TYR-178) now in topbar reading /api/health.

**2026-06-11 batch 4 (PR #49, deployed 6b673dd):** 7 sources, all UTC. rob (Belgium ROB Atom, geo:lat/long + xhtml summary, magtype "M"+subscript), niggg (Bulgaria data.xml markers, time attr is UTC — verified vs USGS M5.2 Greece), seismors (Serbia seismo.gov.rs table, "Vreme (GMT)", mag cell is "M = 1.7" so regex the number, coords "44.15 N", ~500 rows/poll), nssp (Armenia nssp.am Leaflet JS — var lat/lng PRECEDE bindPopup; Date is UTC verified vs EMSC), igpvast (Vietnam Joomla RSS, Vietnamese bulletin states giờ GMT; vĩ Bắc/Nam=lat, kinh Đông/Tây=lon), inmtn (Tunisia meteo.tn table; lat/lon cols are HTML-COMMENTED-OUT but _CELL regex still matches them; H.Origine GMT; page 503s sometimes). **49 providers total.** Added config-level `params` passthrough for fdsn providers (threaded through _fdsn_walk + sync) + fdsn._parse_quakeml (fmt xml/quakeml). **NIEP Romania (TYR-56) CONFIRMED stale**: eida-sc3.infp.ro QuakeML parses fine (674 historical Vrancea events backfilled, bbox 43-49N/20-30E) but catalog ends ~2025-09-10, every 2026 window = 0 → NO live coverage. niep enabled for historical value; live sync harmlessly returns 0. TYR-56 left In Review (historical-only) pending user call on finding a live NIEP node. Other 6 closed Done. S.Africa TYR-130 still deferred (no coords). FakeResponse gained raise_for_status() for fdsn tests.

**CF toggles applied 2026-06-11:** (1) plates.json Cache Rule created via rulesets API (http_request_cache_settings entrypoint; expr `http.request.uri.path eq "/plates.json"` → set_cache_settings cache:true edge_ttl override 86400) — verified MISS→HIT. (2) SSL mode flipped full→strict (site stayed 200; tunnel cert valid). MetMalaysia TYR-105: token `5cc6...` authenticates, datacategoryid=GENERAL is correct (400=missing-arg not 403), but EARTHQUAKE data query still missing a required param (likely locationid) and /locations 403s for this token → free token may be forecast-scoped; needs the docs-page earthquake query example. Key escrowed at ~/.claude/secrets/tremor-met-malaysia.env.
