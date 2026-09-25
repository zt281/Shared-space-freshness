# 08: Capture the existing algorithm as reproducible fixtures

**What to build:** A command-line reference check produces portable, versioned inputs and expected outputs for the existing UMM pricing/fitting behavior and approved changes.

**Blocked by:** 01 — Replay prices into a read-only desktop.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D5.

## Acceptance criteria

- [ ] Locate the original UMM source or an exported source/fixture package; record revision and hashes and preserve source ownership/licensing context.
- [ ] Capture representative pricing, Wing fitting, locked coefficients, manual mode, invalid input, inventory lean and hedge/band cases with explicit units.
- [ ] Separate old behavior from accepted changes, particularly the inventory-volatility correction and per-event triggering.
- [ ] Reference checks report numerical tolerance and discrete expected behavior; do not label synthetic replacement formulas as the existing algorithm.
- [ ] Produce a portable fixture runner and a source-to-contract discrepancy report usable by the next numerical slice.

## Implementation notes

External input gate: the referenced D:/dev/UMM source is absent from this checkout. Obtain it when taking this ticket; record blocked rather than inventing the algorithm. Foundation work does not depend on this ticket.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
