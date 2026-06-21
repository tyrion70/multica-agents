---
name: eryndal-artist
description: "Generate and review artwork for Eryndal — book art, portraits, locations, creatures, maps, card art, social assets — using Flux Dev via ComfyUI on the GX10 (Dall-E for maps). Covers the global oil-painting style, the non-negotiable character anchors, the anti-pattern rules (no readable text, no anachronisms, maps without figures), the mandatory review loop, and prompt templates. Use whenever generating images, reviewing generated images, fixing art, or deciding visual style for Eryndal."
---

# Eryndal Artist

Generate and review artwork for the **Eryndal** universe — book art, character
portraits, location and creature pieces, maps, card art, and social assets. Use
whenever generating images, reviewing generated images, fixing art, or deciding
visual style for Eryndal. Keep every depiction consistent with `eryndal-lore` and
the World Bible. Art Prompt Library: `Bible/Eryndal_World_Bible_Vol6_ArtPrompts.md`.
Definitive art lives in `Images/`; non-final tryouts in `Images_archive/`.

## Generation backends (current)
- **Flux Dev bf16 via ComfyUI on the GX10** — primary, for portrait/scene quality.
  ComfyUI at `/root/ComfyUI/`; ~25s/image at 768×1024, 25 steps. Start it with
  `systemctl stop vllm` first, then `source /root/ComfyUI/venv/bin/activate && cd
  /root/ComfyUI && python main.py --listen 0.0.0.0 --port 8188`; `systemctl start
  vllm` after. Reach the GX10 over SSH (`ssh` skill).
- **Dall-E** — for **maps** (legible labels — ComfyUI/Flux garbles text) and quick
  Instagram iterations.
- The repo's `.claude/skills/eryndal-artist` is the project-local source of truth;
  reconcile with it if it has diverged.

## Global style preamble (prepend to character/scene/landscape prompts)
> A realistic oil painting with soft natural daylight, gentle shadows, and a
> brighter, more luminous palette. Skin tones warm and lifelike with subtle
> highlights, in the style of Sargent or Vermeer. Background softly lit and
> neutral, with visible but refined brushstrokes and a clean painterly texture.

## Character anchors (NON-NEGOTIABLE — include for every named character)
- **Aldric Crane** — human male, 34; strong jaw, dark hair, short stubble; deep
  blue linen coat over cream shirt, leather belt, sword at left hip; military
  bearing, civilian clothes (NO uniform/insignia); broad shoulders.
- **Tam Ashwell (Drev)** — small, thin, wiry, ~4.5ft (NOT stocky/round); round face,
  **round ears**, curly auburn-brown hair to jawline; colourful mismatched layers
  (patchwork vest in reds/golds, saffron shirt, violet neckerchief, emerald cloak);
  ~67 but looks ~50, smile lines, warm hazel eyes, thin cook's hands. **NOT an elf,
  NOT a child, NO pointed ears.**
- **Halric Keln** — dwarf male, 31, stocky, a head shorter than humans; braided
  red-brown beard with gold/copper clasps; ochre leather jerkin over dark green
  wool, mason's hammer at belt; muscular forearms, stone dust on hands.
- **Seris** — Silven elf female, looks late-20s despite ~180 (ageless, NO wrinkles);
  tall, lean, silver-streaked dark hair past shoulders; deep teal robe with silver
  embroidery, grey silk scarf, leather satchel; luminous grey-green eyes, pointed
  ears. **Must look YOUNG.**
- **Dara** — human female, 24 but looks ~20, fresh-faced; auburn hair in a practical
  braid, freckles; burgundy leather vest over faded blue linen, utility belt, bone-
  handled salvage knife; direct, confident.

Size relationships matter: Tam is noticeably smaller, Halric shorter but broader,
Seris tallest. In group scenes describe each named character specifically.

## Anti-patterns (NEVER)
- **No readable text/lettering anywhere** — AI text is the #1 tell. Add "No readable
  text, no legible lettering, no words visible." Maps: abstract calligraphic squiggles
  + colour coding, never words. Documents: dense marks suggesting script.
- **Maps are the map itself** — no hands, figures, or people holding it. "The map
  fills the entire frame… scanned parchment look."
- **No anachronisms** — no asphalt/concrete/modern materials/electric light/glass in
  poor buildings. Roads are dirt, cobblestone, or fitted stone.
- **Character consistency** — every named character carries their full anchor.

## The review loop (after EVERY image)
Check, in order: (1) text/lettering present? → REJECT; (2) each named character
matches anchor? → REJECT on wrong hair/build/clothing; (3) anachronisms? → REJECT;
(4) maps: person/hands in frame? → REJECT; (5) composition/focal point; (6) style
(Sargent/Vermeer oil — not photographic, not cartoony). Tiers: PASS / ACCEPTABLE
(minor) / REJECT. On REJECT: name the failure, add explicit counter-instructions,
regenerate; **max 3 attempts**, then flag for human review. Log filename + status +
notes.

## Prompt templates
- **Character/scene:** style preamble + scene + anchor(s) + "No readable text, no
  legible lettering. Medieval fantasy, no modern materials."
- **Map:** "Hand-drawn antique fantasy map, ink on aged parchment with watercolour
  wash. " + geography + "The map fills the entire frame. No people, no hands. No
  readable text — abstract calligraphic marks and colour coding instead of words.
  Scanned parchment look."
- **Landscape:** style preamble + scene + "No legible signage. Medieval fantasy, no
  asphalt — dirt, cobblestone, or fitted stone only."
- **Document/object:** style preamble + object + "Any writing as dense abstract
  marks suggesting script, not readable words."

## Generate once, use everywhere
A portrait or location piece feeds the book, card game, RPG, and social at once.
Generate definitive art into `Images/<category>/`; keep tryouts out of `Images/`.
For card art follow `eryndal-cardgame`; for social sizing follow `eryndal-social`.
