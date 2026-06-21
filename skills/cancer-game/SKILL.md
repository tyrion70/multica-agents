---
name: cancer-game
description: "Cross-cutting orientation for the Cancer Game project (github.com/tyrion70/cancer-game): two concept-stage products teaching cancer-prevention literacy through play — Play It Safe (60-tile board game) and the live Companion App (Tamagotchi-style mobile concept at playitsafe.app) — sharing one ECAC5/IARC evidence base. Read this first on any Cancer Game task to know what the products are, where everything lives in the repo, the non-negotiables (every game fact traces to evidence; age-appropriate tone), and how to clone over SSH (multica repo checkout does NOT work). Use cancer-game-evidence for the science, cancer-game-companion for the deployed app, cancer-game-artist for image generation."
---

# Cancer Game — Project Map

Cross-cutting orientation for any work on the **Cancer Game** project: two
parallel concept-stage products that teach **cancer-prevention literacy through
play**, sharing one evidence base. This skill tells you WHERE everything lives,
WHAT the two products are, and HOW to get the repo. For the science layer read
`cancer-game-evidence`; for the deployed app read `cancer-game-companion`; for
image/asset generation read `cancer-game-artist`.

## The repo is the source of truth
Everything lives in the private repo **github.com/tyrion70/cancer-game**.

- `multica repo checkout` does NOT work for this repo on this deployment (no
  GitHub App configured — it fails on HTTPS auth). Clone over SSH instead; the
  host has Peter's keys. See the `ssh` skill for which key authenticates to
  github.com/tyrion70:

      git clone git@github.com:tyrion70/cancer-game.git

- Read the repo's own `README.md` first every time — it carries the
  authoritative layout and current status, which move as the project does. The
  summary below orients you; the repo wins on any conflict.
- Repo changes follow the `git-pr` workflow (Multica-issue-first, SSH-signed
  commits, PR linked back to the issue).

## The two products (one evidence base)
1. **Play It Safe** — a physical **60-tile life-stages board game** with decision,
   event, myth, delayed-consequence, and milestone cards. Every card's
   `scienceFact` traces to ECAC5 / IARC evidence. Visuals largely complete;
   concept-stage. → `cancer-game-artist` for art, `cancer-game-evidence` for the
   science. Source docs (rules, prototype, funding/concept notes) in
   `projects/play-it-safe/source/`.
2. **Companion App** — a **Tamagotchi-style mobile concept** for adolescents
   (12–16): adopt a painterly plant-elemental creature whose wellbeing reflects
   daily cancer-prevention choices. **Closed-alpha is live at
   [playitsafe.app](https://playitsafe.app)** (Vite + React + Cloudflare Pages).
   → `cancer-game-companion` for the build/deploy, `cancer-game-artist` for the
   avatars/mockups.

## Where things live (repo)
| Need | Path |
|------|------|
| Project overview + status | `README.md` |
| **Shared evidence DB** | `data/evidence/` (`SOURCE.md` = schema + provenance) |
| Board game source (rules, notes, prototype) | `projects/play-it-safe/source/` |
| Board game style guide | `projects/play-it-safe/design/style-guide.md` |
| Board/card generators | `projects/play-it-safe/scripts/` |
| Board/card/hero renders | `projects/play-it-safe/output/` |
| Companion design docs (read in order) | `projects/companion-app/design/` + `brief/` |
| **Companion app POC (deployed)** | `projects/companion-app/poc/` |
| Companion avatar/mockup composers | `projects/companion-app/scripts/` |
| Companion renders, mockups, stakeholder packs | `projects/companion-app/output/` |
| Cross-project image-gen tooling | `scripts/` (`generate_one.py`, `generate_oai.py`, `serve.sh`) |

## Read the companion design docs in order
1. `companion-app/brief/visual-brief.md` — original brief
2. `companion-app/design/companion-mechanics.md` — the tamagotchi loop
3. `companion-app/design/care-evidence-map.md` — each daily action → a 2nd ECAC5 rec
4. `companion-app/design/care-visits-cadence.md` — calendar-driven visits
5. `companion-app/design/poc-plan.md` — build-out roadmap
6. `companion-app/design/engagement-runway.md` — honest long-term-retention read
7. `companion-app/design/playtest-protocol.md` — runnable 45–60 min co-design session

## Non-negotiables (the whole project rests on these)
- **Every game fact traces to evidence.** No invented statistics, no
  "sounds-right" health claims. The shared `data/evidence/` DB is the single
  source of truth; the canonical original is a Drive xlsx (see
  `cancer-game-evidence`). When in doubt, cite or ask — never fabricate.
- **Age-appropriate, non-alarmist tone.** The companion app targets 12–16-year-olds;
  prevention is framed as gentle daily care, not a fear-driven quiz.
- **No readable text in generated art** (see `cancer-game-artist`).

## Infrastructure
- **Image generation** runs on the **GX10 cluster** (ComfyUI + Flux Dev,
  `192.168.19.80:8188`) or OpenAI **gpt-image-2** — shared with Eryndal; the
  scripts here are adapted from it. Details + the vLLM/ComfyUI GPU-contention
  caveat: `cancer-game-artist`.
- **Companion app** auto-deploys to Cloudflare Pages on push to `main`. Details:
  `cancer-game-companion`.
- **Browse output/** from any device: `scripts/serve.sh` (static HTTP on
  `0.0.0.0:8001`, reachable on LAN + Tailscale).

This is Peter's personal project (`peter@chainlayer.io`). Background and key
decisions across all of Peter's private projects live in `private-knowledge`.
