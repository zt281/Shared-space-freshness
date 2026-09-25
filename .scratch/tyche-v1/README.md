# Tyche: ready to start development

On 2026-09-25 the user requested continuing until development is ready, without excessive
experiments or discussion. The result is an implementation baseline and ordered tickets.
No further interview or standalone prototype is required to start. This is development
readiness, not a claim that the software, capacity or real trading is ready.

## Start here

1. Read the [specification](spec.md).
2. Implement [Replay prices into a read-only desktop](issues/01-replay-desktop.md).
3. Work the [ticket frontier](ticket-index.md): claim one slice whose blockers are complete,
   implement and validate it, then take the next slice in a fresh context.

First deliver a desktop connected to an isolated C++ replay backend, then simulated trading
that recovers correctly. Shared fitting/Grid, remote operation and channel integration extend
the same runtime interfaces.

## Readiness checks

| Check | Result |
| --- | --- |
| Product scope and first delivery | Explicit; replay and simulation first. |
| Backend/desktop ownership choices | Development defaults selected in spec D1–D10. |
| Recovery behavior | Accepted contracts preserved; prototype evidence retained. |
| First runnable slice | Ticket 01 has no blockers, account, SDK or algorithm-source requirement. |
| Test seam | Runtime command/event interface with input, clock, storage-fault and channel adapters. |
| Implementation breakdown | 25 tickets with acceptance criteria and explicit blocking edges. |
| Further experiments | Integrated batching and capacity are development acceptance, not pre-build gates. |

## Remaining inputs and release gates

| Item | When it matters | Action |
| --- | --- | --- |
| Existing UMM source/reference fixtures | Numerical port | Obtain the identified source/package at ticket 08; do not invent it from prose. |
| Named factor definitions | Analytics series | Pin formula, units and fixtures at ticket 17; raw history/chart work can proceed. |
| SDKs and simulation access | CTP/Binance adapters | Pin and verify in tickets 19/20; separate fixtures from external simulation evidence. |
| Actual account rights/native protection | Real activation | Verify per account/product; no simulation substitution. |
| Data-age/risk/clock/storage budgets | Deploying a profile | Require explicit validated values; simulation values stay development-only. |
| Two screens and target hosts | Capacity/release acceptance | Measure in tickets 23–25; preserve uncovered status meanwhile. |

Ordinary coding can proceed without another design approval. A later genuine business ambiguity
requires only a targeted decision, while independent work continues. Planning does not authorize
account operations, external deployment or real orders.

## Disposition of the old decision map

The [architecture map](../tyche-architecture/map.md) and comments remain primary sources.
Existing agents' claims are not reassigned or falsely closed. Historical open experiment
statuses do not make every experiment a prerequisite for coding.

| Earlier topic | Development disposition |
| --- | --- |
| [Backend architecture](../tyche-architecture/issues/08-backend-architecture.md) | D1–D4/D9 fix the build baseline: local, remote, then integrated batching. |
| [Frontend architecture](../tyche-architecture/issues/09-frontend-architecture.md) | D6 fixes ownership, synchronization and interaction baseline. |
| [Implementation roadmap](../tyche-architecture/issues/10-architecture-roadmap.md) | This spec and ticket DAG supply the build route and separate acceptance gates. |
| [Option algorithm](../tyche-architecture/issues/14-option-pricing-model.md) | Preserve accepted Q53–Q70; Q71/Q72 use explicit-source/override engineering defaults. Exact port needs source/fixtures. |
| [Pricing capacity](../tyche-architecture/issues/15-pricing-capacity-prototype.md) | Integrated acceptance; original targets unchanged. |
| [Workbench prototype](../tyche-architecture/issues/18-workbench-prototype.md) | Adopt latest free Dock direction; remaining interaction and actual screen checks happen during development. |
| [History contract](../tyche-architecture/issues/19-factor-history-contract.md) | D7 defines recovery/analytics separation and query/retention behavior; factors have a bounded definition ticket. |
| [Runtime diagnostics](../tyche-architecture/issues/20-runtime-observability-alerts.md) | D8 defines health, alarms and required deployment profiles. |
| [Cross-market cooperation](../tyche-architecture/issues/25-cross-market-strategy-budget.md) | D9 defines owners, remote intents and freshness; cross-region numbers remain measured deployment data. |

## Requirement sources

- ADRs: [strategy-group lifecycle](../../docs/adr/0001-strategy-group-lifecycle.md),
  [uniform shared space](../../docs/adr/0002-unified-shared-space.md),
  [shared fitting/private quotes](../../docs/adr/0003-shared-fitting-independent-quotes.md),
  [checkpoint/trading evidence](../../docs/adr/0004-consumer-checkpoint-and-trading-evidence.md).
- Product decisions: [deployment](../tyche-architecture/issues/01-deployment-lifecycle.md),
  [performance](../tyche-architecture/issues/04-strategy-performance.md),
  [workbench](../tyche-architecture/issues/05-workbench-workflow.md),
  [domain](../tyche-architecture/issues/06-market-domain-model.md),
  [orders/risk](../tyche-architecture/issues/07-order-risk-recovery.md),
  [Binance scope](../tyche-architecture/issues/12-binance-scope.md),
  [validation](../tyche-architecture/issues/16-strategy-validation-scope.md),
  [stock-related access](../tyche-architecture/issues/23-stock-short-selling-access.md).
- Historical API/SDK research is context; verify actual versions and account capabilities when
  implementing/accepting each adapter.

## Prototype evidence and stopping rule

- Checkpoint prototype: `prototype/consumer-checkpoint-recovery`, code/evidence `4259f2d0`,
  verdict `38c9bfb8`, directory `prototype-freshness/consumer-checkpoint`. Final Release and
  UBSan each passed 853 assertions and independent decoding of 37 scenario directories and
  1,200 timed events. The 85% sync reduction excludes publication/order-evidence/network costs.
- Original local/QUIC and combined batching evidence remains in the [prototype documentation](../../prototype-freshness/README.md)
  and [network results](../../prototype-freshness/network/REMOTE-COMBO.md).
- Workbench branch `prototype/workbench`, latest observed commit `627560fe`, supplies interaction
  evidence; its old capacity figures are not production guarantees.
- Next checkpoint measurement: ticket 13 on the integrated development path. One stable and one
  burst workload plus listed faults suffice. Expand only to diagnose a concrete failure; do not
  reopen settled requirements or weaken durability to make a performance target pass.

## Local tracker convention

`ready-for-agent` means sufficiently specified, not dependencies complete. A ticket is runnable
when its numbered blockers and explicit external input gate are satisfied. Set Assignee and
Status to `in-progress` when claiming, `done` after behavior checks pass, or `blocked` with the
specific missing input. Attach evidence and the actual demo/run command. These generated tickets
need no triage pass. The user delegated ordinary sequencing/granularity, so a separate approval
round for the ticket breakdown is unnecessary.
