# 19: Exercise Binance order semantics through simulation

**What to build:** The same manual/strategy order path operates against verified Binance simulation endpoints and exposes product-specific limitations.

**Blocked by:** 05 — Reconcile account positions and attribution, 18 — Display normalized Binance market data.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D4, D10.

## Acceptance criteria

- [ ] Implement product-specific mappings for intent, channel order/fill, account/position mode, cancel/query and rate-limit behavior.
- [ ] Run deterministic adapter fixtures for unknown outcomes, duplicates, partial fills, query limits and missing required protection.
- [ ] When a simulation account is configured, record supported/failed/uncovered cases independently for options and USDT perpetuals.
- [ ] Validate sell-to-open/close semantics, risk reservation and native protection scope/renewal without pretending all products share one account model.
- [ ] Keep normal real trading unavailable; missing credentials or endpoint coverage is an explicit external acceptance gate, not a fixture pass.

## Implementation notes

Simulation connectivity can be completed later with user-supplied account access. No real-order permission is implied.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
