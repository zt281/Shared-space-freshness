# 22: Gate activation on reproducible validation records

**What to build:** The operator sees coverage for a specific code/configuration/channel scope and cannot activate a path lacking required evidence.

**Blocked by:** 11 — Explain restrictions and persist alarms across windows.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D8, D10.

## Acceptance criteria

- [ ] Replay the full recorded decision chain with initial state and exact input order; compare intents, executable prices/quantities, risk and position changes.
- [ ] Report first divergence and missing evidence; same-build discrete outcomes must match and floating tolerances cannot hide trading changes.
- [ ] Issue a validation record bound to code/configuration combinations, products, accounts/capabilities, risk and capacity profile.
- [ ] Invalidate affected coverage after behavior changes/out-of-range edits; distinguish passed, failed and uncovered cases.
- [ ] Keep replay/simulation credentials and state isolated; a real activation additionally needs current reconciliation and explicit user action.

## Implementation notes

Build the activation gate with fixtures. A test-generated pass record must never masquerade as external account validation.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
