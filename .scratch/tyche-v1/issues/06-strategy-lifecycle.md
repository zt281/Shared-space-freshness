# 06: Run and stop isolated strategy groups

**What to build:** Two scripted strategy groups run independently; stopping, crashing or updating one produces visible and persistent scope-correct behavior.

**Blocked by:** 04 — Recover uncertain submissions and cancellation races.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D1, D3, D4.

## Acceptance criteria

- [ ] Supervise one process per group; a group crash cannot silently change another independent group state.
- [ ] Persist user stop, contract submission pause and risk stop separately from computation checkpoints; technical recovery cannot clear them.
- [ ] Stop new orders and attempt scoped cancellation while retaining positions; display outstanding unknown/cancel states.
- [ ] Allow a stopped group code update with a new generation; stale requests and work from the former generation are rejected.
- [ ] Require current dependencies and reconciliation for automatic technical recovery; include shared native-protection scope as a declared dependency.

## Implementation notes

Use two synthetic strategies. This slice validates lifecycle without waiting for the numerical algorithm port.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
