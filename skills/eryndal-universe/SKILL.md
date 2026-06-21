---
name: eryndal-universe
description: "Cross-cutting orientation for the Eryndal transmedia universe (Valdris / The Pale Road): the seven product pillars (book, audiobook, card game, art, social, RPG, digital games), where everything lives in the github.com/tyrion70/eryndal repo, canon authority, the GX10 generation cluster, and how to clone the repo over SSH (multica repo checkout does NOT work for it). Read this first when starting any Eryndal task to know who owns what and where to look; use eryndal-lore for the story world and eryndal-writer for prose craft."
---

# Eryndal Universe — Project Map

Cross-cutting orientation for any work on **Eryndal**, a transmedia fantasy
universe set on the continent of **Valdris** in the **Broken Age** (73 years after
the Waking). One world bible feeds seven product pillars. This skill tells you
WHERE everything lives, WHO owns canon, and HOW to get the repo. For the *story
world itself* read the `eryndal-lore` skill; for prose craft read `eryndal-writer`.

## The repo is the source of truth
Everything lives in the private repo **github.com/tyrion70/eryndal**.

- `multica repo checkout` does NOT work for this repo on this deployment (no GitHub
  App configured). Clone over SSH instead — the host has Peter's keys; see the
  `ssh` skill for which key authenticates to github.com/tyrion70:

      git clone git@github.com:tyrion70/eryndal.git

- Read the repo's own `CLAUDE.md` first every time — it carries the authoritative
  directory layout, naming conventions, and current status, which change as the
  project moves. The summary below orients you; the repo wins on any conflict.
- Repo changes follow the `git-pr` workflow (Multica-issue-first, SSH-signed
  commits, PR linked back to the issue).

## The seven pillars
Roadmap and phasing: `docs/UNIVERSE_EXPANSION_PLAN.md`. Live status / what's next:
`docs/SESSION_NEXT_STEPS.md`.

1. **Book** — *The Pale Road* (Book One). 29 chapters (~42.8k words), final;
   EPUB (text + illustrated) and print PDF built. Future books: *The Locked
   Archive*, *The Permission*. → `eryndal-writer` (prose), `eryndal-lore` (canon).
2. **Audiobook** — full multicast, all 29 chapters generated on the GX10 cluster.
   → `eryndal-audiobook`.
3. **Card game** — *Echoes of the Source*, a 2-player TCG. Design complete; card
   *template* design is the open work. → `eryndal-cardgame`.
4. **Art** — definitive artwork in `Images/` (Flux Dev via ComfyUI on GX10, Dall-E
   for maps). → `eryndal-artist`.
5. **Social** — @eryndal.online on Instagram, daily posts, automated pipeline. →
   `eryndal-social`.
6. **Tabletop RPG** — planned (5e-compatible setting guide first). No skill yet.
7. **Digital games** — planned (narrative RPG in Ink → tactical RPG). No skill yet.

## Where things live (repo)
| Need | Path |
|------|------|
| Project rules + layout | `CLAUDE.md`, `.claude/KNOWLEDGE.md` |
| World Bible (6 vols) | `Bible/Eryndal_World_Bible_Vol*.md` |
| Book One chapters | `Book_1_The_Pale_Road/Chapter_NN_Title/` |
| Book One outline | `Book_1_The_Pale_Road/Eryndal_Book1_Outline_ThePaleRoad.md` |
| Chapter status | `progress.md` |
| Continuity tracker (source of truth) | `continuity/tracker.md` |
| Reviews | `reviews/` |
| Card game design | `docs/CARD_GAME_DESIGN.md` |
| Audiobook pipeline | `docs/TTS_PIPELINE_SUMMARY.md`, `narration/` |
| Instagram content | `reels/` (+ `reels/post_log.md`) |
| Generation scripts | `scripts/` (EPUB, image gen, TTS, Instagram) |
| Definitive art | `Images/`  (non-final tryouts in `Images_archive/`) |

## Naming conventions (enforced)
Underscores never spaces. Chapter folders `Chapter_NN_Title`; drafts
`Eryndal_Book1_ChapterNN_RevN.md`; reviews `reviews/review_NN.md`; continuity
`continuity/continuity_after_NN.md`.

## Canon authority
The World Bible + `continuity/tracker.md` are canon. Never invent lore from memory
— read the Bible or ask. New canon decisions are made by the human (Peter) or the
Loremaster role, then written back to the Bible/tracker. **Generate once, use
everywhere:** a character portrait or a lore fact serves the book, audiobook, card
game, RPG, and social at once — keep the shared assets consistent.

## Infrastructure: the GX10 cluster
Image gen (ComfyUI + Flux Dev bf16) and the TTS audiobook pipeline (Chatterbox
Original + Kokoro refs) run locally on the ASUS Ascent GX10 (GB10 Grace Blackwell,
128GB unified, `192.168.19.80`). vLLM and ComfyUI contend for the GPU — stop one
before starting the other (`systemctl stop vllm` before ComfyUI; restart after).
Reach it over SSH (`ssh` skill). Details: `docs/TTS_PIPELINE_SUMMARY.md` and the
Image Generation section of `docs/SESSION_NEXT_STEPS.md`.
