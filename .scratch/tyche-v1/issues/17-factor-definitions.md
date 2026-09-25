# 17: Add reproducible factor and trade-analysis series

**What to build:** Each displayed factor or trade-edge value has a versioned definition, exact inputs and fixture-backed interpretation.

**Blocked by:** 05 — Reconcile account positions and attribution, 09 — Publish shared fitting results with exact input versions, 16 — Browse versioned history without blocking execution.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D7.

## Acceptance criteria

- [ ] Write the formula profile for each requested realized-volatility window, MicroPrice/weighted-mid difference and theoEdge/actual Edge before implementing it.
- [ ] Bind price source, time sampling, year basis, units, direction, fee inclusion, reference horizon and missing-data behavior; get a specific business decision only if evidence leaves these genuinely ambiguous.
- [ ] Use deterministic fixtures covering missing/crossed quotes, zero depth, irregular time, partial fills, fees and late corrections as applicable.
- [ ] Carry theoretical-price/position/configuration provenance through the historical and live chart views.
- [ ] Keep old formula versions queryable after changes and mark incomparable/unknown values instead of silently filling them.

## Implementation notes

This later product-definition gate does not block chart infrastructure or core trading. No profitability claim is part of the ticket.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
