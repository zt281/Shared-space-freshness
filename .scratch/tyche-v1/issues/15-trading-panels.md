# 15: Add option-chain editing and safe price-ladder actions

**What to build:** The operator edits per-contract parameters and submits/cancels at the displayed ladder price in freely arranged panels.

**Blocked by:** 07 — Edit and activate complete parameter versions, 14 — Restore freely dockable multiwindow workspaces.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D5, D6.

## Acceptance criteria

- [ ] Provide configurable T-shaped option-chain columns and object/contract parameter drafts with effective-value/source/version display.
- [ ] Preview cross-object bulk edits and display each applied/conflict/failed/unknown result; no implied cross-object transaction.
- [ ] Freeze ladder price positions on mouse entry while values continue updating; capture exact click target instead of recalculating from a moving row index.
- [ ] Disable trading on initial open, target change, disconnect or workspace restore until explicit enablement after synchronization.
- [ ] Test target changes during updates, stale quote display, manual cancellation causing contract pause, and local feedback without pretending backend completion.

## Implementation notes

This ticket extends the already working simulated order path; no real account is needed.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
