# 21: Recover a simulated cross-market opportunity

**What to build:** A configured strategy consumes both markets and exposes each leg, residual exposure and recovery state after partial execution.

**Blocked by:** 10 — Drive simulated orders from Grid quotes and fills, 12 — Use the same plugin interface across two nodes, 19 — Exercise Binance order semantics through simulation, 20 — Exercise CTP replay and simulated execution.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D4, D9.

## Acceptance criteria

- [ ] Declare strategy owner, account nodes, exact remote dependencies and permissible data-age/clock-error profile.
- [ ] Correlate both legs and apply independent final account risk/authority checks at their execution owners.
- [ ] Inject one-leg fill with other-leg rejection/disconnect; stop new exposure, cancel remaining orders where possible and retain actual fills.
- [ ] Reject stale/duplicate/expired remote intents and preserve unknown risk across both node restarts.
- [ ] Measure local and cross-node stages separately; simulation uses an explicit example policy, not an invented profitable arbitrage rule or automatic hedge authorization.

## Implementation notes

A live strategy-specific opportunity rule, budgets and any corrective hedge policy must be explicitly configured and validated before activation.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
