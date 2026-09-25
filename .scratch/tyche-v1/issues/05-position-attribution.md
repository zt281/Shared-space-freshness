# 05: Reconcile account positions and attribution

**What to build:** The operator sees actual positions, strategy/manual attribution and unexplained differences without hiding risk.

**Blocked by:** 04 — Recover uncertain submissions and cancellation races.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D4, D7.

## Acceptance criteria

- [ ] Consume each fill once into native-currency balances, account positions and separately identified attribution records.
- [ ] Reconcile channel snapshots with event history; unexplained holdings remain unattributed and count toward account risk.
- [ ] Implement explicit attribution transfer with reference price, effective time and immutable history; no simulated external fill is created.
- [ ] Show distinct balances, attribution and reconciliation status in a monitor; missing FX or original cost remains explicitly unknown.
- [ ] Test repeated fills, correction/out-of-order input, net-zero account position with nonzero opposing attribution, restart and missing history.

## Implementation notes

Do not equate logical strategy close with a channel close/reduce-only instruction; channel modes own that conversion.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
