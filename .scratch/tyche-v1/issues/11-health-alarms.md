# 11: Explain restrictions and persist alarms across windows

**What to build:** The operator can see why each path is restricted, acknowledge an alarm and reconnect without losing its lifecycle.

**Blocked by:** 06 — Run and stop isolated strategy groups.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D8.

## Acceptance criteria

- [ ] Publish connection, generation, source validity, completeness, persistence and reconciliation separately, with a dependency-derived reason list.
- [ ] Implement active/acknowledged-active/recovered occurrences with deduplication by scope/cause/generation; acknowledgement never clears the cause.
- [ ] Persist alarm history in the backend and reconcile it after desktop closure; optional notification/sound throttling cannot alter backend behavior.
- [ ] Show unknown submissions, reserved risk, shared protection effects and actual cancellation confirmation explicitly.
- [ ] Test quiet valid markets versus heartbeat loss, repeated faults, acknowledged recurrence, failed notification and bounded diagnostics with dropped counters.

## Implementation notes

No Slack/email or other external notification integration is part of this slice.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
