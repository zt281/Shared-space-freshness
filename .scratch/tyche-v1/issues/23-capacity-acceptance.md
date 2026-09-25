# 23: Measure representative strategy and workbench capacity

**What to build:** The operator receives a reproducible capacity report for the integrated system, with incomplete work and actual UI load included.

**Blocked by:** 13 — Batch consumer checkpoints in the complete simulated path, 15 — Add option-chain editing and safe price-ladder actions, 17 — Add reproducible factor and trade-analysis series, 21 — Recover a simulated cross-market opportunity.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D6, D9.

## Acceptance criteria

- [ ] Use representative fitting/Grid work at 500 contracts, 20 active instances and 100 options/two sides per group; declare sharing/fanout and input rates.
- [ ] Measure complete market-entry to last necessary submit-call latency with risk and persistence included; retain no-submit, rejected and unfinished rounds.
- [ ] Compare to the unchanged local p99 1ms/p99.9 5ms goals, and report sustainable rate only where queues do not grow.
- [ ] Measure actual visible panels/windows/rows/curves on the target dual-screen workload against the accepted display and feedback goals.
- [ ] Classify missing target hardware/capacity evidence as uncovered; optimize a measured bottleneck in bounded work rather than restarting architecture exploration.

## Implementation notes

This is a release acceptance task, not a prerequisite for coding. Failing a target produces a concrete optimization ticket and keeps that capacity profile unapproved.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
