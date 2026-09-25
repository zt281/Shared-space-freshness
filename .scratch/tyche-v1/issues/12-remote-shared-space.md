# 12: Use the same plugin interface across two nodes

**What to build:** A strategy consumes remote published data and sends a simulated intent to the authoritative remote account owner using the same logical interface.

**Blocked by:** 06 — Run and stop isolated strategy groups.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D2, D9.

## Acceptance criteria

- [ ] Pin/reproduce MsQuic and its dependencies; implement versioned authenticated transport without exposing raw pointers or broker credentials.
- [ ] Keep local and remote adapters behaviorally equivalent for immutable publication, identity, retained history and explicit progress receipts.
- [ ] Exercise loss/reconnect, generation change, wrong identity, missing prefix, queue overflow and source-time expiry with fixed retained evidence.
- [ ] Route remote intent deduplication/outcome queries to the execution owner; final risk and authority checks stay there.
- [ ] Display both node/dependency states; use same-host monotonic timing for a loopback run and explicitly record clock uncertainty for real hosts.

## Implementation notes

This is an implementation slice, not another general network prototype. Reuse bounded original QUIC scenarios and stop when its acceptance cases pass.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
