---
name: datafeeds-health-findings
description: Run the chainlink-datafeeds-health report READ-ONLY and turn its findings into deduplicated Multica issues. Use whenever an agent (e.g. a scheduled findings sweep) must check Chainlink data-feeds health and file/refresh findings as issues. Defines the exact finding→issue mapping, the dedup metadata keys (adapter_id / feed_contract), the new/known/recovered lifecycle (never auto-close), the N-consecutive-window debounce on new degraded-adapter issues (CHA-197), where issues are placed (the "Datafeeds health — open findings" project, not as sub-issues), and the hard zero-mutation guardrail. Pairs with bitwarden (token) and grafana-monitoring (Loki enrichment).
---

# Datafeeds health → findings issues

This skill turns the **read-only** `chainlink-datafeeds-health` report into a
deduplicated set of Multica issues. It is the source of truth for the
finding→issue mapping; bind it to the agent that runs the periodic sweep.

The report tool itself (`github.com/tyrion70/chainlink-datafeeds-health`,
built under CHA-154) only *observes* — it reads Prometheus through the Grafana
Cloud proxy and prints findings. This skill adds the issue-filing layer on top.
**Active triage / restarts are explicitly out of scope** (tracked separately as
CHA-165) — see the guardrail at the bottom.

---

## 0. Prerequisites

- **Findings project id.** All issues land in the dedicated
  **"Datafeeds health — open findings"** project (created and wired in Stage 3).
  Get its id once with `multica project list --output json` and reuse it; this
  skill refers to it as `$PROJECT`.
- **Squad assignee.** Issues are assigned to the **Chainlayer Squad DeepSeek** (the
  permanent assignee), id `6cb3a5fe-fd11-4ddd-8f06-395d3b82ef11`.
- Bitwarden access (`bitwarden` skill) for the Grafana viewer token.

---

## 1. Run the report (read-only, JSON)

```bash
# 1. Check out the report tool
multica repo checkout https://github.com/tyrion70/chainlink-datafeeds-health
cd chainlink-datafeeds-health

# 2. Fetch the Grafana viewer token at runtime (never commit it).
#    Bitwarden item "readonly chainlayer credentials", field GRAFANA_VIEWER_TOKEN
#    — via the bitwarden skill.
export GRAFANA_VIEWER_TOKEN="<token from Bitwarden>"

# 3. Run with --json — the machine-readable source of truth.
python3 chainlink-datafeeds-report.py --json > run.json
```

`--json` emits the **same** findings and thresholds as the text report but with
**full, untruncated** contract ids, and it **subsumes `--by-adapter`** (the
per-bridge rollup is always included), so you never need a second invocation.
stdlib-only Python 3, no `pip install`. Do not change detection thresholds —
file against the defaults the tool ships with.

### The JSON you consume (`v3` shape)

```jsonc
{
  "as_of": "2026-06-28T12:58:00Z",      // RFC3339 UTC — use as the <ts> in comments
  "summary": { "silent": 2, "erroring": 0, "degraded_adapter": 9,
               "lowfreq_por": 4, "dead_frozen": 1, "decommissioned": 9,
               "suppressed": 208, "unclassified": 0 },
  "findings": [ /* one per finding; field `bucket` selects the mapping below */ ],
  "adapters": [ /* per-bridge rollup = the --by-adapter view */ ]
}
```

A `findings[]` entry (the fields this skill uses):

```jsonc
{
  "bucket": "DEGRADED_ADAPTER",   // SILENT | ERRORING | DEGRADED_ADAPTER | LOWFREQ_POR
                                  // | DEAD_FROZEN | DECOMMISSIONED | SUPPRESSED | UNCLASSIFIED
  "job_name": "USDD / USD | OCR2 | contract 0x837Af6E8…2Ab83b | network tron-mainnet",
  "contract": "0x837Af6E843EDa17079d742b44A800f2E6D2Ab83b",  // FULL (0x or base58); null if unknown
  "network": "tron",
  "completed": 2805.79, "completed_recent": 840.0, "errors": 794.21,
  "error_fraction": 0.2206,
  "adapters": [                   // failing bridges ON THIS feed
    { "task_id": "ds2", "bridge_name": "bridge-elwood",
      "label": "ds2→bridge-elwood", "errors": 264.74, "completed": 95.26,
      "error_fraction": 0.73 }
  ]
  // SILENT also carries `note`; DEAD_FROZEN carries `transmit`,`frozen`,`med_seen`;
  // DECOMMISSIONED carries `reason`.
}
```

An `adapters[]` rollup entry (per bridge, active feeds only):

```jsonc
{ "bridge_name": "bridge-coinmetrics-lwba",
  "feeds_failing": 3, "feeds_using": 395,   // → the failing/using ratio
  "errors": 364.01, "networks": ["bsc","ethereum","polygon"],
  "adapter_wide": false,                     // true ⇒ failing on ≥80% of feeds that use it
  "feeds": [ /* full job_name of each failing feed */ ] }
```

---

## 2. Finding → issue mapping

Drive everything off `bucket`. There are exactly two issue *shapes* — one per
**adapter** and one per **feed** — plus two buckets that are never auto-filed.

| Bucket(s) | Issue shape | One issue per | Dedup key |
|---|---|---|---|
| `DEGRADED_ADAPTER` | **per-adapter** | failing bridge (`bridge_name`) | `adapter_id` |
| `SILENT`, `ERRORING`, `DEAD_FROZEN` | **per-feed** | feed (full `contract`) | `feed_contract` |
| `LOWFREQ_POR`, `DECOMMISSIONED` | **not filed** | — (counts only) | — |
| `SUPPRESSED`, `UNCLASSIFIED` | **not filed** | — (gating / noise) | — |

### 2a. Per-adapter issues (`DEGRADED_ADAPTER`)

One issue **per failing bridge**, not per feed — a single adapter failing across
many feeds is one issue. Build each from the `adapters[]` rollup entry plus the
`DEGRADED_ADAPTER` findings that name that bridge:

- **Group** all `findings` where `bucket == "DEGRADED_ADAPTER"` by the
  `bridge_name` inside their `adapters[]`. (A feed degraded on two bridges
  contributes a row to two adapter issues.)
- **Header** comes from the matching `adapters[]` rollup entry:
  `feeds_failing/feeds_using` (the failing/using ratio), `errors`, `networks`,
  and the `adapter_wide` flag.
- **Per-feed table** — one row per contributing finding:

  | Feed | Network | Contract (full) | feed err/used | adapter err/completed |
  |---|---|---|---|---|
  | USDD / USD | tron | `0x837Af6E8…2Ab83b` (full) | 22% (809e/2,791c) | ds2→bridge-elwood 75% (270e/90c) |

  Feed name = `job_name`; contract = full `contract`; feed err = finding
  `error_fraction` with `errors`/`completed`; adapter err/completed = the
  matching `adapters[]`-on-feed entry's `error_fraction`, `errors`, `completed`.

The table lives **inside** the adapter issue and is **rewritten in full every
run** (feeds can join/leave as the adapter degrades or partially recovers).

- **Title:** `DEGRADED ADAPTER: <bridge_name> (<feeds_failing> feed(s))`
- **Metadata:** `adapter_id = <bridge_name>` (exact string, e.g. `bridge-elwood`).

### 2b. Per-feed issues (`SILENT`, `ERRORING`, `DEAD_FROZEN`)

A whole-feed alert is **one issue per feed**, keyed by its contract. Body:
bucket, `job_name`, `network`, full `contract`, `error_fraction` with
`errors`/`completed`/`completed_recent`, the named failing adapter(s) from
`adapters[]` (the `label`, e.g. `ds1→bridge-proof-of-reserves 100%`), and the
bucket-specific extras (`note` for SILENT; `transmit`/`frozen`/`med_seen` for
DEAD_FROZEN).

- **Title:** `<BUCKET>: <feed name> (<network>)` — e.g.
  `SILENT: USDO Reserves (base)`.
- **Metadata:** `feed_contract = <full contract>` (the `0x…` or base58 string,
  exactly as in JSON — never the truncated text-report form).
- If `contract` is `null`, fall back to `feed_contract = job_name` and note the
  missing contract in the body; this keeps dedup stable until the contract is
  known.

### 2c. Never auto-filed (counts only)

- **`LOWFREQ_POR`** — PoR/NAV feeds are chronically near-idle *by design*;
  paging on their silence is noise.
- **`DECOMMISSIONED`** — the OCR job is gone from the node; excluded so it
  doesn't sit as permanent noise.

Do **not** open issues for these. Report them only as the counts from
`summary.lowfreq_por` / `summary.decommissioned` (e.g. in a run-summary comment
on the tracking issue, or a log line). `SUPPRESSED` (closed-market gating) and
`UNCLASSIFIED` are likewise never filed.

---

## 3. Dedup convention

**Match on metadata, never by parsing the title.** Titles are human-facing and
change; the dedup keys are the contract.

| Issue shape | Metadata key | Value |
|---|---|---|
| per-adapter | `adapter_id` | `bridge_name` (e.g. `bridge-elwood`) |
| per-feed | `feed_contract` | full contract (`0x…` / base58) |

### Per-key procedure (run for every finding that maps to an issue)

```bash
# 1. List open findings-project issues that already carry this key.
multica issue list --project "$PROJECT" \
  --metadata adapter_id=bridge-elwood --output json
#   (per-feed: --metadata feed_contract=0xC28b74022D625849ff43f6E5...)

# 2. Treat status done/cancelled as NOT open. Among the open ones:
#    - exactly one match  → UPDATE it (§4 Known)
#    - no match           → CREATE it (§4 New)
```

`multica issue list` supports `--metadata key=value` (AND-combinable,
JSON-typed — contracts and bridge names sniff as strings, which is what we
want). Scope by `--project "$PROJECT"` so you only ever match findings issues.
If two open issues somehow share a key, update the oldest and leave a comment
flagging the duplicate — don't silently pick one.

---

## 4. Lifecycle

Decide per dedup key, comparing **this run's findings** against **open issues in
the project**.

- **New** — key present in this run, **no** open issue with it →
  `multica issue create` with the body from §2, `--project "$PROJECT"`,
  `--assignee-id 6cb3a5fe-fd11-4ddd-8f06-395d3b82ef11`, `--status todo`, then
  pin the dedup metadata key. **For `DEGRADED_ADAPTER` (per-adapter) issues this
  step is gated by the debounce in §4a — open the new issue only once the adapter
  has been over threshold for `N` consecutive windows.** The per-feed buckets
  (`SILENT` / `ERRORING` / `DEAD_FROZEN`) are **never** debounced; they file on
  the first over-threshold run as before.
- **Known** — key present in this run **and** an open issue exists →
  `multica issue update` to **rewrite the body/table** with fresh numbers, and
  add **one** comment: `still degraded as of <as_of>` (per-adapter) or
  `still <bucket> as of <as_of>` (per-feed). **Do not create a second issue.**
- **Recovered** — key is on an **open issue** but **absent from this run's
  findings** → post a **`recovered as of <as_of>` comment only**. **Never
  auto-close, never change status, never reassign.** A human (QA/Tech Lead)
  decides when to close. To find these: list all open issues in `$PROJECT`,
  read each one's `adapter_id`/`feed_contract`, and diff against the set of keys
  this run produced.

Use `as_of` from the JSON (RFC3339 UTC) as the `<ts>` in every comment so the
timeline is anchored to the evaluation time, not wall-clock.

### 4a. DEGRADED_ADAPTER debounce (CHA-197)

A single threshold-edge flap — one bridge tipping just over `--adapter-error-frac`
for one hour (CHA-195 / CHA-198: bridge-bea at 10.1%) — used to file an issue
immediately. Per Peter's decision (option 1), a **new** `DEGRADED_ADAPTER` issue is
opened only once the adapter (`bridge_name` = the `adapter_id` dedup key) has been
over threshold for **`N` = 4 consecutive hourly windows**. This gates **only
new-issue creation** for the per-adapter shape; everything else in §4 is unchanged,
and `SILENT` / `ERRORING` / `DEAD_FROZEN` are never debounced.

**Constants — tune here, never inline:**
- `N_CONSECUTIVE = 4` — windows required before a new degraded-adapter issue is filed.
- `gap_tolerance` — how long the run series may be interrupted before the streak is
  considered broken. It is the default of the SQL helper below (**150 min**); pass
  an explicit value only to override.

**The streak is read from the persistence DB** (the CHA-201 `datafeeds_health`
schema on multica-02). Migration `0004` of the report repo provides the read-time
helper `adapter_degraded_streak(bridge, ref_as_of [, gap_tolerance])`, which returns
the count of **consecutive prior runs** the bridge was in a `DEGRADED_ADAPTER`
finding, walking `health_run` backwards from `ref_as_of`: a present run **without**
the bridge degraded breaks it (observed recovery); a single missed sweep within
`gap_tolerance` does not; ≥2 missed runs do. It does **not** include the current run.

**Why "prior" and a `+1`.** The sweep files issues **before** `sweep-ingest.sh`
runs, so the current run is not yet in the DB (persistence is deliberately last and
fail-soft — CHA-201 — so a DB hiccup never gates filing). Do **not** reorder to
ingest-then-file. Compute:

> `streak = 1 (current run — run.json has the bridge in DEGRADED_ADAPTER)`
> `       + adapter_degraded_streak(bridge, <run as_of>)   -- prior runs, from the DB`

and create the new issue only when `streak >= N_CONSECUTIVE`. Below that, **file
nothing** for that adapter this run — the degradation is still fully captured in
`health_finding` for history, and the streak resumes (or resets) on the next run.

Per dedup key, once §3 finds **no** open issue for the `adapter_id`:

```bash
# DSN from Bitwarden: item "DATAFEEDS_HEALTH_DSN", field DATAFEEDS_HEALTH_DSN, vault
# company folder — the SAME DSN the ingester uses; never commit or echo it.
prior=$(psql "$DATAFEEDS_HEALTH_DSN" -At \
  -c "SELECT datafeeds_health.adapter_degraded_streak('bridge-elwood', '<run as_of>'::timestamptz)")
# streak = 1 (current run) + prior;  open the new issue iff streak >= 4
```

**DB unreachable at filing time → fail-closed for DEGRADED_ADAPTER only.** If the
streak can't be read (DSN unset, DB down, query error), **do not open the new
degraded-adapter issue this run** — defer; it files next run once the streak is
confirmable. This class is low-severity and the data is captured regardless, so
deferring beats re-introducing churn by fail-open filing. **Never let a DB problem
gate `SILENT` / `ERRORING` / `DEAD_FROZEN` filing — those always proceed.**

**Debounce gates first creation only — it never re-arms.** Once the issue exists,
the **Known** path takes over immediately: subsequent over-threshold runs append the
`still degraded as of <as_of>` update to the same issue (dedup by `adapter_id`), and
recovery closes via the existing path. After a close, a fresh degradation must
re-accumulate `N` consecutive windows before a new issue is filed (the streak is the
current unbroken run; a recovery/close gap breaks it). Issues already open when this
ships are unaffected.

---

## 5. Placement

- Findings are **issues in the "Datafeeds health — open findings" project**
  (`--project "$PROJECT"`), **assigned to the Chainlayer Squad**, `--status todo`.
- They are **NOT** sub-issues — do **not** pass `--parent`, and do not file them
  under CHA-165 or any tracking parent. Project membership is the only grouping.

---

## 6. Investigation depth — READ-ONLY guardrail

Beyond the report's metrics, the filing agent **MAY** enrich an issue with:

- **Loki adapter logs** via the `grafana-monitoring` skill — read-only LogQL
  through the Grafana datasource proxy (e.g. the failing bridge's container logs
  in the `chainlink-ea*` namespaces) to add context to the issue body.
- **A read-only bridge GET** — a plain HTTP `GET` against the external-adapter
  endpoint to confirm reachability / capture the error response. GET only.

**Hard guardrail — ZERO production mutations. Allowed = reads only:**

| Allowed (read) | Forbidden (mutation) |
|---|---|
| Prometheus / report metrics | Restarting adapters or nodes |
| Loki log queries (LogQL GET) | Any `POST`/`PUT`/`PATCH`/`DELETE` to a bridge |
| Read-only bridge `GET` | Redeploys, scaling, k8s `apply`/`delete` |
| Reading k8s/Grafana state | Key rotation or secret writes |
| Filing/updating Multica issues | Any config change / MR to prod |

If a finding looks like it needs a restart, a key rotation, or any write, that
is **active triage (CHA-165)** — file/refresh the issue and hand off; **do not
perform the mutation**. State this in the issue if relevant. The whole point of
this lane is a safe, repeatable, observe-and-file sweep.

---

## Quick reference

```
run --json ──► for each finding:
  DEGRADED_ADAPTER → group by bridge_name → per-adapter issue, key adapter_id
  SILENT/ERRORING/DEAD_FROZEN → per-feed issue, key feed_contract (full)
  LOWFREQ_POR / DECOMMISSIONED / SUPPRESSED → counts only, never filed

dedup: list --project $PROJECT --metadata <key>=<val>  → match=update, none=create
lifecycle: new=create · known=update+“still …” comment · recovered=“recovered …” comment ONLY (never close)
debounce (§4a, CHA-197): new DEGRADED_ADAPTER issue only when streak >= N(4);
  streak = 1 (current run) + adapter_degraded_streak(bridge, as_of) from the DB;
  DB unreachable → defer DEGRADED_ADAPTER (fail-closed), never SILENT/ERRORING/DEAD_FROZEN
placement: project issue, squad assignee, status todo, NEVER --parent
guardrail: reads only (metrics, Loki, bridge GET) — zero prod mutations
```
