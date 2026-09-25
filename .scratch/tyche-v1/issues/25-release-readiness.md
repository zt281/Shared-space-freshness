# 25: Assemble the v1 release evidence and activation checklist

**What to build:** The operator receives a concise product-by-product readiness record rather than a blanket claim that all trading paths are ready.

**Blocked by:** 23 — Measure representative strategy and workbench capacity, 24 — Package the desktop and backend deployment profiles.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D10.

## Acceptance criteria

- [ ] Link each required story to its completed ticket and executable evidence; mark failed and uncovered requirements separately.
- [ ] List actual SDK/build/config, account/product rights, server protection, hardware and measured capacity for each deployable profile.
- [ ] Verify persisted evidence restore/backup procedure on the intended host; distinguish process recovery from power-loss or lost-host coverage.
- [ ] Keep normal trading disabled for profiles missing mandatory evidence and document the remaining concrete action.
- [ ] Document any separately authorized bounded live acceptance as a future operation with account/contract/time/risk scope; do not execute it as part of this ticket.

## Implementation notes

The milestone is honest release readiness per profile. It never converts planning or a simulator pass into authorization to trade.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
