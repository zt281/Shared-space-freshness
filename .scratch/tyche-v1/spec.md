# Tyche v1 development specification

Status: ready-for-agent
Labels: ready-for-agent
Date: 2026-09-25

## Problem Statement

The user needs a personal multi-account trading workbench whose C++ strategies continue
running independently of the desktop. It must support CTP futures/options and the selected
Binance products, share fitting results across strategies, and preserve explainable order,
position and recovery state across failures. Existing work comprises decisions and disposable
prototypes, not a production application. More open-ended prototyping is delaying implementation.

## Solution

Build a replay-first vertical slice, then extend the same runtime through simulated trading,
shared fitting/Grid quotes, local and remote shared-space adapters, a freely dockable desktop,
history, and channel integration. Validate each increment through observable behavior.
Development starts now; live activation and performance guarantees require their own evidence.

This spec consolidates accepted requirements. The engineering defaults below are selected
under the user's instruction to proceed to development without further excessive experiments.
They are reversible implementation choices, not claims that the user individually approved
every detail or that a prototype established production performance.

## User Stories

1. As the operator, I can start an isolated replay session and see prices and connection state without credentials.
2. As the operator, I can distinguish replay, simulation and real environments at every command and display.
3. As the operator, I can discover contracts without making every discovered contract active in a strategy.
4. As the operator, I can submit a manual order against a fixed account/contract and see its actual acknowledgement state.
5. As the operator, I can cancel an order without confusing a cancellation request with confirmed cancellation.
6. As the operator, I can see an unknown submission and its reserved risk until reconciliation resolves it.
7. As the operator, I can restart without duplicate submissions or silently forgotten fills.
8. As the operator, I can see actual account positions separately from strategy/manual attribution.
9. As the operator, I can retain unexplained positions as unattributed while including them in risk.
10. As the operator, I can transfer attribution explicitly without inventing an external trade.
11. As the operator, I can stop a strategy group, retain positions, and see remaining cancellation uncertainty.
12. As the operator, I can update one stopped strategy group without stopping independent groups.
13. As the operator, I can retain manual stops, contract pauses and risk stops through technical recovery.
14. As the operator, I can atomically edit an object's complete parameters and resolve stale-version conflicts.
15. As the operator, I can distinguish inherited values, explicit zero values and contract overrides.
16. As the operator, I can let multiple strategies share one fitting instance and apply their own risk lean.
17. As the operator, I can use automatic/manual fitting and independently lock vr/sr/cc/pc.
18. As the operator, I can trace a quote to its trigger, fitting, parameter and position versions.
19. As the operator, I can choose bounded degraded quoting or stop/cancel when fitting fails.
20. As the operator, I can see fills trigger affected quote recalculation immediately.
21. As the operator, I can use the same plugin access model for local and remote published versions.
22. As the operator, I can see a stale or incomplete remote dependency restrict only affected paths, including shared protection effects.
23. As the operator, I can inspect the reason a path cannot submit, rather than treating connectivity as trading readiness.
24. As the operator, I can freely dock, split, float and restore repeated panel instances across windows.
25. As the operator, I can link contract selections without silently changing a panel's account or strategy target.
26. As the operator, I can click a frozen ladder price with the exact displayed account, contract, side and quantity.
27. As the operator, I can close the desktop while backend strategies and alarms continue.
28. As the operator, I can reconnect and resynchronize, then explicitly re-enable desktop trading.
29. As the operator, I can inspect long historical charts, gaps and original records without blocking live execution.
30. As the operator, I can replay the complete recorded decision chain and see the first divergence.
31. As the operator, I can see passed, failed and uncovered validation per strategy/configuration/channel/product.
32. As the operator, I can install a desktop on Ubuntu or Windows and later connect to the appropriate backend node.
33. As the operator, I can distinguish measured capacity from a requested performance target.

## Implementation Decisions

### D1. Stack and ownership

- C++20 core and backend; CMake/CTest for build and behavior checks. Linux is the first backend host.
  Electron, TypeScript and Vue 3 form the Ubuntu/Windows desktop; Node 22 and npm lockfiles are
  the initial toolchain baseline. The first slice pins exact dependency versions and records them.
  Native Windows backend support is not assumed; a Windows desktop may connect to Linux/WSL.
- Each strategy group runs in its own supervised process. A fitting owner publishes shared results;
  each account execution owner serializes risk reservations, intents and channel actions. Market
  adapters, history and desktop gateway run outside strategy processes. Start with one of each
  required role; do not create a thread/process per contract or split roles further speculatively.
- Within a state owner, process events in one deterministic order. Bounded asynchronous storage and
  transport workers return completion receipts; callers never infer durability from queue acceptance.
- A supervisor issues a node generation and exclusive owner lease. The execution owner rejects stale
  generations and commands. First deployment requires verified previous-owner exit before takeover;
  distributed automatic leader election and failover are not v1 requirements.

### D2. Shared space and transport

- Keep the accepted uniform logical shared-space interface. Local read-only attachments use
  shared-memory offsets/handles, never pointer identity across machines. Network replication uses
  MsQuic as the initial candidate, an explicit versioned encoding and mutual node authentication.
  Its exact build is pinned in the remote slice. No dependency download is needed before that slice.
- Identify a record by environment, object/owner, generation, sequence and payload identity. Publish
  complete immutable versions; expose validity, source time, publication time and retained history.
  One object's atomic publication is not a multi-object transaction or a simultaneous cross-node view.
- Retain the source sequence needed by consumers; gaps, incompatible schemas, invalid owners and
  exhausted bounded buffers produce explicit restrictions. Catch-up cannot refresh old source time.
- User commands are requests to authoritative owners, not arbitrary writes to another owner's state.
  Persist stable request IDs and response mappings. Retrying an idempotent control request queries
  the original outcome; this does not authorize resending an uncertain external order.

### D3. Computational checkpoints and execution evidence

- Adopt ADR 0004: computation may run ahead of a jointly committed state/cursor. Exact input,
  configuration, algorithm version and consumed order remain recoverable. Replaying that suffix
  restores computation and never performs historical external effects.
- A published result used for trading has stable identity and retained evidence sufficient to
  reconstruct that exact version. Its producer's complete checkpoint may lag. Completion receipts
  distinguish accepted, durable, published and consumed stages.
- Trading intent, submission identity/mapping and risk reservation are recoverable before a channel
  call. Persist the possibility of submission before attempting it. Unknown outcomes retain risk
  and require reconciliation; a provably unattempted old intent is retired after restart.
- Durable stop/control records override an older computational checkpoint. Saving failure applies
  the stop in memory immediately but never falsely acknowledges its durability.
- Pending work has count and byte bounds and age-based flush triggers. Reaching a bound pauses
  further computation and dependent new orders; saved progress releases the bound. Save failure
  requires recovery/reconciliation. Independent usable cancellation/query paths remain available.
- Use checksummed/versioned local append-only recovery records and atomic consistent checkpoints.
  A successful local commit includes file and directory synchronization as required by the storage
  operation. This is local-host durability, not replicated host-loss tolerance. History storage is
  never the sole copy of execution recovery evidence.
- Prototype values (batch 8, age 2 ms, capacity 64) belong only to the initial simulation profile.
  Production values are validated configuration, with the original latency targets preserved.

### D4. Orders, risk and attribution

- Separate intent, submission attempt, channel order, fill and cancellation identities. Represent
  order state, cancellation state and reconciliation state independently. SDK return is not fill evidence.
- Enforce account, strategy-group and contract limits before reservation/submission. Include working
  orders and unknown attempts; unavailable risk inputs never become zero. Limit prices and quantities
  use validated instrument increments and currency/quantity units.
- Ordinary single-request/frequency breaches reject that request. Loss/drawdown stops remain latched
  until explicit operator recovery. Account actual position is distinct from attribution and display FX.
- Deduplicate fill events by channel-specific identity; out-of-order corrections are versioned evidence.
  Cancel/replace waits for the old outcome by default, then recomputes remaining demand from fills.
- Keep each channel's native protection scope and renewal results explicit. The shared scope can
  affect other strategies/manual orders. A missing required protection capability prevents that path
  from starting; local cancellation cannot pretend to have executed over a broken connection.
- Cross-market partial execution follows the accepted stop-new-exposure/cancel-rest/retain-filled
  positions rule. Automatic corrective trades require an explicitly configured strategy policy.

### D5. Fitting and strategy parameters

- Preserve the confirmed shared fitting / strategy-private Grid split. Fit instances default to
  underlying + expiry + explicit configuration, permitting multiple instances for the same expiry.
  Every related market event is processed; display throttling does not alter strategy event processing.
- Publish trigger identity, exact input view, fit config, curve parameters, base volatility, market IV,
  theory/Greeks, units and per-result validity. Reuse theory/Greeks only when pricing inputs match.
- Quote cycles fix fitting, strategy-parameter and selected attribution-position versions. A fill
  updates attribution once and triggers affected quotes; it does not itself refit the market curve.
- Keep the accepted inventory-volatility correction: sigma = C + a + b(Q − C) − distance×N/PTh,
  exactly once, with finite distance ≥ 0 and PTh > 0; N excludes futures hedge lots. Invalid final
  pricing volatility restricts the contract and requests cancellation; no silent clamp/disable.
- Automatic fitting solves unlocked vr/sr/cc/pc under the locked values; all locked behaves as manual.
  Hedge curve and safety-band instances have separate owners/configuration. Inventory lean cannot
  move the safety band to relax protection.
- A strategy may explicitly allow compatible, age-bounded degraded repricing with current inputs;
  it records the old successful curve and reason. It never refreshes the last successful fit time.
  Default simulation policy is stop/cancel; enabling degradation requires an explicit complete profile.
- Engineering defaults for the still-open Q71/Q72: declare model, actual/fallback input sources,
  expiry/time/year basis, rates and units explicitly; no silent fallback. Declare ownership and allowed
  override levels per field; unset inherits, zero is explicit, clearing an override restores inheritance.
- Parameter atomicity is per fit/strategy/hedge/band object. Complete validation plus expected-base
  version precedes event-boundary activation. Cross-object batch edits return per-object outcomes.
- The exact existing UMM algorithm is ported from an identified source revision plus fixtures, not
  reconstructed from prose. Its original Windows source is not in this checkout. This is an input
  gate for the numerical port, not for the platform foundation or simulated data path.

### D6. Desktop and control protocol

- Electron main owns the backend connection, credential-store access and validated IPC surface;
  renderer processes hold no trading secrets and cannot load arbitrary privileged code. Vue renders
  typed read models; the backend remains authoritative for trading, parameters and alarms.
- Start with versioned JSON control/display messages over a local WebSocket; use authenticated TLS
  for non-loopback deployments. This is separate from the shared-space binary data path. Bootstrap
  binds loopback; remote enabling needs explicit endpoint/node identity configuration.
- Envelope: protocol version, environment, session/generation, correlation ID, stream/object identity
  and sequence. Commands carry expected versions and fixed targets. Reply states distinguish received,
  rejected, applied and unknown. Snapshot + ordered deltas use a cutover sequence; gaps resnapshot
  and restrict affected actions. Do not replay buffered desktop order clicks after reconnection.
- One active desktop control session per environment is the initial policy. Reconnect starts read-only
  until snapshot and lease checks complete, then requires explicit user trading enablement. Desktop
  disconnection does not stop healthy autonomous backend strategies.
- Panel catalog and instances are separate. Use the existing freely dockable interaction, including
  five-direction targets, nested splits, floating and native-window popout. Start with Dockview as
  replaceable layout implementation, without making persisted workspace shape its public business model.
- Workspaces persist panel IDs, geometry, link groups and targets, never an enabled-trading flag.
  Main process coordinates cross-window state. Hidden panels unsubscribe from visual work and catch
  up from current snapshots; backend event records remain complete.
- Preserve accepted display budgets: ladder/chain up to 20 Hz, monitors 10 Hz, charts 5 Hz; local
  input feedback p99 ≤ 50 ms, received business-state display p99 ≤ 100 ms. Virtualize large grids,
  coalesce display values, and retain all order/fill/alarm records. Validate actual visible workloads.

### D7. History, replay and analytics

- Store raw ordered decision evidence independently from analytical projections. Replay packages bind
  build, input schema, algorithm/config versions, initial state, consumed event order and required
  shared versions. Missing packages or sequence gaps make a replay non-reproducible, not a success.
- DolphinDB remains the first analytical adapter candidate; a local fixture adapter supports initial
  development. Analytical unavailability marks charts unavailable and buffers within configured limits;
  it does not by itself disable order execution when independent recovery evidence remains healthy.
- No automatic pruning of execution evidence, replay inputs or referenced versions in v1. Storage
  pressure warns at 80% of the configured evidence budget and restricts new dependent work at 90%;
  reclaim only explicitly exported/unreferenced data after verification. These are development defaults,
  not a retention SLA. Require a budget per deployment; do not silently grow until the disk is full.
- History interface accepts series/formula version, time range, desired resolution, continuation and
  cancellation. Initial response budget: 2,000 points per series and 1 MiB per page; return min/max,
  first/last, count and gap flags where appropriate. Cursor paging exposes raw records separately.
  Snapshot/live handover uses one sequence watermark, not timestamp-only deduplication.
- Factors and P&L definitions are versioned calculation profiles containing unit, price source,
  sampling/year basis, missing-value behavior, fees and FX policy. The previously named MicroPrice,
  weighted-mid difference and theoEdge/actual Edge are not implemented from ambiguous names.
  Start chart infrastructure with explicit raw bid/ask and recorded theory/fill series; factor semantics
  receive fixtures and definition review in their own implementation ticket.

### D8. Health, alarms and configuration

- Owners publish connection, sequence completeness, source validity, generation, persistence and
  reconciliation separately. Derived readiness names all blocking dependencies. Unknown and stale
  are not healthy; a quiet market is not automatically a missing-heartbeat failure.
- Backend alarm identity combines scope, cause and generation. Track active → acknowledged-active
  → recovered, with recurrence creating a new occurrence. Acknowledgement does not resolve the fault
  or resume trading. Desktop notifications/sound are optional views of the persistent backend record.
- Capture stage timestamps, queue count/bytes/oldest age, rejected/incomplete events, save failures,
  requested/effective parameter versions and order correlations. Keep full lifecycle evidence; sample
  diagnostics with an explicit dropped-observation counter so instrumentation cannot silently block work.
- Simulation profile supplies fixed deterministic limits and logical clock values in fixtures. Live
  configurations require explicit data-age, clock-error, heartbeat, protection-renewal, risk and query
  budgets, each bound to validation evidence. Missing live values reject activation; do not substitute
  simulation values. This makes the behavior buildable without pretending to know a safe live number.

### D9. Cross-node coordination and performance

- A strategy group declares its owner node and remote dependencies. Both adapters implement the same
  shared-space contract; the desktop is never an automated-strategy relay. Account execution owners
  remain authoritative at their channel node, including final risk/authority checks.
- A remote intent carries stable identity, origin generation, dependency versions and expiry. Enforce
  expiry and scope at the execution node; duplicates query the original result. Link loss/unknown clock
  error restricts dependencies rather than resetting freshness. Do not claim atomic cross-market fills.
- Preserve p99 ≤ 1 ms / p99.9 ≤ 5 ms local complete tick-to-order targets, including fitting, risk,
  evidence saving and last required batch submission. Cross-region latency is measured separately with
  clock uncertainty; those local targets are not silently assigned to cross-region traffic.
- Test 500 contracts, 20 active instances and 100 options/two sides per group with declared input rate,
  curve sharing and fanout. Record queue growth, rejects and incomplete rounds, not just finished orders.
  Choose sustainable rates after integrated measurement; no further standalone prototype is a start gate.

### D10. Channels and activation

- Begin with replay and the in-process scripted exchange adapter. Add public Binance market data,
  then a simulated Binance execution adapter and CTP/OpenCTP replay/simulation adapter. Verify actual
  SDK/product semantics when implementing each adapter; earlier research is context, not current proof.
- Keep selected Binance BTC/ETH options and USDT perpetuals (including chosen equity-related perpetuals)
  as separate capability profiles. CTP futures/options use their actual contract and offset semantics.
  Unsupported account/product/protection combinations remain visibly unavailable.
- Backend activation checks a validation pass record covering code/configuration combination,
  adapter/product/account scope, capacity and risk configuration. In-range routine edits remain within
  that record; behavior changes/out-of-range combinations invalidate affected coverage.
- Normal real trading requires current reconciliation and explicit operator activation. The development
  tasks implement this gate, without issuing real orders or treating simulated success as account evidence.

## Testing Decisions

The primary behavioral seam is the runtime's command/event interface and observable state stream,
shared by the desktop, CLI and replay runner. Test complete paths through it. Replace only the real
sources of variability: event input, clock, storage fault injection and external channel. Keep pure
algorithm fixtures at the pricing interface; subprocess crash tests cross the persistence boundary.

- Assert quotes, intent identities, reserved risk, positions, stop reasons and visible outcomes, not
  worker counts or internal function calls. Same-build replay requires identical discrete behavior;
  numerical tolerances must be explicit and must not excuse different executable prices or risk decisions.
- Prior art: local shared-memory/recovery C++ experiments; QUIC replication and consumer checkpoint
  experiments; workbench drag/restore observations; Grid counterexamples. Reuse their behavioral cases,
  not prototype storage ABI or benchmark numbers as production promises.
- Every ticket has a runnable demo and normal/boundary/failure checks. Crash cases preserve input and
  output evidence and independently reconcile records. Validate end-to-end batching during the bounded
  checkpoint ticket, using fixed source/remote modes and both publication and trading-evidence costs.
- Finish each slice with appropriate compiler warnings, formatting/lint/type checks and meaningful
  behavior tests. Add Release capacity tests only once representative computation is connected.
- Desktop CI covers Ubuntu/Windows build and isolated renderer interactions. Actual dual 3440×1440
  screens, target servers and channel/account capabilities remain explicit deployment acceptance gates.

## Out of Scope

Full historical backtesting/P&L optimization, QMT, Direct Stocks/bStocks, portfolio margin, automatic
wallet/FX transfers, RDMA, transparent remote pointers, distributed consensus/failover and seamless
code hot-swap. These preserve earlier scope decisions; no real account operation is part of planning.

## Further Notes

Use the [readiness and source map](README.md) and [implementation tickets](issues/01-replay-desktop.md).
The archived decision issues remain historical sources; open experiment statuses do not force more
pre-development prototypes. Existing algorithm source and hardware/account evidence gate the relevant
later acceptance tasks. They do not block the first independently runnable vertical slice.
