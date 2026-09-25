# 02: Recover a published local stream after a process crash

**What to build:** A producer and consumer in separate processes expose durable published versions and recovered consumer progress through the desktop status view.

**Blocked by:** 01 — Replay prices into a read-only desktop.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D2, D3.

## Acceptance criteria

- [ ] Use environment/object/generation/sequence identity, immutable complete records and a local shared-memory adapter behind the uniform access interface.
- [ ] Run one authoritative writer and reject a second owner; reattach through handles after a verified owner restart and reject stale-generation writes.
- [ ] Replay from a jointly saved state/cursor with exact inputs/configuration retained; show computed, saved and published progress separately.
- [ ] Inject partial writes, lost acknowledgements and consumer death; independently decode evidence to show no skipped or double-counted events.
- [ ] Missing/corrupt evidence and gaps produce a restricted state, never an empty fallback. Begin with per-event saves as the correctness baseline.

## Implementation notes

Reuse the existing process-crash scenarios as requirements; use a versioned production format instead of freezing the prototype binary ABI.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
