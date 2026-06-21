---
name: eryndal-cardgame
description: "Design reference for 'Eryndal: Echoes of the Source', the 2-player TCG set in the Broken Age. Covers the Source/Disturbance permission system (the core innovation), the four factions and their signature mechanics, card types and keywords, win conditions, rarity/booster/deck rules, set structure, and the open card-template work. Use when designing or balancing cards, writing card text/flavour, or building card templates and art. Full design doc: docs/CARD_GAME_DESIGN.md."
---

# Eryndal Card Game — Echoes of the Source

Design reference for **Eryndal: Echoes of the Source**, the 2-player collectible
trading card game set in the Broken Age. Use this when designing cards, balancing
factions, writing card text/flavour, or building card templates and art. The full
design doc is `docs/CARD_GAME_DESIGN.md` in the repo — it is authoritative; this
skill is the working summary. Keep all card flavour and naming consistent with the
`eryndal-lore` skill and the World Bible.

## The core innovation
Magic is not a resource you spend — it is a permission you borrow. Drawing power is
easy; drawing *too much* makes the world notice. The mechanics encode the series'
theme: the Source has moral consequences.

## The Source / Disturbance system (replaces mana/lands)
- Players play **Conduit** cards instead of lands. Each has a **Draw** value
  (Source energy) and a **Weight** (how much it disturbs the Sleeper).
- Each player has a **Disturbance Track (0–12)**. Tapping a Conduit adds its Weight.
  Thresholds: 0–3 Quiet (no effect) · 4–6 Stirring (draws cost +1) · 7–9 Tremors
  (reveal from the Consequence Deck at end of turn) · 10–11 Waking (your creatures
  −1/−1) · **12 The Reckoning (you lose)**.
- Disturbance **decays by 1 at the start of each turn** — push hard now vs. let it
  cool. The **Drev Hearthstone** (Weight −1) is the only Conduit that *reduces*
  Disturbance: weakest-looking, most strategically important — exactly the lore.

## Four factions (philosophies of using power)
| Faction | Colour | Playstyle | Signature mechanic |
|---------|--------|-----------|--------------------|
| **Hegemony of Arath** | blue-silver | control, removal, card draw; heavy Disturbance | **License** — deny opponent card types |
| **The Freeholds** | green-gold | alliance/synergy, weak alone, strong together | **Accord** — bonuses with 2+ races in play |
| **Undermount Clans** | rust-brown | defensive attrition, 0-Weight Ironspine Seams | **Stonewhisper** + **Accounting** (name & destroy) |
| **The Drev** | warm amber | subtle long game, thrives at Disturbance 0–2 | **The Underneath** — triggers at low Disturbance |

## Card types
Conduit (resource) · Creature (Cost / Power-Toughness / Race / Tradition /
abilities) · Tradition (spells: Resonance, Stonewhisper [pay life], Deep-Drawing
[+Disturbance, discard], Wound-craft [needs a Wound Site], Drev Connection) ·
Relic (persistent objects) · **Consequence** (shared ~20-card threat deck revealed
at Disturbance 7+: Nothing Stirs, Tremor, The Pale Approaches, Veth Visitation,
Mourne's Breath, Source Drought, Dreaming Plague, The Sleeper Stirs).

**Race matters** (Human / Silven / Undermount / Drev) for Accord, License, and
protection effects. **Tradition matters** for tradition synergies.

## Keywords
Attunement, Permission (−2 cost at Disturbance 0–2), Licensed, Exiled, Stoneblood
(lose life on Stonewhisper), Deep Draw (+Disturbance), Drev Quiet (untargetable by
Hegemony), The Wander, Accounting, Drift, Wound-touched.

## Win conditions
Standard: reduce opponent's life 20→0. Alternate **The Reckoning**: opponent hits
Disturbance 12. Alternate **The Accord Restored**: control creatures of all four
races at Disturbance 0 (near-impossible, deeply thematic — the Concord rebuilt).

## Rarity, boosters, decks
Common/Uncommon/Rare/Mythic Rare (the five protagonists, The Pale, Serevane's
Notes are Mythics). 15-card boosters (7C/3U/1R[1-in-8 Mythic]/2 Conduit/1
Consequence/1 token). Four preconstructed Starter Boxes. Deck rules: min 40 cards,
max 3 copies (basic Conduits unlimited), ≥15 Conduits, one primary + one secondary
faction, shared 20-card Consequence Deck.

## Set structure
Set 1 "Echoes of the Source" — 200 cards (80C/60U/40R/20M) + 20 Consequence. Future
sets tie to books: Set 2 "The Locked Archive" (Book 2), Set 3 "The Permission"
(Book 3, the Sleeper as a card).

## Open work (current priority)
Card **template** design — proper multi-layer frames at TCG dimensions (63×88mm),
four faction frame textures + neutral + card back, separate layouts for Conduit /
Tradition / Consequence / Relic, and a reusable compositor script (art + card-data
JSON → finished PNG). Placeholder mockups live in
`Images/cardgame/cards_with_frames/` (programmer art — needs redesign); card art in
`Images/cardgame/full/`. See section 12 of the design doc for the production path
(paper prototype → print-and-play PDF → Tabletop Simulator → Kickstarter). Generate
card art on the GX10 with the `eryndal-artist` skill.

## When writing card text
- Mechanics must read cleanly (MTG-style templating); flavour must be true to lore.
- Aggressive/high-Draw decks should genuinely risk their own Reckoning; defensive
  low-Disturbance decks should be able to sit safely. The Consequence Deck is the
  self-balancing engine — preserve that asymmetric pressure.
- The Drev are mechanically what they are narratively: overlooked, quiet, and the
  key nobody looks for. Don't "fix" their low raw power into something flashy.
