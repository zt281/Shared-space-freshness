# 01: Replay prices into a read-only desktop

**What to build:** A clean checkout starts a C++ replay backend and an Electron/Vue desktop showing one contract, environment and connection state.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D1, D6.

## Acceptance criteria

- [ ] Provide locked dependencies, reproducible setup/build/run commands and a deterministic synthetic fixture with no credentials or external traffic.
- [ ] Publish a versioned snapshot and ordered price updates from C++ through the real desktop connection; show the contract, replay environment, sequence and timestamp.
- [ ] Reject an unsupported protocol version; on a sequence gap or disconnect preserve the last view with an invalid indicator and resnapshot on reconnect.
- [ ] Provide one command that checks the C++ behavior and desktop type/build checks; add a renderer-level smoke check for the actual replay path.
- [ ] Document source/test/asset layout and tools in the root README. The first demo has no order button, plugin framework expansion or docking implementation.

## Implementation notes

Start from an empty production application, not by promoting the synthetic prototype classes. Group backend, desktop, behavior tests and fixtures by responsibility; document the chosen layout in the first slice.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
