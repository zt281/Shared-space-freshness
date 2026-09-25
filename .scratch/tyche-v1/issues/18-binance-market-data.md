# 18: Display normalized Binance market data

**What to build:** The desktop discovers and displays the selected Binance products through a read-only adapter and can record them for replay.

**Blocked by:** 02 — Recover a published local stream after a process crash, 14 — Restore freely dockable multiwindow workspaces.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D2, D10.

## Acceptance criteria

- [ ] Check current official product/schema/stream documentation and pin the implementation assumptions; do not rely on historical research as current account capability.
- [ ] Namespace instruments by environment/venue/product; discovery is distinct from active strategy subscriptions.
- [ ] Normalize retained raw events and timestamps with explicit gaps/reconnect/snapshot handling, including depth continuity where required.
- [ ] Show options, perpetual and selected equity-related perpetual capability separately; unavailable symbols are explicit.
- [ ] Test against recorded fixtures first, then an optional public read-only smoke run with complete provenance. No trading credentials or order routes are loaded.

## Implementation notes

Public discovery confirms public availability, not a particular account permission or a protected market-making capability.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
