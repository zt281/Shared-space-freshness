# 07: Edit and activate complete parameter versions

**What to build:** The operator edits one object, sees inherited/overridden values, and observes a complete version take effect at an event boundary.

**Blocked by:** 06 — Run and stop isolated strategy groups.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D5, D6.

## Acceptance criteria

- [ ] Declare field ownership, units, valid range, override capability and explicit enable switches; unset inherits and zero remains a real value.
- [ ] Submit a complete version with expected base; stale submissions return conflict and preserve the draft.
- [ ] Activate atomically for one object at the event boundary; record requested and effective versions in event evidence.
- [ ] Show applied, rejected, conflict and unknown outcomes in the editor; reconnect resynchronizes before editing is enabled.
- [ ] Test simultaneous event arrival/edit, invalid fields, clear override, lost reply and same-ID retry without applying twice.

## Implementation notes

Fit, strategy, hedge and band are separate versioned objects. Cross-object atomic transactions are not required.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
