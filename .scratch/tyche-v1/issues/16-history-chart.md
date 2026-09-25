# 16: Browse versioned history without blocking execution

**What to build:** A chart loads bounded history, exposes gaps and original records, and switches to live data at an explicit watermark.

**Blocked by:** 02 — Recover a published local stream after a process crash, 14 — Restore freely dockable multiwindow workspaces.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D7.

## Acceptance criteria

- [ ] Implement one query interface with fixture and DolphinDB analytical adapters; pin and verify the actual package/license when adding that adapter.
- [ ] Keep recovery evidence independent; chart/database failure must not corrupt order recovery or silently drop required replay records.
- [ ] Return bounded point/byte pages, cancellation/continuation and meaningful extrema/count/gap summaries; zoom requests finer data.
- [ ] Join history and live by sequence watermark with explicit gap handling and no duplicate boundary event.
- [ ] Check slow query, unavailable database, full analytical buffer, long ranges and evidence-budget warning/restriction without automatic deletion.

## Implementation notes

Begin with explicit bid/ask/recorded-theory series. Named financial factors are added by the next ticket, not guessed here.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
