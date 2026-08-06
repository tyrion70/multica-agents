---
name: Weekend Escape Radar
description: Personal MVP — travel intelligence platform that surfaces unusually good weekend trips
type: project
originSessionId: 92331e2a-f9df-4679-b734-d27cbe36271b
---
PRIVATE personal-use project. Repo at github.com/tyrion70/weekend-escape-radar (private). Working tree lives at `~/claude/repositories/weekend-escape-radar/` — `projects/travel/` is a thin pointer.

**Stack:** Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic, Postgres 16, Redis 7. Local dev via `compose.yml` at the repo root. Deploy target: single Proxmox VM (Phase 6, not yet provisioned).

**Phase 0 is done:** compose stack runs, full domain schema migrated (windows / fares / baselines / candidates / alerts), manual-window POST endpoint as a stand-in for calendar sync (which is deferred, "Phase 1" skipped). Working test window: 2026-05-21 → 2026-05-25 (Pentecost long weekend), seeded via `make seed-demo`.

**Why:** User wants a personal travel concierge that scans free weekends + Amadeus fares and alerts on unusually good deals. Doc lists hotels/Telegram/predictive pricing — those land in later phases.

**How to apply:** When the user asks about "the travel project" or weekend-escape-radar, work in `~/claude/repositories/weekend-escape-radar/`. Phase 2 next: Amadeus Self-Service client + APScheduler worker — keys go in `.env` as `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET`.

**Conventions for this repo:** No Linear (personal project, not chainlayer). Conventional commits. No Co-Authored-By in commits (matches global preference).
