---
name: ESS saas-pi-appliance local-first principle
description: Architectural rule for the ess saas-pi-appliance project — only public data (prices, solar, weather) lives in cloud; everything customer-specific stays on the Pi
type: project
originSessionId: 1fdc6b8e-07b1-48ce-9987-7daf406c5d29
---
For `github.com/tyrion70/ess` saas-pi-appliance project, the
load-bearing architectural rule is **local-first with public-data
exception**:

- **Cloud holds:** identity/billing (customer email, subscription
  state), public data canonical history (prices, solar, weather
  forecasts), aggregate fleet metrics, Pi heartbeat.
- **Pi holds:** energy time-series, override/curtail flags, schedule
  decisions, Wi-Fi creds, MQTT creds, plus a rolling local window of
  recent prices/solar for the optimizer.
- **Subscription cancel effect:** customer keeps live optimizer
  (rolling window), loses access to historical price/solar charts.
  By design — ties cloud value to the subscription without holding
  any of the customer's own data hostage.
- **Privacy framing:** if the customer cuts off the cloud, they keep
  the optimizer working but lose history. Their own data (energy,
  overrides) is never in cloud at all, so privacy is preserved
  unconditionally.

**Why:** captured 2026-05-03 from the user during review of the
initial planning docs. This principle resolves part of the
grace-period ambiguity (REVIEW.md §1.1) and reframes M4 from a
fallback cache to a canonical public-data history store.

**How to apply:**
- When designing any new cloud endpoint or storage table, ask: is
  this public data, identity/billing, or aggregate? If not, it must
  be on the Pi.
- When designing any Pi storage, ask: is this customer-specific
  behaviour data? If yes, it must never leave the Pi unless customer
  opts in to support diagnostics.
- M4 (price/solar history) is the only milestone that intentionally
  puts customer-relevant data in the cloud, and it's gated to
  public-domain inputs only.
