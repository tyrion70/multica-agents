---
name: ess-ai-planner project
description: Private AI optimizer project for the home ESS — repo conventions, scope, and tracking rules
type: project
originSessionId: fa334a32-d673-46bc-b583-c3fb19af4168
---
**Private project — no Linear issue tracking.** Unlike all other Chainlayer/ChainLink work, this project is personal and does NOT get Linear issues. Just commit and push.

**Repo:** `repositories/ess-ai-planner/` locally → `github.com/tyrion70/ess-ai-planner` (PRIVATE).

**Why:** Goal is to replace the heuristic ESS scheduler in `repositories/ess` with a forecast-layer + MILP optimizer (then optionally an amortized neural surrogate). Validated against real historical data via backtest harness before anything ships.

**How to apply:**
- Don't create Linear issues for ess-ai-planner work — straight to commits/PRs.
- The ess repo (`tyrion70/ess`) is **read-only** for this project. Any change there is a separate, explicit PR with its own Linear issue (since ess itself follows the normal workflow).
- Plan lives in `projects/ess-ai-planner/PLAN.md` — phased: bootstrap → backtest harness → MILP → learned forecasts → service+shadow → amortized surrogate.
