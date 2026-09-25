# 03: Submit a manual order to the scripted exchange

**What to build:** The operator submits one limit order from a fixed-account panel and sees acceptance or rejection from an isolated simulated channel.

**Blocked by:** 02 — Recover a published local stream after a process crash.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D4, D6.

## Acceptance criteria

- [ ] Capture immutable environment/account/instrument/side/price/quantity and a stable client intent ID at click time.
- [ ] Validate tick/lot increments and configured account/group/contract risk; unavailable risk or invalid environment rejects before external submission.
- [ ] Durably record intent identity and risk reservation, then the possible-submission marker, before invoking the scripted channel.
- [ ] Distinguish local pending, channel accepted and rejected views; an SDK-style return alone never shows a fill.
- [ ] Check duplicate control requests, save failure and risk rejection; a counting mock must show zero calls on rejection and one call on successful submission.

## Implementation notes

Use explicit deterministic simulation limits. No production defaults or real credentials are required.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
