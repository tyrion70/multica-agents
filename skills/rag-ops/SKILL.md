---
name: rag-ops
description: Operate and extend ChainLayer's in-house RAG ops assistant — the on-network Q&A bot over internal docs, runbooks, incidents, and Linear, served from its own chat model + embedder + Qdrant (no third-party inference). Use to add/rescope a corpus source, run or refresh ingestion, reason about the secret filter + its mandatory IaC audit gate, debug retrieval/citations, run the eval, or deploy the CLI/Slack bot. Code is github.com/tyrion70/rag-ops-assistant; it runs on claude-readonly-01 + gx10-f018. NOT the chainlayer-knowledge skill (that's infra facts) — this is the RAG system itself.
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
- **Runs on:** `claude-readonly-01` (192.168.16.22, the bot/ingest/Qdrant host)
  + `gx10-f018` (192.168.19.207, GPU serving the models). Reach both via the
  **ssh** skill (`claude-readonly-01` has a host alias; f018 is a root hop from
  it).
- **Tracking:** Multica project **RAG**, umbrella `CHA-42`. Follow-ups are
  per-issue (see Roadmap below).

## Topology — who serves what

| Component | Host | Endpoint | Service |
|---|---|---|---|
| Chat LLM | gx10-f018 GPU | `:8801/v1` `Qwen3-30B-A3B-Instruct` | `rag-chat.service` (systemd) |
| Embeddings | gx10-f018 GPU | `:8802/v1` `Qwen3-Embedding-0.6B` (1024-dim) | `rag-embed.service` (systemd) |
| Vector store | claude-readonly-01 | `127.0.0.1:6333` Qdrant v1.18.2 | docker compose |
| Ingester / CLI / bot | claude-readonly-01 | — / outbound WS | `venv` + `rag_ops` pkg; `rag-slack.service` |

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
| `ingestion` | build the corpus → secret-filter → chunk → embed → Qdrant. `corpus_sources.py` is the source registry; `build_corpus.py` (`rag-build-corpus`) the refresh entrypoint. |
| `secret_filter` | the pre-embed denylist + its 0-leak test. |
| `cli` | the `rag-ask` command — hybrid retrieval → grounded cited answer. The single answer path. |
| `slackbot` | Slack (Socket Mode) interface; reuses the CLI answer path verbatim. |
| `eval` | 34-question retrieval + LLM-judged correctness harness (the regression check). |
| `benchmark` | cross-model latency benchmark with a pinned judge (CHA-107). |
| `deploy/` | systemd units + bring-up/restore scripts, split by host. |

Install / run from the deployed checkout's venv (console commands: `rag-ask`,
`rag-ingest`, `rag-build-corpus`, `rag-eval`, `rag-slackbot`, `rag-bench`):

```bash
python3.12 -m venv venv && venv/bin/pip install -r requirements.txt && venv/bin/pip install -e .
docker compose up -d                                  # Qdrant
venv/bin/rag-ask "What do I do when WormholeNodeBlockHeightNotIncreasing fires on Polygon?"
```

## Corpus & Qdrant layout

One Qdrant collection, `chainlayer_rag`: 1024-dim cosine vectors + a full-text
index per chunk (so hybrid retrieval works). Each point's payload carries the
chunk text, a stable `uuid5` id, a content `sha`, and a `source` label. Chunk
IDs are content-stable; a `sha` is stored per chunk (the hook for incremental
re-embed, CHA-95).

**Raw source docs are never committed and never embedded raw** — they live under
the gitignored `corpus/` on the box (they can contain the very secrets the
filter drops); only filtered embeddings reach Qdrant.

Sources are declared in `ingestion/corpus_sources.py` — the single
version-controlled answer to "what is indexed?". Each `Source` has a `kind`
(`repo` = walked by the file ingester; `manual` = external MCP export, listed
but not yet scripted) and a `category` (`prose` vs `iac` — the secret-safety
class, see gate below). Current registry:

| Source | Kind | Category | Ingested? |
|---|---|---|---|
| `documentation` (`gitlab.com/chainlayer/documentation`) | repo | prose | yes — primary corpus (CHA-42) |
| `rag-ops-assistant` (this repo) | repo | prose | yes — self-docs, so it explains its own pipeline (CHA-100) |
| `k8s-apps` | repo | iac | **yes — pilot, audit approved** (CHA-120) |
| `helm-charts`, `clusters`, `haproxy`, `monitoring2`, `proxmox-iac` | repo | iac | no — `enabled=False`, `audit=pending` (gated) |
| `incident-io`, `linear-ops-cll` (MAN excluded) | manual | prose | yes, but via a **manual** MCP-export step (not scripted) |

`claude-skills` and `multica-agents` are **deliberately excluded** (Peter's
personal repos, not company corpus) — do not add them without his say-so.

## Ingestion pipeline

`build_corpus` → for each ingestable `repo` source: clone/checkout → walk files
in scope (`include`/`exclude` globs) → **secret-filter every doc** → chunk
markdown on natural boundaries → embed → upsert to Qdrant with dense vector +
full-text. Today every refresh re-embeds the full source (incremental is the
CHA-95 follow-up).

```bash
rag-build-corpus                       # refresh every ingestable source
rag-build-corpus --plan                # show the resolved plan, build nothing
rag-build-corpus --only <src> --dry-run  # scope + filter only, embed nothing
rag-build-corpus --check               # CI gate: non-zero if an enabled IaC source is un-audited
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

## Refresh mechanism — current state + follow-ups

Refresh today is a **manual one-shot**: re-run `rag-build-corpus` from the box
venv; it re-ingests every `repo` source full (no skip), secret-filtered. The
`manual` sources (incident.io, Linear OPS/CLL) are still a hand-run MCP-export
step, logged-and-skipped by the builder. Two tracked follow-ups make refresh
cheap + automatic:

- **CHA-95 — incremental re-embed:** skip chunks whose stored `sha` is unchanged
  (the `sha` is already in the payload); an unchanged corpus should embed 0
  chunks. Prerequisite for cheap scheduling.
- **CHA-96 — scheduled refresh:** a systemd timer / cron re-ingesting all sources
  on cadence (nightly docs/incidents/Linear, weekly repos), incrementally, with
  the secret filter on every run, counts logged, and an alert on miss/failure.
  Depends on CHA-95 landing first.

Until those land: **a stale index is the failure mode** — re-run `rag-build-corpus`
after a meaningful docs change.

## Deploy

Currently a **documented manual deploy** (systemd units already on the boxes; CI
is a follow-up). Full step-by-step is `deploy/README.md` — summary:

- **claude-readonly-01:** clone to `/home/peter/rag-ops-assistant`, build the
  venv, write the root-only `.slack.env` from Bitwarden (**company** folder, via
  the **bitwarden** skill — never commit it; `*.env` is gitignored),
  `docker compose up -d` (Qdrant), install/repoint `rag-slack.service`, then
  verify: 0-leak test → a cited `rag-ask` → `rag-eval --judge` → `/ops` in Slack.
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
| 🔶 | `rag-build-corpus` (re-embeds the live index); restart `rag-slack.service`; restart f018 chat/embed (shared, causes a bot blip). |
| 🛑 | Enable an `iac` source without the dry-run audit + Peter's approval; commit `corpus/`, `.slack.env`, or any token; expose an endpoint publicly; add a personal repo (`claude-skills`, `multica-agents`) to the corpus. |

## Provenance & related

CHA-42 (baseline PoC) → CHA-93 (chain-id allowlist + entropy backstop) → CHA-94
(Slack bot) → CHA-100 (self-documentation) → CHA-106 (productionize into the
repo) → CHA-107 (benchmark) → CHA-117 (f018 restore fix) → CHA-120 (company-repo
list + IaC gate, k8s-apps pilot). Open: CHA-95/96 (refresh), CHA-97 (network
harden), CHA-98 (base64url-in-path backstop), CHA-88 (Drive→docs curation).

Sibling skills: **chainlayer-knowledge** (infra facts the corpus is *about*),
**ssh** (reach the boxes), **bitwarden** (Slack tokens, company folder),
**git-pr** (ship changes to the repo), **linear-company** (the OPS/CLL issues
that feed the corpus).
