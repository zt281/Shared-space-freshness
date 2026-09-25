# 13: Batch consumer checkpoints in the complete simulated path

**What to build:** The integrated system reduces computational checkpoint writes while retaining correct published results, trade evidence and recovery behavior.

**Blocked by:** 10 — Drive simulated orders from Grid quotes and fills, 12 — Use the same plugin interface across two nodes.

**Status:** ready-for-agent

**Assignee:** none

**Parent:** [Tyche v1 specification](../spec.md), sections D3, D9.

## Acceptance criteria

- [ ] Keep source/remote publication modes fixed and compare per-event with bounded consumer checkpoint batching in one Release build.
- [ ] Include actual result publication, intent/risk evidence saves and simulated submission eligibility in the measured path; report their stages separately.
- [ ] Use one stable and one burst workload, both with complete input accounting; record computed/saved/published progress, queue age/bytes and sync counts.
- [ ] Inject consumer crash, checkpoint/save failure and backlog while replication continues; independently verify exact replay, preserved stop and no duplicate submissions.
- [ ] Run sanitizer correctness and record the candidate verdict. A latency failure remains a failed performance target; do not weaken recovery to pass it.

## Implementation notes

This is the only planned follow-up to the checkpoint experiment. Experimental 8/2ms/64 values are a starting profile, not an SLA. Do not launch parameter sweeps unless a concrete failure requires one.

Implement only this slice. Reuse the runtime command/event seam, keep simulation isolated, and report the reproducible demo and behavior checks. Do not introduce unrelated abstractions or another prototype.
