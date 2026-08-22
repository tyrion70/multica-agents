---
name: rag-ops
description: Operate and extend ChainLayer's in-house RAG ops assistant — the on-network Q&A bot over internal docs, runbooks, incidents, and Linear, served from its own chat model + embedder + Qdrant (no third-party inference). Use to add/rescope a corpus source, run or refresh ingestion, reason about the secret filter + its mandatory IaC audit gate, debug retrieval/citations, run the eval, or deploy the CLI/Slack bot. Code is github.com/tyrion70/rag-ops-assistant; it runs on rag-refresh + gx10-f018. NOT the chainlayer-knowledge skill (that's infra facts) — this is the RAG system itself.
---

# rag-ops — the in-house RAG ops assistant

A Retrieval-Augmented-Generation assistant over ChainLayer's internal knowledge:
ask an operational question (CLI or Slack) and get a **grounded, `[n]`-cited,
on-network** answer. Its own chat model, embedder, and vector DB — nothing
leaves the LAN, no shared/third-party inference. Built CHA-42, productionized
into one repo in CHA-106.

- **Code:** `github.com/tyrion70/rag-ops-assistant` (private). Change it via the
  **git-pr** skill (Multica-issue-first). The repo's own READMEs are the
  authoritative HOW-TO — this skill is the durable map + the safety rules.
- **Runs on:** `rag-refresh` (192.168.16.130 / tailnet 100.64.220.121 — the
  bot/MCP/Qdrant/refresh host) + `gx10-f018` (192.168.19.207, GPU serving the
  models). Reach both via the **ssh** skill (`rag-refresh` resolves on the
  tailnet as `rag-refresh.java-moth.ts.net`; f018 is a root hop from it).
  Moved here from `claude-readonly-01` on 2026-08-21 (old host's RAG services
  decommissioned).
- **Tracking:** Multica project **RAG**, umbrella `CHA-42`. Follow-ups are
  per-issue (see Roadmap below).

## Topology — who serves what

| Component | Host | Endpoint | Service |
|---|---|---|---|
| Chat LLM | gx10-f018 GPU | `:8801/v1` `Qwen3-30B-A3B-Instruct` | `rag-chat.service` (systemd) |
| Embeddings | gx10-f018 GPU | `:8802/v1` `Qwen3-Embedding-0.6B` (1024-dim) | `rag-embed.service` (systemd) |
| Vector store | rag-refresh | `127.0.0.1:6333` Qdrant v1.18.2 | docker compose (`rag-qdrant`) |
| Ingester / CLI / bot | rag-refresh | — / outbound WS | `venv` + `rag_ops` pkg; `rag-slack.service` |
| MCP server (`rag_ask`) | rag-refresh | `100.64.220.121:8041/sse` (Tailscale-only) | `rag-mcp.service` (CHA-161) |
| Corpus refresh | rag-refresh | — (cron, 03:00 UTC) | `deploy/rag-refresh/rag-refresh-cron.sh` (CHA-1079/1082) |

All endpoints are **internal-LAN only** (Qdrant is localhost-bound; the GPU
endpoints are LAN-only — public exposure is deliberately absent, CHA-97 tracks
hardening the bind). Every endpoint is overridable via `RAG_*` env vars
(`RAG_CHAT_URL`, `RAG_EMBED_URL`, `RAG_QDRANT_URL`, `RAG_COLLECTION`,
`RAG_JUDGE_URL`, …); the defaults are the on-LAN values above.

## The package — one map

One installable package `rag_ops` under `src/`, one subpackage per concern, each
with its own README (read those for detail):

| Part | What it is |
|---|---|
| `core` | shared endpoint clients (`embed`, `chat`, pinned `judge`, timed streaming) + the `RAG_*` config. Everything imports this. |
| `ingestion` | build the corpus → secret-filter → chunk → embed → Qdrant. `corpus_sources.py` is the source registry; `refresh.py` (`rag-refresh`) the scheduled incremental refresh entrypoint (CHA-95/96), wrapping `build_corpus.py` (`rag-build-corpus`); `exporters.py` scripts the export sources. |
| `secret_filter` | the pre-embed denylist + its 0-leak test. |
| `cli` | the `rag-ask` command — hybrid retrieval → grounded cited answer. The single answer path. |
| `slackbot` | Slack (Socket Mode) interface; reuses the CLI answer path verbatim. |
| `eval` | 34-question retrieval + LLM-judged correctness harness (the regression check). |
| `benchmark` | cross-model latency benchmark with a pinned judge (CHA-107). |
| `deploy/` | systemd units + bring-up/restore scripts, split by host. |

Install / run from the deployed checkout's venv (console commands: `rag-ask`,
`rag-ingest`, `rag-refresh`, `rag-build-corpus`, `rag-export`, `rag-eval`,
`rag-slackbot`, `rag-bench`):

```bash
python3.12 -m venv venv && venv/bin/pip install -r requirements.txt && venv/bin/pip install -e .
docker compose up -d                                  # Qdrant
venv/bin/rag-ask "What do I do when WormholeNodeBlockHeightNotIncreasing fires on Polygon?"
```

## Corpus & Qdrant layout

One Qdrant collection, `chainlayer_rag`: 1024-dim cosine vectors + a full-text
index per chunk (so hybrid retrieval works). Each point's payload carries the
chunk text, a stable `uuid5` id, a content `sha`, and a `source` label. Chunk
IDs are content-stable; the `sha` is what lets the refresh skip unchanged chunks
(incremental re-embed, CHA-95).

**Raw source docs are never committed and never embedded raw** — they live under
the gitignored `corpus/` on the box (they can contain the very secrets the
filter drops); only filtered embeddings reach Qdrant.

Sources are declared in `ingestion/corpus_sources.py` — the single
version-controlled answer to "what is indexed?". Each `Source` has a `kind`
(`repo` = walked by the file ingester; `export` = materialized to markdown by a
scripted exporter, CHA-96; `slack` = workspace channels) and a `category`
(`prose` vs `iac` — the secret-safety class, see gate below). Current registry:

| Source | Kind | Category | Ingested? |
|---|---|---|---|
| `documentation` (`gitlab.com/chainlayer/documentation`) | repo | prose | yes — primary corpus (CHA-42) |
| `rag-ops-assistant` (this repo) | repo | prose | yes — self-docs, so it explains its own pipeline (CHA-100) |
| 26 prose inventory repos (CHA-142) | repo | prose | yes — no audit gate required |
| `k8s-apps` (pilot), `helm-charts`, `clusters`, `haproxy`, `monitoring2`, `proxmox-iac`, `gitlab-iac` | repo | iac | yes — all `enabled=True, audit="approved"` (CHA-120/124) |
| `chainlink-ops`, `chainlink-service-registry`, `chainlink-service-registry-sidecar`, `chainlink-topup` | repo | iac | yes — all `enabled=True, audit="approved"` (CHA-124) |
| 134 IaC inventory repos (CHA-142, batches 1–9) | repo | iac | yes — all `enabled=True, audit="approved"` (per-batch dry-run + Peter sign-off) |
| `incident-io`, `linear-ops-cll` (MAN excluded) | export | prose | yes — scripted exporters (CHA-96), refreshed with the rest |
| `slack` (`xnetwork-`/`xinfra-` channel auto-discovery) | slack | prose | yes — workspace channels (CHA-121) |

`claude-skills` and `multica-agents` are **deliberately excluded** (Peter's
personal repos, not company corpus) — do not add them without his say-so.

## Ingestion pipeline

`rag-refresh` (wrapping `build_corpus`) → for each ingestable source
(`repo`/`export`/`slack`): clone/checkout (or run the scripted exporter for
`export` sources) → walk files in scope (`include`/`exclude` globs) →
**secret-filter every doc** → chunk markdown on natural boundaries → embed
**incrementally** (CHA-95: chunks whose stored `sha` is unchanged are skipped,
deleted ones pruned) → upsert to Qdrant with dense vector + full-text. The
nightly timer also posts a per-source **digest of what changed to Slack `#rag-ops`**
on every run, and `--check-freshness` probes the recorded heartbeat (see Refresh
mechanism).

```bash
rag-refresh                       # incremental refresh of every ingestable source
rag-refresh --only <src>          # restrict to named sources (repeatable)
rag-refresh --dry-run             # scope + secret-filter only; still posts a digest
rag-refresh --no-slack            # run + print digest, do not post (local/debug)
rag-refresh --check-freshness     # exit non-zero if the last refresh is stale
rag-build-corpus                  # one-shot builder every ingestable source (full, no skip)
rag-build-corpus --plan           # show the resolved plan, build nothing
rag-build-corpus --only <src> --dry-run  # scope + filter only, embed nothing
rag-build-corpus --check          # CI gate: non-zero if an enabled IaC source is un-audited
rag-export incident-io --dest /tmp/inc --limit 5   # run one exporter by hand
rag-ingest <dir> --source <name> [--repo <url>] [--include <glob> ...]  # one tree
```

## Secret filter — the blocking gate (criterion 4)

The denylist applied to **every doc before it is embedded**. Goal: **0 secret
leaks** into the vector store. Fail-safe by design: a matching chunk is
**dropped whole, never redacted-and-kept**; drops are counted and logged by
source + chunk-id — **the secret value is never logged or stored**. Code:
`secret_filter/secret_filter.py`; the 0-leak test (`test_secret_filter.py`,
`python -m rag_ops.secret_filter.test_secret_filter`) must stay green — it's the
post-deploy verification and a natural CI gate.

Three layers:
- **Layer 1 — path globs:** a matching file is never read (`*.tfstate`,
  `*secret*.y*ml`, `.env*`, `id_ed25519`/`*.pem`/`*.key`, `*.kubeconfig`,
  `.pgpass`, vault/bitwarden exports, …) plus build noise.
- **Layer 1b — content markers:** files whose *content* identifies them as a
  credential file regardless of name (GCP SA-key JSON, `BEGIN … PRIVATE KEY`,
  `$ANSIBLE_VAULT;`, raw `kind: Secret`).
- **Layer 2 — per-chunk content regex:** any match drops the chunk. Deterministic
  token shapes (AWS/GitHub/GitLab/Slack tokens, JWT, `Authorization: Bearer`, DB
  URIs with creds, the ChainLayer-specific QuickNode token, a generic
  `secret-ish key = long value`), **plus an entropy backstop**.

**The deterministic patterns carry the 0-leak guarantee; the entropy backstop**
(env-gated `RAG_ENTROPY_SCAN`, **ON** by default since CHA-93) is the only guard
against a *novel* secret format matching none of them. It used to false-fire on
public, high-entropy-but-non-secret blockchain strings (validator/libp2p peer
ids, bech32 addresses, EVM hashes, long URL/path/doc slugs), so a **positive
chain-identifier allowlist** + URL/path-aware tokenisation now clears those
(0 false positives verified on the live corpus). The allowlist only ever clears
*recognised public shapes* — a genuinely random high-entropy blob still trips.
Residual known gap: a base64url secret with dense `-`/`_` glued inside a raw URL
path (CHA-98).

### IaC audit gate — MANDATORY before enabling any `iac` source

The filter is **proven on prose** (docs/incident/Linear) but only **designed**
for IaC/config. So a `category = "iac"` source is **not ingestable** until a
human approves its audit — `ingestable` is `False` and the builder refuses while
`audit != "approved"`. To onboard one (per CHA-120 / CHA-114):

1. **Dry-run audit (embeds nothing):** `rag-ingest <checkout> --source <name> --dry-run`
   → prints the drop log by reason + a sample of what *survived* the filter.
2. **Human (Peter) reviews** both the drop reasons and the survivor sample.
3. Set `audit = "approved"` and `enabled = True` for that **one** source in
   `corpus_sources.py`, then ship.

**Staged rollout, one source at a time:** `k8s-apps` is the approved pilot; roll
the rest out only after the filter holds on it. `rag-build-corpus --check` is the
CI gate (non-zero if any enabled IaC source is un-audited) and the builder makes
the same check before ingesting — a mis-gated repo can never slip through. 🛑
**Never flip an `iac` source to `enabled=True` without the dry-run audit +
Peter's explicit approval.**

> Self-doc nuance (CHA-100): the two detector files (`secret_filter.py` + its
> test) are dense with regex patterns and benign fake fixtures that would trip
> Layer 1b, so the registry lists them under `allow_unfiltered_paths`. That
> exemption relaxes **only** the whole-file skip — **per-chunk Layer 2 still runs
> on every chunk**, so the fake-token fixtures are still dropped. Use this only
> for files confirmed secret-free.

## Retrieval, answers & citations

`cli/ask.py` is the **single answer path** (the Slack bot and eval both call it
verbatim, so every surface answers identically):

- **Hybrid retrieval:** dense vector search + lexical full-text, fused with
  Reciprocal Rank Fusion (RRF) — semantics catch paraphrase, lexical catches
  exact hostnames / error codes / flag names.
- **Grounded generation:** the chunks are stitched into the prompt; the answer
  cites sources inline as `[n]` with a `*Sources:*` footer, and **refuses** when
  the corpus doesn't contain the answer (no hallucination).

```bash
rag-ask "how do I ...?" [--k 6] [--show-chunks]
```

**Slack bot** (CHA-94): Socket Mode → Slack opens an *outbound* WebSocket to the
box, so there is **no inbound public ingress** (stays on-network like the CLI).
Responds to `/ops` and @mentions; long answers are split (never truncated).
Self-test without Slack: `python -m rag_ops.slackbot.slack_bot --selftest "q"`.

## Eval — the regression check (criterion 3 / 6)

Fixed 34-question set; `rag-eval` scores top-k retrieval hit-rate, `--judge` adds
LLM-judged answer-correctness (judge pinned, CHA-107). Targets: **≥80% top-5
hit-rate, ≥70% correctness** (baseline ran 97–100% / 85–91%). Run it as the
post-deploy no-regression gate; it exercises the same answer path the bot uses.
Caveat: the judge is the same model family that writes answers, so correctness
is a groundedness self-assessment, not a fully independent grade.

## Refresh mechanism — nightly, incremental (CHA-95/96)

Refresh is **automatic and incremental**. On `rag-refresh`, a **cron job** runs
nightly at **03:00 UTC** (`0 3 * * *` in Peter's crontab) executing
`deploy/rag-refresh/rag-refresh-cron.sh` (CHA-1079 step 2 / CHA-1082) from the
box venv — this replaced the old systemd `rag-refresh.timer` path (CHA-96). The
cron script retries **once** on a transient Git-over-SSH blip (self-resolves —
CHA-1062), owns the failure-alert path itself (no systemd `OnFailure=` backstop
in the daily path), and since CHA-1083 self-reports every run as a **Multica
issue** in the RAG project (per-source digest issue on success, failure issue
assigned to the RAG squad on error). Underneath it runs the same incremental
refresh:

```bash
python -m rag_ops.ingestion.refresh      # what the cron runs each night
```

It wraps `build_corpus` in the incremental re-embed (CHA-95): only added/changed
chunks are embedded and deleted ones pruned, so an unchanged corpus embeds 0
chunks. Every in-scope source is refreshed — the `export` sources (incident.io,
Linear OPS/CLL) are materialized by their scripted exporters first, then ingested
through the same secret filter as everything else. Each run posts a per-source
**digest of what changed to Slack `#rag-ops`** (on success) or a ⚠️ failure
alert + non-zero exit (on error) — the cron script owns this alert path now.
`rag-refresh --check-freshness` is an explicit staleness probe (non-zero if the
recorded heartbeat is too old).

**Manual refresh** (no need to wait for the cron — e.g. right after a meaningful
docs change):

```bash
bash deploy/rag-refresh/rag-refresh-cron.sh   # on rag-refresh, from the app dir
rag-refresh                                   # or run the command directly from the venv
```

> Note (awareness only, from the CHA-1062 manual run): the first manual refresh
> hit a **transient GitLab SSH auth blip** on one source's fetch — it
> self-resolved on retry and is **not systemic** (the cron script now retries
> once on exactly this).

## Deploy

Currently a **documented manual deploy** (systemd units already on the boxes; CI
is a follow-up). Full step-by-step is `deploy/README.md` — summary:

- **rag-refresh:** clone to `/home/peter/rag-ops-assistant`, build the
  venv, write the root-only `.slack.env` + `.export.env` from Bitwarden
  (**company** folder, via the **bitwarden** skill — never commit them; `*.env`
  is gitignored), `docker compose up -d` (Qdrant), install/repoint
  `rag-slack.service` **and** `rag-mcp.service` (units under
  `deploy/rag-refresh/`), wire the nightly refresh as the **cron** entrypoint
  (`deploy/rag-refresh/rag-refresh-cron.sh`, 03:00 UTC — this replaced the old
  `rag-refresh.service` + `rag-refresh.timer` + `rag-refresh-alert.service`
  systemd units), then verify: 0-leak test → a cited `rag-ask` → `rag-eval --judge`
  → `/ops` in Slack → a `rag_ask` round-trip against the MCP server (`:8041`).
- **gx10-f018:** `deploy/gx10-f018/gx-f018-deploy.sh` brings up chat (`:8801`) +
  embed (`:8802`); `gx-f018-restore-baseline.sh` restores the baseline RAG 30B
  after a benchmark candidate (CHA-117 — supersedes the old `teardown.sh`, which
  wrongly repointed prod chat). f018 only *serves models*; it doesn't run the
  package. 🔶 The f018 chat is a load-bearing shared service — restarts cause a
  brief bot outage; do them in an acceptable window.

## How to extend — common tasks

- **Add / rescope a corpus source:** edit `corpus_sources.py` (a config change,
  not code). Prose source → add it `enabled`. **IaC source → run the audit gate
  above first** (dry-run → Peter approves → `enabled=True, audit="approved"`).
- **Change the answer/retrieval behaviour:** edit `cli/ask.py` (one path — Slack
  + eval inherit it). Re-run `rag-eval --judge` to confirm no regression.
- **Add a secret pattern:** extend `CONTENT_PATTERNS` / globs in
  `secret_filter.py` and add a fixture to `test_secret_filter.py`; keep the
  0-leak test green.
- **Compare a candidate chat model:** `benchmark` part, judge pinned (CHA-107).
- All changes ship as a **git-pr** PR against `tyrion70/rag-ops-assistant`,
  Multica-issue-first, SSH-signed, no `Co-Authored-By`.

## Safety model

| | |
|---|---|
| ✅ | Run `rag-ask` / `rag-eval` / dry-run ingests; read Qdrant; edit code behind a PR. |
| 🔶 | `rag-refresh` / `rag-build-corpus` (touch the live index); restart `rag-slack.service` / `rag-mcp.service`; run `rag-refresh-cron.sh`; restart f018 chat/embed (shared, causes a bot blip). |
| 🛑 | Enable an `iac` source without the dry-run audit + Peter's approval; commit `corpus/`, `.slack.env`, or any token; expose an endpoint publicly; add a personal repo (`claude-skills`, `multica-agents`) to the corpus. |

## Provenance & related

CHA-42 (baseline PoC) → CHA-93 (chain-id allowlist + entropy backstop) → CHA-94
(Slack bot) → CHA-100 (self-documentation) → CHA-106 (productionize into the
repo) → CHA-107 (benchmark) → CHA-117 (f018 restore fix) → CHA-120 (company-repo
list + IaC gate, k8s-apps pilot) → CHA-95 (incremental re-embed) → CHA-96
(nightly `rag-refresh` service/timer) → CHA-161 (MCP server) → CHA-1079/1082
(refresh moved to cron) → 2026-08-21 move to `rag-refresh` (claude-readonly-01
decommissioned). Open: CHA-97 (network harden), CHA-98
(base64url-in-path backstop), CHA-88 (Drive→docs curation).

Sibling skills: **chainlayer-knowledge** (infra facts the corpus is *about*),
**ssh** (reach the boxes), **bitwarden** (Slack tokens, company folder),
**git-pr** (ship changes to the repo), **linear-company** (the OPS/CLL issues
that feed the corpus).
