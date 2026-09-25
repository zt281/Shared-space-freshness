# Consumer checkpoint and recovery experiment — disposable C++ prototype

Question: can a consumer checkpoint several computed events together, recover its exact
state after a process crash, and keep order/stop recovery evidence independent?

The user confirmed the [contract](../../.scratch/tyche-architecture/analysis/consumer-checkpoint-contract.md)
and explicitly requested C++ experiments instead of an HTML demo.
This directory belongs on `prototype/consumer-checkpoint-recovery`, not production.
The original `cpp/DurableConsumer` and QUIC experiment remain separate baselines.

## Run

Requires Linux on a little-endian machine, a C++20 compiler (`c++`), Python 3.9+, and a
local filesystem supporting `fdatasync`, `rename` and directory `fsync`. No external
dependencies, credentials or trading connections. Run from the repository root:

```sh
python3 prototype-freshness/consumer-checkpoint/run.py
python3 prototype-freshness/consumer-checkpoint/run.py --sanitize
```

Each invocation builds a new executable and creates a new evidence directory. The second
command uses UndefinedBehaviorSanitizer; run it after the first completes to avoid
contaminating timings. `--output NEW_DIRECTORY` selects an explicit unused location.
The standalone C++ executable receives that directory as its only argument.

`experiment.cpp` contains the synthetic consumer and subprocess scenarios. `run.py`
captures the compiler, platform, filesystem, commands, source snapshots, executable
hash and output. `audit.py` independently decodes the saved records and recomputes
state, event identities, simulated submission counts and timing statistics:

```sh
python3 prototype-freshness/consumer-checkpoint/audit.py \
  prototype-freshness/consumer-checkpoint/evidence-release-02
```

## Model and acceptance checks

- Every input retains its sequence, price, quantity, parameter and fitting value.
  The calculation version is explicit. Saved state contains version, cursor, sum
  and order-sensitive digest; replay reconstructs the same prefix. Retained data
  is never pruned during this experiment.
- A checkpoint uses complete staging write → file synchronization → atomic rename
  → directory synchronization → in-memory acknowledgement. Child processes exit
  at six boundaries including unfinished computation, partial write and lost
  acknowledgement. Pending files are retained, never substituted for the canonical file.
- An order intent independently records environment, consumer/cycle identity,
  exact input digest, calculation digest and synthetic risk quantity. The durable
  `possibly sent` state precedes a mock external call. Recovery retires unattempted
  old intents, holds uncertain attempts for query, and never creates intents during replay.
  The mock receiver increments its call count without deduplicating retries.
- Stops are immediately enforced and independently saved; a lagging computation
  checkpoint cannot erase an acknowledged stop. Failed stop saving returns failure,
  keeps the current process restricted, and does not promise the unacknowledged
  stop survived a crash.
- A published result is saved independently of the producer checkpoint. A downstream
  record references that exact result. Publication crash cases expose only the
  canonical result, revalidate/resynchronize it on recovery, and replay reproduces
  the downstream version. A staged-only result is unavailable to the downstream reader.
- Pending-event and pending-byte bounds reject further computation. Saving catches
  up before work resumes. Elapsed time also triggers a partial-batch save. ENOSPC
  before writing and EIO after rename are injected as explicit errors, for both
  checkpoint and trading-evidence saves. Failure latches dependent trading off.
- Missing, corrupt, wrong-version or mismatched recovery evidence rejects startup;
  it never becomes an empty checkpoint. Fresh reconciliation is required after
  restart; replay alone grants no permission. Unknown attempts and saved stops
  continue to restrict trading after catch-up.

The 37 scenario directories include six timing cases. `checks.jsonl` records individual
assertions; `observations.jsonl` records computed/saved state and permission flags where
applicable. Canonical binary records and crash snapshots allow an independent decoder
to verify state instead of trusting assertions alone. The sum/digest calculation is
synthetic, not an option-pricing implementation.

## Results

The final Release run [evidence-release-02](evidence-release-02/audit.json) passed
853 assertions and independent verification of 37 scenarios and 1,200 timed events.
Assertions include per-flush checks, not 853 distinct fault scenarios.
The separate [UBSan run](evidence-ubsan-01/audit.json) also passed all 853 assertions
and independent verification, with no sanitizer diagnostics. Its timings are not
pooled with Release results.

The Release timing cases alternate mode order across three rounds using the same binary,
filesystem, inputs and save protocol. Each case schedules 200 events at absolute times:
20 events every 100 ms, starting at 0 ms; delayed input is not rescheduled. The baseline
saves each event. The candidate saves at eight pending events or a two-millisecond age
trigger, with a final drain. Two milliseconds is a trigger, not a disk-latency ceiling.

| Measure, per 200-event run | Per-event checkpoint | Batch checkpoint |
| --- | ---: | ---: |
| Checkpoint commits | 200 | 30 |
| File + directory synchronization calls | 400 | 60 |
| Maximum pending events | 1 | 8 |
| Median planned-input → durable latency, across rounds | 269.07–287.11 ms | 13.29–13.83 ms |
| p99 planned-input → durable latency, across rounds | 481.86–537.50 ms | 29.95–35.24 ms |
| Maximum planned-input → durable latency, across rounds | 494.92–550.61 ms | 29.95–35.24 ms |

All timed cases finish with the same complete state, with no rejected or missing inputs.
The candidate reduces checkpoint commits/synchronization calls by 85% in this workload.
Per-event observations and independently recalculated statistics are retained. The earlier
`evidence-release-01` is a preliminary run before adding trading-evidence save failures
and state observations; its timings are not pooled with the final run.
Timing includes the experiment's observation/check logging overhead; no attempt was
made to subtract instrumentation cost.

Verdict: **the agreed separation and batch-checkpoint rules pass the tested local
process-crash cases and reduce checkpoint overhead in this synthetic workload.**
The design can proceed to integration with the existing consumer/QUIC experiment.

## Limits that remain relevant to the contract

- This is one sequential consumer/writer per scenario, one environment and one intent
  slot. Concurrent ownership, takeover fencing, multiple orders, mixed consumers,
  real risk reservation/release and real broker reconciliation are not implemented.
  The query mock proves one recorded submission; an absent record leaves an attempt unknown.
  Real cancellations and exchange connectivity are outside the experiment.
- Published results use their own durable save. The timing workload measures **pure
  computation checkpointing**, without per-result publication, order-evidence writes,
  network traffic, fitting, risk calculations or real trading. The same speedup is
  not established for the full chain; result/evidence writes could dominate it.
- Source inputs are fully retained and loaded before timing; historical prefix validation
  is linear. The byte bound covers unsaved logical input work (40 bytes per event),
  not process RSS or storage. Retention/garbage collection and replay throughput remain open.
- Child `_exit` exercises process death on a surviving Linux host. It does not prove
  behavior under power loss, kernel crash, storage-device failure or remote replication.
  ENOSPC/EIO are controlled error injections, not destructive physical disk tests.
- Three finite runs on an unisolated Ubuntu/ext4 host do not establish a production
  tail percentile, sustained capacity, the 1 ms/5 ms targets, or a comparison with the
  historical WSL/QUIC measurements. Batch eight, age two milliseconds and pending
  capacity 64 are experiment settings, not accepted production parameters.

Production readiness requires integration and validation of those boundaries. This
experiment confirms a candidate mechanism; it does not close the entire backend issue.
