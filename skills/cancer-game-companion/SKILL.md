---
name: cancer-game-companion
description: "Build, run, and deploy the Cancer Game Companion App POC — the live Tamagotchi-style adolescent cancer-prevention web app at playitsafe.app (projects/companion-app/poc). Covers the Vite + React 19 + TypeScript + Framer Motion + Zustand + Tailwind stack, the src architecture and Zustand store, the core care-needs loop (keep it from becoming a quiz), URL flags (?dev=1, ?startday=N), localStorage persistence/migrations, the Cloudflare Pages auto-deploy on push to main, and the manual wrangler path. Use when developing, debugging, building, or deploying the companion app. Use cancer-game-evidence for the science it surfaces, cancer-game-artist for its avatars."
---

# Cancer Game — Companion App POC (build, run, deploy)

The **Companion App** is the live, deployed product of the Cancer Game project:
a Tamagotchi-style mobile concept for adolescents (12–16) where the kid cares
for a painterly plant-elemental creature whose wellbeing reflects daily
cancer-prevention choices. This skill covers the POC's stack, how to run it,
and how it deploys. For the project map read `cancer-game`; for the science it
surfaces read `cancer-game-evidence`; for the avatar/mockup art read
`cancer-game-artist`.

## Where it lives & what it is
- Code: **`projects/companion-app/poc/`** in github.com/tyrion70/cancer-game.
- **Closed-alpha is live at [playitsafe.app](https://playitsafe.app)** behind a
  Cloudflare Access email-OTP gate.
- Stack: **Vite + React 19 + TypeScript + Framer Motion (`motion`) + Zustand +
  Tailwind**. Single static SPA, no backend. Read `poc/README.md` first — it is
  the authoritative file-layout, persistence, and deploy doc; the summary below
  orients you and the repo wins on conflict.

## Run locally
```bash
cd projects/companion-app/poc
npm install
npm run dev      # vite on http://0.0.0.0:5173 (LAN-reachable; open from a phone)
npm run build    # tsc -b && vite build → dist/
npm run lint     # eslint
```
Vite binds `0.0.0.0`, so a phone on the same LAN can hit `http://<mac-ip>:5173`.

### URL flags (demo / playtest affordances)
- `?dev=1` — show header demo buttons (`✦ event`, `✦ skin`, `✦ mood`, `✦ bloom`)
  that bypass natural timing. Persists in localStorage; clear with `?dev=0`.
  Hidden by default in the closed alpha.
- `?startday=N` — on a fresh avatar pick, backdate the run to begin on in-app day
  `N` (1–90), landing a playtester near auto-bloom / mid-cadence events in
  seconds. One-shot. Combine e.g. `playitsafe.app?dev=1&startday=28`.

## Architecture map (`poc/src/`)
- `main.tsx` — entry; arms `armAudioUnlock()` before mount.
- `App.tsx` — route switch (picker / home / memories).
- `state/store.ts` — **Zustand store** + persist middleware; careStreak,
  weeklySummary, encounteredEcac5 tracking. The heart of the app.
- `components/` — `Companion` (avatar renderer), `Home` (daily care + life events
  + visits), `Memories` (streak/weekly cards/ECAC5 grid/journal), `Onboarding`,
  `DailyFactCard`, `BloomCelebration`, `CareVisitBanner`, `LifeEvent`, plus
  `actions/` and `visits/` subfolders.
- `data/` — `ecac5.json`, `scenarios.json` (derived from the shared evidence DB —
  see `cancer-game-evidence`), `dailyFacts.ts`, `lifeEvents.ts`, `seasons.ts`,
  `needs.ts`, `avatars.ts`, `simpleActions.ts`, `moodLines.ts`, `visits.ts`.
- `audio.ts` — Web Audio chimes + seasonal ambient drone; `devMode.ts` — URL flags.
- `public/avatars/<id>/<state>.png` — 42 painterly avatar variants (generated; see
  `cancer-game-artist`). `public/habitat/<season>.png` — seasonal backdrops.

## The core loop (so changes stay on-concept)
Six care needs (Nourishment / Energy / Joy / Light / Rest / Air) decay in
real-time at 4× speed (4 real hours = 1 in-app day). The kid meets them through
six gentle verbs (Feed / Play / Sun / Sleep / Comfort / Vent). Cancer-prevention
evidence shapes **what the companion needs** and **how needs are met** — decisions
appear as **rare weighty life events** (vape offer, HPV moment, tanning bed,
social-media myth), never a daily quiz. Compound moments chain a second ECAC5 rec
(Play→outdoor→sunscreen; Feed→BBQ). Auto-bloom on day 30+ when thriving.
**Keep this loop intact — don't turn care into a quiz.**

## Persistence & migrations
All state in `localStorage` under `companion-app-poc-state` (Zustand `persist`,
**version 2**). Audio under `companion-app-poc-mute`, dev flag under
`companion-app-poc-dev`. If you change the persisted state shape, bump the
version and add a migration (see `poc/README.md` for the v1→v2 example —
`encounteredEcac5` changed shape). Breaking persistence silently resets every
tester's progress.

## Deploy
Auto-deploys to **Cloudflare Pages** (project `playitsafe`) on push to `main`,
via `.github/workflows/deploy-poc.yml` (paths: `projects/companion-app/poc/**`).
Node 22, `npm ci && npm run build`, then `wrangler pages deploy dist`. Secrets
`CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` live in GitHub Actions.

So the normal path is: **merge the PR → push to `main` → it deploys itself.**
Manual force-deploy (rarely needed):
```bash
export CLOUDFLARE_API_TOKEN=...                              # from bitwarden
export CLOUDFLARE_ACCOUNT_ID=11c195ddb38b83a917bc07f8445c4b73
cd projects/companion-app/poc && npm run build
npx wrangler pages deploy dist --project-name=playitsafe --branch=main --commit-dirty=true
```
Adding a closed-alpha tester = add their email to the Cloudflare Access allow
policy for playitsafe.app. Never hardcode the API token — pull it from
`bitwarden`.

## Working rules
- Code changes ship via the `git-pr` workflow (issue-first, SSH-signed, PR linked).
- Run `npm run build` and `npm run lint` before pushing — the deploy runs `tsc`,
  so a type error breaks the live alpha.
- Touching `data/*.json` means a science change — read `cancer-game-evidence` and
  keep it consistent with the shared evidence DB.
- Mobile-first: this is meant to be played on a phone. Test at phone width.
