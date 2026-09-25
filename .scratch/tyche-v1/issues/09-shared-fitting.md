# 09: Publish shared fitting results with exact input versions

**What to build:** Two consumers receive one versioned fitting result per relevant replay event, including automatic/manual/locked modes and visible validity.

**Blocked by:** 07 — Edit and activate complete parameter versions, 08 — Capture the existing algorithm as reproducible fixtures.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D5.

## Acceptance criteria

- [ ] Port the verified fitting/pricing core and pass the reference fixture packet; preserve finite-value and applicability checks.
- [ ] Use one owner per fitting instance and allow distinct configurations for the same underlying/expiry.
- [ ] Publish each triggering event and exact input/configuration versions, curve/base values, theory/Greeks and per-result validity.
- [ ] Solve unlocked coefficients under fixed locked values; all-locked manual mode recomputes pricing without refitting.
- [ ] Test a configuration switch in flight, numerical failure, unchanged successful coefficients, stale source and two strategies referencing one result.

## Implementation notes

A result is not a global snapshot; each consumer fixes its own required dependency versions.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
