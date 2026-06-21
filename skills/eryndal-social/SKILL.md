---
name: eryndal-social
description: "Build and publish Eryndal social content — @eryndal.online on Instagram. Covers the automated posting pipeline (never ask the user to post manually), the reel/story video rules (never fade in from black — first frame is the thumbnail), the reels/ folder + post_log discipline, the CC-BY music library, content types, and cadence. Use when creating reels/stories/image posts, writing captions, or posting via the scripts. Operational source of truth: .claude/KNOWLEDGE.md and reels/post_log.md in the repo."
---

# Eryndal Social — Instagram Content Pipeline

Build and publish social content for **Eryndal** — @eryndal.online on Instagram,
live with ~daily posts since 2 Apr 2026. Use when creating reels/stories/image
posts, writing captions, or posting via the automated pipeline. Operational notes:
`.claude/KNOWLEDGE.md` in the repo; content ideas: `reels/post_ideas.md`; history:
`reels/post_log.md` (authoritative). Keep all copy true to `eryndal-lore`. Site:
https://eryndal.online (Cloudflare Pages). Credentials in `.env`
(`INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`).

## Never ask the user to post manually
Scripts in `scripts/` do it via the Instagram Platform API:
- `post_instagram.py` — images (uploads to Cloudflare Pages → IG API).
- `post_instagram_reel.py` — reels/videos, optional `--share-to-story`.
- Flow: local file → ffmpeg re-encode → copy to `website/img/` → deploy
  (`deploy_site.sh`) → IG create container → wait for processing → publish.
- A 403 on URL verification is normal (Cloudflare CDN propagation) — IG fetches it
  fine.
- Builders: `build_instagram_story.py` (The Pale), `build_instagram_valdris.py`
  (world), plus per-character/per-topic builders (prose, serevane, dara, halric,
  hegemony_log, tam, veth, aldric).

## Reel / story video rules (hard-won)
- **NEVER fade in from black.** The first frame becomes the Instagram thumbnail — a
  black first frame = invisible post. First frame must be the strongest visual (art,
  map, or title card) at full brightness.
- Fade-outs at the end are fine; crossfades between slides are fine.
- The cover/title slide is a good *final* frame, not a good *first* frame (art is
  more eye-catching up front).

## Content structure & discipline
- **All reel/story content lives in `reels/`**, never `output/`. One folder per
  post: `reels/YYYY-MM-DD-<reel|story>-<description>/` holding the final `.mp4` and
  all source `.png` slides. Shared assets (music, fonts) in `reels/_assets/`.
- Build scripts output to `output/instagram_stories/` temporarily, then move final
  content into the dated `reels/` folder.
- **Update `reels/post_log.md` after every post** — date, type, description, post
  URL/ID, folder path. This is the single source of truth for what's been published.

## Music library (`reels/_assets/` — all Scott Buckley, CC-BY 4.0)
`i_walk_with_ghosts.mp3` (haunting) · `the_long_dark.mp3` (melancholic piano+strings)
· `nightfall.mp3` (dark strings→build) · `permafrost.mp3` (meditative violin) ·
`last_and_first_light.mp3` (bittersweet orchestral). Credit Scott Buckley.

## Content types (low → high effort)
1. **Text/quote** — Serevane epigraphs, in-universe documents (Hegemony logs,
   Freehold reports, clan stone-songs), one-lore-concept threads, non-spoiler
   character quotes.
2. **Visual** — character portraits, location/creature art, progressive map reveals,
   excerpt cards (prose over atmospheric art). Generate with `eryndal-artist`; Dall-E
   for quick iterations, Flux for portrait quality.
3. **Audio/video** — short narrated readings over art (TTS via `eryndal-audiobook`),
   "Lore Codex" audio shorts, atmospheric animated shorts.

## Cadence & strategy
~1 post/day, mixing character deep-dives, prose excerpts, and worldbuilding. Build a
queue ahead; consistency beats virality. Open ideas in `reels/post_ideas.md`
(e.g. Seris still lacks a solo spotlight reel; Serevane-quote series planned). Other
planned channels (not yet live): TikTok/Reels, X/Bluesky, Substack, YouTube Lore
Codex — see `docs/UNIVERSE_EXPANSION_PLAN.md`.
