---
name: cancer-game-evidence
description: "The Cancer Game project's scientific evidence base and integrity rules. Covers the shared data/evidence/ database (14 ECAC5 recommendations, ~25 IARC agents, WCRF matrix, global burden, the game_content_mapping spine, references), the canonical Drive xlsx → JSON export workflow, the file schemas, and how both products consume the science. Use whenever adding/editing a health claim, statistic, recommendation, scenario, or card fact, or reviewing content for scientific accuracy. The cardinal rule: every game fact must trace to a real sourced entry — never fabricate. Use cancer-game for the project map."
---

# Cancer Game — Evidence Base & Scientific Integrity

The Cancer Game project teaches cancer-prevention literacy, so its credibility
rests entirely on **every game fact tracing to real evidence**. This skill
covers the shared evidence database, where it comes from, its schema, and the
integrity rules both products must obey. For the project map read `cancer-game`.

## The cardinal rule
**No invented statistics. No "sounds-right" health claims. No paraphrase that
drifts from the source.** Every risk figure, dose-response, cancer-type list,
and recommendation in either product must trace to an entry in
`data/evidence/`. If you cannot find the supporting entry, you either add it
(sourced) or you do not make the claim. When unsure, cite the source or ask
Peter — never fabricate. This is the single most important rule in the project.

## The shared evidence database
Single source of truth: **`data/evidence/`** in the repo. Both `play-it-safe`
and `companion-app` consume from here. Read `data/evidence/SOURCE.md` first — it
is the authoritative provenance + schema doc and lists every file.

**Canonical original is a Drive xlsx**, not the JSON:
- `https://drive.google.com/file/d/1N5rjfERnKQ4LurBdNFYA47DDz2Xq-zUd/view`
  (owner: peter@chainlayer.io). A working copy also sits at
  `projects/play-it-safe/source/Cancer_Prevention_Evidence_Database.xlsx`.
- **Workflow: edit the xlsx, then re-export to JSON** in `data/evidence/`. The
  JSON is a derived mirror — do not hand-edit JSON and let it drift from the
  xlsx. `evidence_raw.txt` (verbatim xlsx text extraction) exists for
  drift-detection; use it to check the JSON still matches the source.

## What's in `data/evidence/`
| File | Contents |
|------|----------|
| `SOURCE.md` | Provenance + schema notes (read first) |
| `ecac5_recommendations.json` | The **14 ECAC5** (European Code Against Cancer, 5th ed.) recommendations |
| `iarc_agents.json` | ~25 IARC-classified risk factors (Group 1 / 2A / 2B …) |
| `wcrf_evidence_matrix.json` | WCRF-AICR diet/lifestyle evidence rows |
| `global_burden.json` | Population-attributable fractions per risk-factor category |
| `game_content_mapping.json` | **The spine the games consume**: 29 life-stage scenarios → ECAC5 → IARC → per-choice token effects |
| `references.json` | Bibliography with URLs / DOIs |

`game_content_mapping.json` is the bridge between science and gameplay — when a
card or a companion life-event needs a fact, it resolves through this mapping so
the chain `choice → token effect → ECAC5 rec → IARC evidence → source` stays
intact end to end.

## Schema highlights
`ecac5_recommendations.json` entries carry: `rec` (1–14), `topic`, `text` (the
recommendation), `changed_from_ecac4`, `evidence` (the dose-response / key
finding), `cancer_types[]`, `risk_reduction`, and `game_cards[]` (which game
content uses it). `iarc_agents.json` entries carry `agent`, `iarc_group`,
`cancer_types[]`, `exposure_route`, `life_stages[]`, `attributable_fraction`,
`evidence`, `ecac5_rec`, `game_mechanic`, and `source`. Full schemas are in
`SOURCE.md` — read it before editing any evidence file.

## How the products consume it
- **Companion app** ships a trimmed copy under `poc/src/data/` —
  `ecac5.json` (14 recs with evidence) and `scenarios.json` (29 life-stage
  scenarios). These are derived from `data/evidence/`; keep them consistent with
  the canonical DB, and surface the science gently (adolescent-appropriate daily
  notes, life-event evidence reveals) — never as a quiz.
- **Play It Safe** cards reference ECAC5 / IARC through `game_content_mapping.json`;
  every card's `scienceFact` must resolve to a real entry.

## When you touch evidence
1. Edit the **xlsx** (canonical), then re-export the affected JSON.
2. Confirm `evidence_raw.txt` and the JSON agree (no drift).
3. If a downstream product copy (`poc/src/data/`) is affected, update it too.
4. Cite the source in `references.json`; never introduce an unsourced claim.
5. Changes ship via the `git-pr` workflow.

ECAC5 = European Code Against Cancer, 5th edition (14 recommendations). IARC =
International Agency for Research on Cancer (carcinogen classification). WCRF-AICR
= World Cancer Research Fund / American Institute for Cancer Research (diet &
lifestyle evidence).
