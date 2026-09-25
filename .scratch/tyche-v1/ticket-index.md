# Implementation order

A ticket is runnable when its numbered blockers are complete. `ready-for-agent` describes ticket clarity, not completion of its dependencies or external evidence. Claim one ticket at a time; do not triage these generated tickets.

| Ticket | Depends on | Deliverable |
| --- | --- | --- |
| [01 — Replay prices into a read-only desktop](issues/01-replay-desktop.md) | None | A clean checkout starts a C++ replay backend and an Electron/Vue desktop showing one contract, environment and connection state. |
| [02 — Recover a published local stream after a process crash](issues/02-durable-shared-space.md) | 01 | A producer and consumer in separate processes expose durable published versions and recovered consumer progress through the desktop status view. |
| [03 — Submit a manual order to the scripted exchange](issues/03-simulated-manual-order.md) | 02 | The operator submits one limit order from a fixed-account panel and sees acceptance or rejection from an isolated simulated channel. |
| [04 — Recover uncertain submissions and cancellation races](issues/04-order-reconciliation.md) | 03 | After a crash or lost reply the operator sees the original order and reserved risk, and can reconcile or cancel it without duplicate submission. |
| [05 — Reconcile account positions and attribution](issues/05-position-attribution.md) | 04 | The operator sees actual positions, strategy/manual attribution and unexplained differences without hiding risk. |
| [06 — Run and stop isolated strategy groups](issues/06-strategy-lifecycle.md) | 04 | Two scripted strategy groups run independently; stopping, crashing or updating one produces visible and persistent scope-correct behavior. |
| [07 — Edit and activate complete parameter versions](issues/07-parameter-versions.md) | 06 | The operator edits one object, sees inherited/overridden values, and observes a complete version take effect at an event boundary. |
| [08 — Capture the existing algorithm as reproducible fixtures](issues/08-algorithm-reference.md) | 01 | A command-line reference check produces portable, versioned inputs and expected outputs for the existing UMM pricing/fitting behavior and approved changes. |
| [09 — Publish shared fitting results with exact input versions](issues/09-shared-fitting.md) | 07, 08 | Two consumers receive one versioned fitting result per relevant replay event, including automatic/manual/locked modes and visible validity. |
| [10 — Drive simulated orders from Grid quotes and fills](issues/10-grid-quotes.md) | 05, 09 | Grid strategies share base fitting while independently producing traceable quotes, risk lean and simulated order updates. |
| [11 — Explain restrictions and persist alarms across windows](issues/11-health-alarms.md) | 06 | The operator can see why each path is restricted, acknowledge an alarm and reconnect without losing its lifecycle. |
| [12 — Use the same plugin interface across two nodes](issues/12-remote-shared-space.md) | 06 | A strategy consumes remote published data and sends a simulated intent to the authoritative remote account owner using the same logical interface. |
| [13 — Batch consumer checkpoints in the complete simulated path](issues/13-integrated-checkpoints.md) | 10, 12 | The integrated system reduces computational checkpoint writes while retaining correct published results, trade evidence and recovery behavior. |
| [14 — Restore freely dockable multiwindow workspaces](issues/14-dock-workspaces.md) | 01 | The operator creates repeated panels, docks/splits/floats them, pops out windows and restores a named workspace. |
| [15 — Add option-chain editing and safe price-ladder actions](issues/15-trading-panels.md) | 07, 14 | The operator edits per-contract parameters and submits/cancels at the displayed ladder price in freely arranged panels. |
| [16 — Browse versioned history without blocking execution](issues/16-history-chart.md) | 02, 14 | A chart loads bounded history, exposes gaps and original records, and switches to live data at an explicit watermark. |
| [17 — Add reproducible factor and trade-analysis series](issues/17-factor-definitions.md) | 05, 09, 16 | Each displayed factor or trade-edge value has a versioned definition, exact inputs and fixture-backed interpretation. |
| [18 — Display normalized Binance market data](issues/18-binance-market-data.md) | 02, 14 | The desktop discovers and displays the selected Binance products through a read-only adapter and can record them for replay. |
| [19 — Exercise Binance order semantics through simulation](issues/19-binance-simulation.md) | 05, 18 | The same manual/strategy order path operates against verified Binance simulation endpoints and exposes product-specific limitations. |
| [20 — Exercise CTP replay and simulated execution](issues/20-ctp-simulation.md) | 05 | CTP futures/options replay and simulated execution drive the same order, position and recovery views. |
| [21 — Recover a simulated cross-market opportunity](issues/21-cross-market-strategy.md) | 10, 12, 19, 20 | A configured strategy consumes both markets and exposes each leg, residual exposure and recovery state after partial execution. |
| [22 — Gate activation on reproducible validation records](issues/22-validation-gate.md) | 11 | The operator sees coverage for a specific code/configuration/channel scope and cannot activate a path lacking required evidence. |
| [23 — Measure representative strategy and workbench capacity](issues/23-capacity-acceptance.md) | 13, 15, 17, 21 | The operator receives a reproducible capacity report for the integrated system, with incomplete work and actual UI load included. |
| [24 — Package the desktop and backend deployment profiles](issues/24-desktop-packaging.md) | 14, 22 | The operator installs Ubuntu/Windows desktops and selects a local or remote backend without losing workspace or environment identity. |
| [25 — Assemble the v1 release evidence and activation checklist](issues/25-release-readiness.md) | 23, 24 | The operator receives a concise product-by-product readiness record rather than a blanket claim that all trading paths are ready. |
