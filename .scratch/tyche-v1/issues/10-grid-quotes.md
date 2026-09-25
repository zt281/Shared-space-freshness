# 10: Drive simulated orders from Grid quotes and fills

**What to build:** Grid strategies share base fitting while independently producing traceable quotes, risk lean and simulated order updates.

**Blocked by:** 05 — Reconcile account positions and attribution, 09 — Publish shared fitting results with exact input versions.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D4, D5.

## Acceptance criteria

- [ ] Compute both sides for a representative option chain with fixed fit/parameter/position versions; preserve per-contract units and executable rounding.
- [ ] Apply the approved inventory-volatility term exactly once; test net-long/net-short direction, disabled distance, PTh invalidity and invalid final volatility.
- [ ] Keep hedge and safety-band ownership separate; position-based quote lean must not widen its own safety protection.
- [ ] Fills immediately reprice all affected strategies after attribution update, invalidating pending old-position quotes without refitting the market curve.
- [ ] Exercise explicit bounded degradation versus stop/cancel, preserved original curve age, current-input requirements and normal recovery.

## Implementation notes

Use the original scope rules for risk lean and preserve the existing order replacement/reconciliation behavior.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
