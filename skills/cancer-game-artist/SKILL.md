---
name: cancer-game-artist
description: "Generate and review artwork for the Cancer Game project — Play It Safe board/card/hero art and Companion App painterly avatars, wellbeing states, habitats, mockups, and stakeholder packs. Covers the two generators (Flux Dev via ComfyUI on the GX10 192.168.19.80, and OpenAI gpt-image-2), the GX10 vLLM/ComfyUI GPU-contention caveat, the two distinct visual styles (flat illustration vs painterly creatures), PIL mockup compositing, output locations, and the hard rules (no readable text in generated art, no photorealism, avatars stay on-model, generate deliberately — gpt-image-2 costs money). Use whenever generating, reviewing, or fixing images for either product. Use cancer-game for the project map."
---

# Cancer Game — Art & Asset Generation

Both Cancer Game products are visual: **Play It Safe** needs board + card + hero
art; the **Companion App** needs painterly avatars, wellbeing states, habitats,
and mockups. This skill covers the generation tooling, the two distinct visual
styles, the compositing pipeline, and the hard rules. For the project map read
`cancer-game`; for the deployed app read `cancer-game-companion`.

## The two generators
Both are adapted from the Eryndal art pipeline and share the same infra.

1. **Flux Dev via ComfyUI on the GX10** — `scripts/generate_one.py`.
   - ComfyUI runs on the **GX10 box at `192.168.19.80:8188`**. Reach it over SSH
     (see the `ssh` skill).
   - **The GPU is shared with vLLM — stop vLLM before starting ComfyUI** and
     restart it after:
     ```
     ssh root@192.168.19.80 'systemctl stop vllm && source /root/ComfyUI/venv/bin/activate && cd /root/ComfyUI && python main.py --listen 0.0.0.0 --port 8188'
     ```
   - Usage: `./scripts/generate_one.py [--size card] [--style none] [--steps N]
     [--guidance G] [-o name.png] [--prefix P] "prompt"`. The script prepends a
     project style preamble unless `--style none`.

2. **OpenAI gpt-image-2** — `scripts/generate_oai.py` (project-agnostic single-shot;
     pass `--prompt`/`--prompt-file` + `--output` + `--size`/`--quality`).
     Supports `--reference` for image-to-image edits. API key from the repo `.env`
     (or env) — pull from `bitwarden`, never hardcode. The 42-PNG avatar set cost
     ~$25 in gpt-image-2 spend, so generate deliberately.

Project-specific prompt collections live under `projects/<name>/scripts/`
(e.g. `companion-app/scripts/avatar_prompts.py`,
`play-it-safe/scripts/generate_board.py` / `generate_cards.py` / `render_card.py`).

## Two visual styles — keep them separate
- **Play It Safe (board game)**: warm modern **flat illustration** — soft natural
  lighting, gentle gradients, rounded shapes, friendly diverse characters in
  everyday positive scenarios, slightly desaturated matte colours; "Ticket to
  Ride / Pandemic" warmth, ages 12+. The full palette (per-life-stage colours,
  token colours, neutrals), typography (Nunito display, Source Sans 3 body), and
  layout rules are in `projects/play-it-safe/design/style-guide.md` — follow it.
- **Companion App**: **painterly plant-elemental creatures** (Mossy, Succulent,
  Mushroom, Fern, Berry, Dandelion). Each has a full **6-state wellbeing range**
  plus a **mature variant** (42 PNGs total). Soft, warm, gentle — the art carries
  the calm, non-alarmist tone the app depends on.

## Compositing (mockups & stakeholder packs)
Final mockups are **PIL composites** of generated assets — text is drawn
programmatically so it stays crisp and readable (generated art itself has NO
text — see below). Shared drawing primitives:
`projects/companion-app/scripts/_mockup_helpers.py`. The `build_*.py` scripts
compose avatar grids, wellbeing strips, compound-moment flows, daily-fact cards,
seasonal strips, app mockups, and the **stakeholder pack** (latest:
`build_stakeholder_pack_v5.py` → `output/stakeholder_pack_v5.pdf` + `.png`, the
shareable artifact for funders / co-design). Board + card composition lives in
`play-it-safe/scripts/`.

## Hard rules (anti-patterns)
- **No readable text in generated images.** No legible lettering, no words
  anywhere — Flux/gpt-image garble text. All real copy is composited in later
  with PIL. The Play It Safe style preamble already forbids text; keep it.
- **No photorealism, no harsh angles, no dark/moody atmosphere** for Play It Safe
  — it must stay warm, optimistic, age-appropriate (12+).
- **Companion avatars stay on-model**: a creature's identity (species, palette,
  silhouette) is consistent across all 6 wellbeing states and its mature variant.
  Regenerate against the existing set, don't drift.
- **Generate deliberately.** gpt-image-2 costs real money per image; Flux ties up
  the shared GPU. Know the prompt and output path before you fire.

## Where outputs go
- `projects/play-it-safe/output/` — `board/` (+ `variants/`, `type_icons/`),
  `cards/` (+ `samples/`, `sample_art/`), `hero/`.
- `projects/companion-app/output/` — `avatars/`, `avatars-mature/`,
  `wellbeing-states/`, `habitat/`, `app-mockup/`, `tamagotchi-mockups/`,
  `evidence-mockups/`, `branding/`, `character-directions/`, `influences/`.
- POC-served avatars live in `poc/public/avatars/<id>/<state>.png`; the helper
  `companion-app/scripts/copy_states_to_poc.sh` copies generated states into the
  app. Browse any output over HTTP with `scripts/serve.sh` (LAN + Tailscale).

## Workflow
Asset/script changes ship via the `git-pr` workflow. When art illustrates a
specific cancer-prevention scenario, keep it faithful to the evidence it depicts
(see `cancer-game-evidence`) — the imagery teaches too.
