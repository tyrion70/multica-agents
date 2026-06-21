---
name: tremor-testing
description: QA and acceptance-test the Tremor earthquake-monitor app (github.com/tyrion70/tremor — PostGIS + FastAPI + Leaflet). Use when grading a coded Tremor issue against its acceptance criteria, running the pytest suite (unit / db / ui markers), standing up a throwaway test/staging stack that is NOT production, or producing an adversarial per-criterion PASS/FAIL QA verdict. The `tremor` skill owns deploy/reconcile/provider mechanics — this skill references it for HOW the stack runs and adds HOW to test it. Test target only; never QA against VM 115 / tremorsonline.com.
---

# Tremor QA / acceptance testing

This is the testing-stage how-to for the **Issue QA** agent (lifecycle stage 3):
take a coded Tremor change, run its suite, stand it up somewhere that is **not
production**, and grade it against falsifiable acceptance criteria with a
per-criterion PASS/FAIL verdict.

**Relationship to the `tremor` skill — reference it, don't fork it.** The
`tremor` skill is the source of truth for the stack, deploy flow, reconcile
footguns, the proxy fleet, and every prod operational detail. This skill does
not restate that mechanics — when you need to know *how the worker reconciles*
or *how deploy.sh decides zero-downtime vs recreate*, read `tremor`. Here we only
cover what's specific to **testing and grading**: the suite, a disposable stack,
and the acceptance procedure.

Repo: `github.com/tyrion70/tremor` (PRIVATE). Everything below assumes the app
lives under `app/` in a checkout (the QA agent gets one via
`multica repo checkout <url> --ref <pr-branch>`). Live state (VM IP, provider
count) is in the `project_earthquakes` memory and the Multica "Tremor" project.

## The test surface (what exists, verified against the repo)

- `app/pytest.ini` defines two markers: **`db`** (needs a PostGIS database via
  `TEST_DATABASE_URL`) and **`ui`** (headless-browser smoke test, needs a running
  app at `APP_URL` + Playwright Chromium). Default opts are `-q`.
- `app/tests/` holds ~25 test modules. Unmarked = pure unit (adapter parsers,
  FDSN client, cache/rate-limit, header policy) — **no network, no DB** (they run
  against the `FakeClient` in `tests/conftest.py` with captured real feed
  samples). `pytestmark = pytest.mark.db` modules need Postgres; `pytest.mark.ui`
  modules need a live app + browser.
- `app/requirements-dev.txt` = `pytest`, `httpx`, `pyyaml`. UI tests additionally
  need `playwright` + a Chromium install.
- CI is `.github/workflows/ci.yml`, three jobs: **`unit`** (`-m "not db"`),
  **`dedup-db`** (`-m db` against a `postgis/postgis:16-3.4` service), **`ui-smoke`**
  (`-m ui` against a gunicorn-served app, fails on any console error / CSP
  violation). A passing CI is **necessary, not sufficient** — see the adversarial
  checklist.

## Running the suite (real commands)

Python 3.12. From the repo root, working dir is `app/`:

```bash
cd app
pip install -r requirements.txt -r requirements-dev.txt
```

**Tier 1 — unit (fast, no net, no DB).** Run this first; if it's red, stop and
report — nothing else is worth running.

```bash
cd app && python -m pytest -m "not db"
```

**Tier 2 — db integration (real PostGIS).** Covers dedup, circles, insights,
push. `TEST_DATABASE_URL` is **deliberately a different env var than
`DATABASE_URL`** so a stray run can never touch the live database — keep it that
way; never point it at VM 115's DB. Spin a throwaway PostGIS (see next section),
then:

```bash
cd app
TEST_DATABASE_URL=postgresql://quakes:quakes@localhost:5432/quakes_test \
  python -m pytest -m db
```

(The `db` modules module-level-skip when `TEST_DATABASE_URL` is unset — a
"skipped" db suite means you forgot the database, not that it passed.)

**Tier 3 — ui smoke (headless browser).** Needs a running app and Chromium.
Fails on **any** browser console error or CSP violation across the pages it
loads — this is the cheapest catch for a broken deploy.

```bash
cd app
pip install playwright && playwright install --with-deps chromium
# ... start the app on :8080 first (see Option A below) ...
APP_URL=http://localhost:8080 python -m pytest -m ui
```

**Full local run = mirror CI:** Tier 1 + Tier 2 + Tier 3. If you only have time
for one tier, Tier 1 gates everything; if the change touches SQL/dedup, Tier 2 is
mandatory; if it touches `web/` or any endpoint the map calls, Tier 3 is
mandatory.

## A test/staging stack that is NOT production — and teardown

> **Hard prod-safety rules. Read before bringing anything up.**
> - **Production** = the compose project **`quakes`** on **VM 115** (`/opt/tremor/app`,
>   LAN `192.168.17.88:8080`, public `https://tremorsonline.com`). QA **never**
>   runs against it, points a DSN at its DB, or loads its origin.
> - **Never run `deploy.sh` for QA.** `deploy.sh` does `git pull` on the VM and
>   mutates the live stack — it is a *production deploy*, not a test harness.
> - **Never bring up `cloudflared` in a QA stack** — its token (`cloudflared.env`)
>   dials the live `tremorsonline.com` tunnel. Skip `umami` too. QA brings up only
>   `db` + `app` (+ `worker` if you need the sync loop).
> - Use **dev credentials only** (the compose default `quakes:quakes`). Never put
>   a real secret in a QA env file, a comment, or a log.

### Option A — ephemeral stack (preferred; this is what CI does)

A disposable PostGIS container plus a local gunicorn on `127.0.0.1`. Fastest, and
guaranteed isolated from prod because it never touches the VM or the compose
project name.

```bash
# 1. throwaway PostGIS (random host port if 5432 is taken; here 5432)
docker run -d --name tremor-qa-db -p 5432:5432 \
  -e POSTGRES_USER=quakes -e POSTGRES_PASSWORD=quakes -e POSTGRES_DB=quakes \
  postgis/postgis:16-3.4
# wait for: docker exec tremor-qa-db pg_isready -U quakes

cd app
export DATABASE_URL=postgresql://quakes:quakes@localhost:5432/quakes
python -m quakes.cli initdb          # creates schema + PostGIS + indexes

# 2. (optional) seed deterministic rows for UI/feature tests — the CI smoke seed
#    inserts a safe-token + circle, a 'smoke' M4.2 event, and an 'on this day'
#    M7.5. Reuse the seed block in .github/workflows/ci.yml (ui-smoke job) verbatim.

# 3. run the app exactly as prod does (catches worker-class / import regressions)
nohup gunicorn quakes.api:app -k uvicorn_worker.UvicornWorker -w 1 \
  -b 127.0.0.1:8080 > /tmp/tremor-qa.log 2>&1 &
for i in $(seq 1 30); do curl -sf http://localhost:8080/api/meta >/dev/null && break; sleep 1; done
```

**Teardown (always do this):**

```bash
pkill -f 'gunicorn quakes.api:app' || true
docker rm -f tremor-qa-db
```

### Option B — full compose stack on an isolated project name

When acceptance needs the real **worker / 60s sync / reconcile** loop (e.g. a
provider or dedup change), bring up the compose stack under a **separate project
name** so its network + volume can't collide with prod, and select only the
non-public services:

```bash
cd app
# -p gives an isolated project (own network + 'tremor-qa_dbdata' volume); only db/app/worker
POSTGRES_PASSWORD=quakes docker compose -p tremor-qa up -d --build db app worker
# NOTE: compose publishes app on host :8080 — if you run this on a host already
# running prod, change the published port or run on a clean host. cloudflared and
# umami are intentionally NOT listed, so the prod tunnel is never dialed.
```

The worker now auto-reconciles every 60s. **All the reconcile footguns in the
`tremor` skill apply here** (don't run a manual `quakes.cli reconcile` while the
worker is up; the providers.yaml stale-inode trap; full-pass `merged=0` is normal
mid-pass) — read that skill before poking reconcile, even in QA.

**Teardown (the `-v` drops the isolated volume so no state leaks into the next run):**

```bash
docker compose -p tremor-qa down -v
```

## Acceptance-grading procedure → per-criterion PASS/FAIL

A green suite is evidence, not a verdict. Grade like this:

1. **Pull the criteria.** Read the issue description + the Refiner's acceptance
   criteria (and `pr_url` from metadata). Each criterion must be **falsifiable** —
   a concrete, checkable claim. If a criterion is vague ("works well", "is fast")
   you cannot grade it: flag it as **UNGRADEABLE** and ask the Refiner/Coder to
   make it falsifiable rather than guessing.

2. **Bind each criterion to an objective probe.** One of:
   - a named test (`python -m pytest -m db tests/test_dedup_db.py -k <case>`),
   - an HTTP check (`curl -s localhost:8080/api/events?... | jq ...`),
   - a SQL assertion (`docker exec tremor-qa-db psql -U quakes -c "SELECT ..."`),
   - a UI assertion (a `ui`-marked test, or a Playwright/`curl` check of the page).

3. **Run each probe in the test stack and record the outcome** as one of
   **PASS / FAIL / BLOCKED** (BLOCKED = couldn't test, e.g. needs the https domain
   — say why), plus the **evidence** (the command and a short output snippet).

4. **Emit a verdict table.** One row per criterion:

   | # | Acceptance criterion | Probe | Result | Evidence |
   |---|----------------------|-------|--------|----------|
   | 1 | New SGC events appear within 60s | `curl /api/events?... \| jq` after sync | PASS | 3 rows, ts UTC-verified |
   | 2 | No double-plotting vs USGS | `SELECT count(*) ... WHERE is_primary` | FAIL | 2 primaries for same quake |

5. **Overall verdict.** **PASS** only if **every** criterion is PASS **and** the
   full CI/suite is green **and** the relevant adversarial checks below are clear.
   Otherwise **FAIL**, naming the exact failing criterion/check. Then follow the
   QA agent's routing: on FAIL set the issue back so the Coder picks it up and say
   what's broken; on PASS leave it `in_review` for human approval before deploy
   (the Deployer owns prod). Never deploy to prod yourself.

## Adversarial edge-case / failure-path checklist

Walk the items relevant to the change under test — this is where QA earns its
keep beyond "CI green". Most are drawn from real Tremor outages (see `tremor`).

**Data / provider correctness**
- [ ] **Timezone:** a new/changed source's timestamps verified against USGS/EMSC
      for the *same* quake. Many national feeds emit local time unlabelled — a
      silent offset is the most common adapter bug.
- [ ] **Dedup / double-plot:** the same quake from multiple agencies collapses to
      one primary. Check `is_primary` / `cluster_id`; a regression plots each
      event 2–4× on the map.
- [ ] **Bad feed degrades, doesn't crash:** simulate a provider 503 / 403
      geofence / broken cert / empty body — sync logs and continues, it does not
      take the worker down.

**Reconcile safety** (if Option B / worker is involved)
- [ ] No **all-primary** regression (every quake plotting multiple times) — the
      classic symptom of a reconcile killed mid-`_DEMOTE`.
- [ ] No manual `reconcile` run while the worker is up (they deadlock). A
      full-pass window showing `merged=0` is normal, not a fault.

**API / web**
- [ ] **Cache headers:** HTML / `app.js` / `style.css` send `no-cache` (instant
      deploys); immutable assets `max-age`. `.json` is NOT edge-cached by
      extension — a new JSON endpoint that must be fresh needs its own rule.
- [ ] **Console / CSP:** the `ui` suite is clean (no console error, no CSP
      violation) on every page the map loads.
- [ ] **Rate limit:** CF returns 429 at ~10 req/s/IP — so **load-test the origin
      directly** (`127.0.0.1:8080` / LAN), never through Cloudflare, or you're
      measuring the WAF, not the app.
- [ ] **`/api/health`:** reports `ok`/`warn` correctly for provider staleness on
      the change.

**Deploy mechanics** (validate in the test stack, never on prod)
- [ ] **Zero-downtime:** after a SIGHUP reload the master keeps the socket and
      `/api/health` passes — the new worker isn't crash-looping.
- [ ] **providers.yaml stale-inode trap:** editing the single-file mount then
      `restart` does NOT take effect — it needs `up -d --force-recreate`. Confirm
      `/api/meta` reflects the new provider list, not the old inode.
- [ ] **No schema DDL on app startup** — `init_schema` must stay out of the API
      lifespan (ACCESS EXCLUSIVE locks would block startup behind a reconcile).

**Feature-flag / env**
- [ ] **Graceful when secrets absent:** without `push.env` the push API returns
      404 and the UI hides the alerts row — a missing optional secret must not
      500.
- [ ] **WebAuthn / "I'm safe":** `RP_ID = tremorsonline.com`, so the passkey flow
      works ONLY on the https domain — it **cannot** be fully tested on
      `localhost`/LAN. Mark that criterion **BLOCKED** with the reason rather than
      failing it.

**Secrets hygiene**
- [ ] No token, key, or live credential printed into the verdict comment or any
      log. QA uses dev creds only.

## Pointers (don't duplicate — defer to these)

- **`tremor`** — the stack, `deploy.sh`, reconcile model + footguns, the proxy
  fleet, Cloudflare/backup/analytics. Source of truth for *how it runs*.
- **`ssh`** — reaching a host (the QA agent uses `id_ed25519_peter`); note VM 115
  is deliberately off the tailnet, reached on the LAN IP only.
- **`bitwarden`** — pulling any credential a test genuinely needs (rare in QA;
  dev creds cover the test stack).
