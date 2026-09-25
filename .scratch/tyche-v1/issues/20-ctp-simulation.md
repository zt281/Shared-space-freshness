# 20: Exercise CTP replay and simulated execution

**What to build:** CTP futures/options replay and simulated execution drive the same order, position and recovery views.

**Blocked by:** 05 — Reconcile account positions and attribution.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D4, D10.

## Acceptance criteria

- [ ] Pin actual CTP/OpenCTP SDK and environment; record license/distribution constraints and compile the platform-specific adapter separately.
- [ ] Map instrument/session/trading-day identity, close offsets, position fields, order references and fills without importing Binance assumptions.
- [ ] Run fixtures for disconnect, query reconciliation, duplicate reports, partial fills and cancellation races.
- [ ] Record live-simulation coverage separately from vendor replay; vendor replay alone is not a complete decision-chain validation.
- [ ] Keep required native protection capability unknown until verified for the actual target counter; expose unavailable paths clearly.

## Implementation notes

Keep third-party SDK access and simulation login as explicit adapter acceptance gates. QMT remains deferred.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
