# 24: Package the desktop and backend deployment profiles

**What to build:** The operator installs Ubuntu/Windows desktops and selects a local or remote backend without losing workspace or environment identity.

**Blocked by:** 14 — Restore freely dockable multiwindow workspaces, 22 — Gate activation on reproducible validation records.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D1, D6, D10.

## Acceptance criteria

- [ ] Produce reproducible desktop packages and a Linux backend launch/service profile with explicit config/data/log locations.
- [ ] Keep secrets in the intended credential store/backend environment; never package credentials or restore enabled trading from a workspace.
- [ ] Enforce non-loopback authentication/TLS and one active desktop control session while supporting read-only recovery views.
- [ ] Test install, upgrade, restart, offline startup, workspace migration and a refused incompatible protocol/schema.
- [ ] Provide local-first, domestic CTP and overseas Binance deployment profiles with fresh target-environment validation requirements.

## Implementation notes

This implements deployment tooling; actual external server provisioning and real trading remain separately authorized operations.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
