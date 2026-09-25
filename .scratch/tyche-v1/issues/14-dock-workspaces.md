# 14: Restore freely dockable multiwindow workspaces

**What to build:** The operator creates repeated panels, docks/splits/floats them, pops out windows and restores a named workspace.

**Blocked by:** 01 — Replay prices into a read-only desktop.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D6.

## Acceptance criteria

- [ ] Implement the accepted free Dock interaction with five-direction targets and nested splits; do not revive the superseded fixed A/B/C layouts.
- [ ] Persist stable panel IDs, panel type/configuration, geometry and link groups; support repeated instances.
- [ ] Keep account/strategy targets fixed and visible while a linked contract selection changes.
- [ ] Restore on Ubuntu and Windows with out-of-screen geometry corrected and all trading controls disabled.
- [ ] Check drag/drop, resize, cross-window state updates, hidden-panel subscription pause, reopen and workspace schema migration.

## Implementation notes

Use the existing prototype/workbench branch at 627560fe as interaction evidence, not production code or a capacity guarantee.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
