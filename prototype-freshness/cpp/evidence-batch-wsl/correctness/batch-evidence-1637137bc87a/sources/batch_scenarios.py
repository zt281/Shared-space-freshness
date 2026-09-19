#!/usr/bin/env python3
"""Finite batch fault experiment. Pipes control faults, never carry market payloads."""
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys

from independent_scenarios import Run, Worker, canonical, write_json
from crash_scenarios import setup, consume_all, die
from audit_crash_evidence import events


def stage(publisher, *, count=4, capacity=8, gate=False):
    publisher.send("batch_open", 60000, capacity)  # drain or a full batch releases this finite test queue
    if gate:
        publisher.send("batch_gate")
    return publisher.send("batch_plan", 100, count)["proposals"]


def publication(run, point):
    publisher = setup(run)
    path = run.root / "PROTOTYPE-consumer.checkpoint"
    reader = Worker(run, "durable", "durable_create", checkpoint=path, consumer_id=51)
    reader.send("consume", 0, 1)
    proposed = stage(publisher)
    publisher.send("arm_batch_crash", 100, point)
    publisher.send("batch_send", 100)
    die(publisher, "batch_drain")
    raw = run.journal.read_bytes()
    (run.root / "journal-at-crash.bin").write_bytes(raw)
    observed = reader.send("inspect", 100)
    expected_visible = 5 if point in (5, 6) else 1
    run.check("pending_not_advertised_before_shared_commit", observed["head"] == expected_visible)
    run.check("surviving_snapshot_is_old_complete_or_explicitly_damaged",
              observed["view"]["validity"] == "damaged" if point == 5 else
              observed["view"]["version"] == (5 if point == 6 else 1))
    if point == 2:
        run.check("full_prefix_plus_half_tail_retained", len(raw) == 2 * 96 + 48)
        run.failed_start("partial_batch_recovery_rejected", role="publisher", contains="incomplete journal tail")
        run.failed_start("partial_tail_stays_latched", role="publisher", contains="previously failed")
        run.check("no_truncation_or_auto_repair", run.journal.read_bytes() == raw)
        run.check("reader_restricted_after_detected_partial_tail", not reader.send("inspect", 100)["complete"])
        return
    count = 0 if point == 0 else 1 if point == 1 else 4
    replacement = Worker(run, "replacement", "publisher", address=0x340000000000)
    run.check("confirmed_exit_allows_full_log_recovery", replacement.initial["head"] == count + 1)
    run.check("recovery_does_not_make_old_source_current", replacement.initial["authority"] == 2
              and replacement.initial["view"]["validity"] == "old_epoch")
    queried = []
    for item in proposed:
        # Cursor beyond head is explicitly incomplete, not an invented empty commit.
        queried += replacement.send("query", 100, item["sequence"], expect_ok=False)["events"]
    run.check("query_checks_exact_original_proposal_not_only_head", canonical(queried) == canonical(proposed[:count]))
    run.check("query_unknown_does_not_resubmit", run.journal.read_bytes() == raw)
    fresh = replacement.send("replace", 120)
    run.check("next_write_appends_without_replacing_recovered_tail", fresh["head"] == count + 2
              and run.journal.read_bytes()[:len(raw)] == raw)
    final = consume_all(reader, 120)
    expected = publisher.events + proposed[:count] + fresh["events"]
    run.check("durable_consumer_delivers_recovered_complete_prefix_once", canonical(reader.events) == canonical(expected)
              and final["checkpoint"]["cursor"] == count + 2)
    run.check("catchup_keeps_reconciliation_gate", not final["allowed"])
    reader.send("capture", 120)
    reader.send("reconcile", 120)
    run.check("old_recovery_stability_gate_preserved", not reader.send("inspect", 319)["allowed"]
              and reader.send("inspect", 320)["allowed"])


def gate_and_serialization(run, _):
    publisher = setup(run, 12)
    publisher.send("prepare", 90)
    reader = Worker(run, "independent_reader", "reader", address=0x330000000000)
    proposed = stage(publisher, capacity=4, gate=True)
    publisher.send("batch_send", 100)
    held = publisher.send("batch_wait", 100)
    run.check("writer_control_plane_reads_while_sync_is_blocked", held["head"] == 12 and held["view"]["version"] == 12)
    run.check("complete_pending_records_already_written_but_not_published", len(events(run.journal)) == 16)
    observed = reader.send("consume", 100, 8)
    run.check("independent_reader_gets_only_old_complete_event_during_disk_gate",
              observed["head"] == 12 and [e["sequence"] for e in observed["events"]] == list(range(1, 9))
              and observed["view"]["version"] == 12 and observed["view"]["checksum_ok"] and observed["journal_reads"] > 0)
    publisher.send("batch_legacy_start", 100)
    run.failed_start("still_alive_writer_not_replaced_during_disk_gate", role="publisher", contains="journal lease")
    run.check("legacy_append_waits_on_write_lock_without_blocking_reader",
              reader.send("inspect", 100)["head"] == 12 and len(events(run.journal)) == 16)
    publisher.send("batch_release", 100)
    final = publisher.send("batch_drain", 100)
    publisher.send("batch_legacy_join", 150)
    run.check("one_sync_confirms_four_distinct_proposals", final["batch"]["committed"] == 4
              and final["batch"]["syncs"] == 1 and all(r["state"] == 1 for r in final["receipts"]))
    run.check("acknowledgements_follow_sync_and_publication", all(
        0 < r["sync_ns"] <= r["published_ns"] <= r["confirmed_by_ns"] for r in final["receipts"]))
    run.check("stale_prepared_single_publish_is_rejected", not publisher.send("publish", 151, expect_ok=False)["ok"])
    final_read = consume_all(reader, 150)
    run.check("batch_then_legacy_append_have_no_slot_overwrite", final_read["head"] == 17
              and canonical(reader.events[12:16]) == canonical(proposed)
              and reader.events[-1]["sequence"] == 17 and reader.events[-1]["record"]["version"] == 16)
    run.check("no_half_snapshot_after_batch_release", final_read["view"]["version"] == 16
              and final_read["view"]["proof"] == 17 and final_read["view"]["validity"] == "valid")


def overflow(run, _):
    publisher = setup(run)
    reader = Worker(run, "reader", "reader")
    proposed = stage(publisher, count=6, capacity=4, gate=True)
    publisher.send("batch_send", 100)
    held = publisher.send("batch_wait", 100)
    run.check("bounded_queue_counts_inflight_and_explicitly_rejects_overflow", held["batch"]["accepted"] == 4
              and held["batch"]["rejected"] == 2 and held["batch"]["max_pending"] == 4)
    run.check("queue_overflow_restricts_shared_source_before_drain", reader.send("inspect", 100)["view"]["validity"] == "gap")
    publisher.send("batch_release", 100)
    final = publisher.send("batch_drain", 100)
    run.check("accepted_prefix_drains_rejected_suffix_is_not_committed", [r["state"] for r in final["receipts"]] == [1]*4+[0]*2
              and [r["accepted"] for r in final["receipts"]] == [True]*4+[False]*2 and final["head"] == 5)
    final_read = consume_all(reader, 100)
    run.check("accepted_full_tail_remains_auditable_despite_gap", canonical(reader.events[1:]) == canonical(proposed[:4]))
    run.check("input_gap_does_not_disappear_after_successful_drain", not final_read["allowed"]
              and final_read["view"]["validity"] == "gap")
    before = run.journal.read_bytes()
    publisher.send("replace", 120)
    run.check("old_replace_cannot_silently_repair_queue_gap", run.journal.read_bytes() == before)
    publisher.exit()
    replacement = Worker(run, "replacement", "publisher")
    replacement.send("replace", 140)
    run.check("takeover_keeps_required_input_gap_restricted", replacement.send("inspect", 140)["head"] == 5
              and not reader.send("inspect", 140)["allowed"])


def sync_failure(run, _):
    publisher = setup(run)
    reader = Worker(run, "reader", "reader")
    stage(publisher)
    publisher.send("arm_batch_sync_failure", 100)
    publisher.send("batch_send", 100)
    final = publisher.send("batch_drain", 100)
    raw = run.journal.read_bytes()
    run.check("failed_sync_is_unknown_not_committed", final["head"] == 1 and final["batch"]["unknown"] == 4
              and [r["state"] for r in final["receipts"]] == [2]*4)
    run.check("full_unknown_tail_preserved_for_investigation", len(events(run.journal)) == 5)
    run.check("unknown_outcome_cannot_be_sent_twice", not publisher.send("batch_send", 100, expect_ok=False)["ok"]
              and run.journal.read_bytes() == raw)
    run.check("failed_confirmation_blocks_all_shared_dependents", not reader.send("inspect", 100)["complete"])
    publisher.exit()
    run.failed_start("detected_io_failure_not_auto_repaired_by_takeover", role="publisher", contains="previously failed")
    run.check("investigation_retains_exact_unknown_bytes", run.journal.read_bytes() == raw)


def ordered(run, _):
    publisher = setup(run)
    reader = Worker(run, "reader", "durable_create", checkpoint=run.root / "PROTOTYPE-consumer.checkpoint", consumer_id=52)
    proposed = stage(publisher, count=24, capacity=32)
    publisher.send("batch_send", 100)
    final = publisher.send("batch_drain", 100)
    consumed = consume_all(reader, 100)
    run.check("multiple_batches_preserve_every_proposal_in_order", canonical(reader.events[1:]) == canonical(proposed))
    run.check("ring_wrap_and_archive_read_preserve_full_payloads", consumed["journal_reads"] > 0
              and consumed["checkpoint"]["cursor"] == 25 and len(events(run.journal)) == 25)
    run.check("batch_sync_is_not_per_event_wrapping", final["batch"]["syncs"] == 3 and final["batch"]["committed"] == 24)
    run.check("processing_state_still_saved_each_event", consumed["checkpoint"]["revision"] == 26)


def rejected_before_write(run, _):
    publisher = setup(run)
    proposed = stage(publisher)
    publisher.send("verify", 90)  # Serialized old entrance advances the slot, not the queued proposal.
    raw = run.journal.read_bytes()
    publisher.send("batch_send", 100)
    final = publisher.send("batch_drain", 100)
    run.check("obsolete_proposal_rejected_before_disk_attempt", final["batch"]["unknown"] == 0
              and [r["state"] for r in final["receipts"]] == [0]*4 and run.journal.read_bytes() == raw)
    run.check("queued_identity_is_not_silently_renumbered", [(r["sequence"], r["seal"]) for r in final["receipts"]]
              == [(p["sequence"], p["seal"]) for p in proposed])
    run.check("rejected_required_input_leaves_source_restricted", final["view"]["validity"] == "gap")


def main():
    binary, root = [Path(v).resolve() for v in sys.argv[1:]]
    root.mkdir()
    sources = root / "sources"
    sources.mkdir()
    for source in Path(__file__).resolve().parent.iterdir():
        if source.suffix in {".cpp", ".hpp", ".py", ".cmake"} or source.name == "CMakeLists.txt":
            shutil.copyfile(source, sources / source.name)
    (root / "manifest.json").write_text(json.dumps({"platform": platform.platform(), "binary": str(binary),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "sources": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources.iterdir()},
        "scope": "local process faults only; no power-loss or real order guarantee"}, indent=2)+"\n")
    cases = [(f"batch-crash-{p}", publication, p) for p in range(7)]
    cases += [("sync-gate-and-serialization", gate_and_serialization, None),
              ("queue-overflow", overflow, None), ("sync-failure", sync_failure, None),
              ("batch-order", ordered, None), ("rejected-before-write", rejected_before_write, None)]
    summary = []
    try:
        for name, scenario, argument in cases:
            run = Run(binary, root / name)
            print("CASE " + name, flush=True)
            try:
                scenario(run, argument)
            finally:
                summary.append({"case": name, "checks": run.checks})
                run.cleanup()
    finally:
        (root / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print("TOTAL " + str(sum(len(c["checks"]) for c in summary)) + " batch checks", flush=True)


if __name__ == "__main__":
    main()
