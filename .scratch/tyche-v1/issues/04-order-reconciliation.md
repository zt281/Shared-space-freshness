# 04: Recover uncertain submissions and cancellation races

**What to build:** After a crash or lost reply the operator sees the original order and reserved risk, and can reconcile or cancel it without duplicate submission.

**Blocked by:** 03 — Submit a manual order to the scripted exchange.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D3, D4.

## Acceptance criteria

- [ ] Crash before/after possible-submission persistence and before/after the mock channel call; never resubmit an unknown attempt automatically.
- [ ] Retire provably unattempted old intents while preserving their identity; replay must not create replacement intents.
- [ ] Handle duplicate/out-of-order reports and partial fill during cancellation; replace only after confirming the old outcome and recomputing remaining demand.
- [ ] Preserve reserved risk until evidence resolves it; an empty or expired query response does not prove non-submission.
- [ ] Keep cancellation/query operations independently reachable when new-order evidence saving fails, reporting actual confirmation or uncertainty in the desktop.

## Implementation notes

The channel mock intentionally does not deduplicate submissions. This makes accidental retries observable.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
