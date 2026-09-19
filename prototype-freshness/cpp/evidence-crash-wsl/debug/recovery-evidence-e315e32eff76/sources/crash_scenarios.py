#!/usr/bin/env python3
"""Process-crash recovery experiment; business events never enter control pipes."""
import hashlib
import json
from pathlib import Path
import platform
import shutil
import struct
import sys

from independent_scenarios import Run, Worker, canonical, write_json


def die(worker, action, now=100, budget=0):
    try:
        worker.send(action, now, budget)
        raise AssertionError("expected process death before reply")
    except EOFError:
        pass
    code = worker.process.wait(timeout=10)
    write_json(worker.records, {"kind": "exit", "pid": worker.process.pid, "code": code})
    worker.run.check(worker.label + "_actual_abrupt_exit", code == 77)


def setup(run, count=1):
    owner = Worker(run, "creator", "create")
    run.check("exclusive_region_created", owner.initial["ok"])
    run.created_names.add(run.name)
    owner.exit()
    publisher = Worker(run, "publisher", "publisher", address=0x310000000000)
    publisher.send("replace", 0)
    for sequence in range(2, count + 1):
        publisher.send("prepare", sequence * 10)
        publisher.send("publish", sequence * 10)
    return publisher


def consume_all(reader, now):
    while reader.send("inspect", now)["backlog"]:
        reader.send("consume", now, 8)
    return reader.send("inspect", now)


def publication(run, point):
    publisher = setup(run, 9)
    fast = Worker(run, "fast", "reader", address=0x320000000000)
    slow = Worker(run, "slow", "reader", address=0x330000000000)
    consume_all(fast, 90)
    publisher.send("prepare", 100)
    if point < 8:
        publisher.send("arm_publication_crash", 100, point)
    die(publisher, "publish_reply_crash" if point == 8 else "publish")
    saved = run.journal.read_bytes()
    (run.root / "journal-at-crash.bin").write_bytes(saved)
    damaged = fast.send("inspect", 100)
    if point == 8:
        run.check("lost_reply_leaves_complete_publication", damaged["complete"] and damaged["head"] == 10)
    else:
        run.check("survivor_restricted_before_recovery", not damaged["allowed"] and not damaged["complete"])
    if point == 1:
        run.failed_start("partial_tail_rejected", role="publisher", contains="incomplete journal tail")
        run.failed_start("record_failure_remains_latched", role="publisher", contains="previously failed")
        run.check("partial_tail_evidence_unchanged", run.journal.read_bytes() == saved)
        run.check("all_record_dependents_restricted", not fast.send("inspect", 120)["complete"]
                  and not slow.send("inspect", 120)["complete"])
        return
    replacement = Worker(run, "replacement", "publisher", address=0x340000000000)
    count = 9 if point == 0 else 10
    run.check("head_rebuilt_from_complete_log", replacement.initial["head"] == count)
    run.check("new_authority_does_not_refresh_old_data", replacement.initial["authority"] == 2
              and replacement.initial["view"]["epoch"] == 1
              and replacement.initial["view"]["verified_ms"] == (90 if point == 0 else 100)
              and replacement.initial["view"]["validity"] == "old_epoch")
    query = replacement.send("query", 100, 10)
    run.check("uncertain_publish_result_is_queryable", len(query["events"]) == (0 if point == 0 else 1))
    if point != 0:
        event = query["events"][0]
        run.check("recovered_event_matches_original_proposal", event["sequence"] == 10
                  and event["record"]["epoch"] == 1 and event["record"]["version"] == 10
                  and event["record"]["price"] == 110 and event["record"]["quantity"] == 10
                  and event["record"]["verified_ms"] == 100)
    # Query output is excluded from publisher.events below: it is not another publication.
    fresh = replacement.send("replace", 120)
    run.check("next_publication_appends_instead_of_overwriting", fresh["head"] == count + 1
              and run.journal.read_bytes()[:len(saved)] == saved)
    expected = publisher.events + query["events"] + fresh["events"]
    fast_state = consume_all(fast, 120)
    slow_state = consume_all(slow, 120)
    run.check("surviving_fast_consumer_receives_every_committed_event", canonical(fast.events) == canonical(expected))
    run.check("lagging_consumer_receives_every_committed_event", canonical(slow.events) == canonical(expected)
              and slow_state["journal_reads"] > 0)
    run.check("catchup_does_not_replace_reconciliation", not fast_state["allowed"])
    fast.send("capture", 120)
    fast.send("reconcile", 120)
    run.check("restart_stability_gate", not fast.send("inspect", 319)["allowed"]
              and fast.send("inspect", 320)["allowed"])


def corrupt_log(run, mode):
    publisher = setup(run, 9)
    reader = Worker(run, "reader", "reader")
    publisher.exit(abrupt=True)
    original = run.journal.read_bytes()
    (run.root / "journal-before-corruption.bin").write_bytes(original)
    if mode == "short":
        changed = original[:len(original) * 8 // 9]
    else:
        changed = bytearray(original)
        changed[0 if mode == "sequence" else len(changed) - 1] ^= 1
    run.journal.write_bytes(changed)  # Only this run's exclusive PROTOTYPE journal.
    run.failed_start("corrupt_history_rejected", role="publisher",
                     contains="shorter than" if mode == "short" else "invalid recovery")
    run.check("corrupt_history_preserved", run.journal.read_bytes() == changed)
    run.check("corrupt_history_blocks_dependent_reader", not reader.send("inspect", 100)["complete"])


def checkpoint(run, point):
    publisher = setup(run)
    path = run.root / "PROTOTYPE-consumer.checkpoint"
    reader = Worker(run, "before_crash", "durable_create", checkpoint=path, consumer_id=41)
    reader.send("consume", 0, 1)
    reader.send("stop", 0)
    for sequence in range(2, 14):
        publisher.send("prepare", sequence * 10)
        publisher.send("publish", sequence * 10)
    reader.send("arm_checkpoint_crash", 130, point)
    die(reader, "consume", 130, 1)
    shutil.copyfile(path, run.root / "checkpoint-at-crash.bin")
    restarted = Worker(run, "after_crash", "durable", checkpoint=path, consumer_id=41, startup_tick=130)
    restored = restarted.initial["checkpoint"]
    expected_cursor = 1 if point <= 3 else 2
    run.check("result_and_cursor_restore_together", restored["cursor"] == expected_cursor
              and restored["processed"] == expected_cursor
              and restored["quantity_sum"] == expected_cursor * (expected_cursor + 1) // 2
              and restored["price_sum"] == expected_cursor * 100 + restored["quantity_sum"])
    run.check("user_stop_survives_process_crash", restored["stopped"] == 1 and not restarted.initial["allowed"])
    finished = consume_all(restarted, 130)
    state = finished["checkpoint"]
    chain = 1469598103934665603
    for event in publisher.events:
        chain = ((chain ^ event["seal"]) * 1099511628211) & ((1 << 64) - 1)
    run.check("aggregate_has_no_loss_or_double_count", state["cursor"] == 13 and state["processed"] == 13
              and state["quantity_sum"] == 91 and state["price_sum"] == 1391 and state["chain"] == chain)
    run.check("restart_replays_only_after_checkpoint", [e["sequence"] for e in restarted.events]
              == list(range(expected_cursor + 1, 14)) and finished["journal_reads"] > 0)
    run.check("catchup_still_requires_current_reconciliation", not restarted.send("resume", 130)["allowed"])
    restarted.send("stop", 130)
    restarted.send("capture", 130)
    restarted.send("reconcile", 130)
    run.check("reconciliation_cannot_clear_persisted_stop", not restarted.send("inspect", 330)["allowed"])
    run.check("explicit_resume_after_all_gates", restarted.send("resume", 330)["allowed"])
    run.check("event_replay_has_no_mock_submissions", not Path(str(path) + ".simulated-submissions.jsonl").exists())


def ready(reader, now):
    consume_all(reader, now)
    reader.send("capture", now)
    reader.send("reconcile", now)
    reader.run.check(reader.label + "_stable_ready", reader.send("inspect", now + 200)["allowed"])


def control_recovery(run, point):
    setup(run)
    path = run.root / "PROTOTYPE-consumer.checkpoint"
    reader = Worker(run, "pending", "durable_create", checkpoint=path, consumer_id=42)
    ready(reader, 0)
    pending = reader.send("issue", 200)["checkpoint"]
    reader.exit(abrupt=True)
    retired = Worker(run, "retired", "durable", checkpoint=path, consumer_id=42, startup_tick=210)
    run.check("pending_intent_retired_without_extending_authorization",
              retired.initial["checkpoint"]["intent_outcome"] == 6
              and retired.initial["checkpoint"]["intent_expires"] == pending["intent_expires"])
    run.check("retired_intent_never_executes", retired.send("execute", 210)["outcome"] == "no_resubmit")
    ready(retired, 210)
    retired.send("issue", 410)
    retired.send("arm_checkpoint_crash", 420, point)
    die(retired, "execute", 420)
    restarted = Worker(run, "uncertain", "durable", checkpoint=path, consumer_id=42, startup_tick=430)
    run.check("unknown_attempt_survives_restart", restarted.initial["checkpoint"]["intent_outcome"] == 2)
    ready(restarted, 430)
    run.check("unknown_attempt_cannot_be_reissued", not restarted.send("issue", 630, expect_ok=False)["ok"])
    run.check("unknown_attempt_cannot_be_resubmitted", restarted.send("execute", 630)["outcome"] == "no_resubmit")
    external = Path(str(path) + ".simulated-submissions.jsonl")
    submissions = [json.loads(line) for line in external.read_text().splitlines()] if external.exists() else []
    run.check("external_mock_observed_at_most_once", len(submissions) == (0 if point == 7 else 1))


def checkpoint_failures(run):
    publisher = setup(run)
    path = run.root / "PROTOTYPE-consumer.checkpoint"
    reader = Worker(run, "owner", "durable_create", checkpoint=path, consumer_id=43)
    ready(reader, 0)
    run.failed_start("duplicate_checkpoint_owner", role="durable", checkpoint=path, consumer_id=43,
                     contains="already owned")
    reader.exit()
    run.failed_start("wrong_consumer_identity", role="durable", checkpoint=path, consumer_id=44,
                     contains="identity mismatch")
    run.failed_start("missing_checkpoint_is_not_empty_start", role="durable",
                     checkpoint=run.root / "PROTOTYPE-missing", contains="open checkpoint file")
    run.failed_start("cannot_initialize_over_existing_progress", role="durable_create", checkpoint=path,
                     contains="already exists")
    for mode in ("partial", "checksum", "ahead", "history"):
        bad_path = run.root / ("PROTOTYPE-bad-" + mode)
        raw = path.read_bytes()
        if mode == "partial":
            raw = raw[:len(raw) // 2]
        elif mode == "checksum":
            raw = raw[:-1] + bytes([raw[-1] ^ 1])
        else:
            values = list(struct.unpack("<16Q", raw))  # Verified x86_64 local prototype layout.
            if mode == "ahead":
                values[5] = values[6] = 2
            else:
                values[7] ^= 1
            value = 1469598103934665603
            for field in values[:-1]:
                value = ((value ^ field) * 1099511628211) & ((1 << 64) - 1)
            values[-1] = value
            raw = struct.pack("<16Q", *values)
        bad_path.write_bytes(raw)
        run.failed_start("checkpoint_" + mode + "_rejected", role="durable", checkpoint=bad_path, consumer_id=43,
                         contains={"partial": "length", "checksum": "invalid checkpoint", "ahead": "ahead",
                                   "history": "does not match"}[mode])
    reader = Worker(run, "io_failure", "durable", checkpoint=path, consumer_id=43, startup_tick=210)
    ready(reader, 210)
    revision = reader.send("inspect", 410)["checkpoint"]["revision"] + 1
    collision = Path(str(path) + f".pending-{reader.process.pid}-{revision}")
    collision.write_bytes(b"PROTOTYPE injected staging collision, not a disk-full test\n")
    run.check("checkpoint_save_failure_not_acknowledged", not reader.send("issue", 410, expect_ok=False)["ok"])
    run.check("checkpoint_save_failure_blocks_submission", reader.send("execute", 410)["outcome"] == "not_ready"
              and not reader.send("inspect", 410)["allowed"])
    healthy = Worker(run, "healthy_other_group", "reader")
    ready(healthy, 410)
    run.check("private_checkpoint_failure_does_not_poison_shared_log", healthy.send("inspect", 610)["complete"])
    run.check("failed_checkpoint_did_not_submit", not Path(str(path) + ".simulated-submissions.jsonl").exists())
    run.check("shared_publisher_remains_healthy", publisher.send("inspect", 610)["view"]["validity"] == "valid")


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: crash_scenarios.py WORKER NEW_EVIDENCE_DIRECTORY")
    binary, root = map(lambda value: Path(value).resolve(), sys.argv[1:])
    root.mkdir()
    sources = root / "sources"
    sources.mkdir()
    for source in Path(__file__).resolve().parent.iterdir():
        if source.suffix in {".cpp", ".hpp", ".py", ".cmake"} or source.name == "CMakeLists.txt":
            shutil.copyfile(source, sources / source.name)
    (root / "manifest.json").write_text(json.dumps({
        "platform": platform.platform(), "python": sys.version, "binary": str(binary),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "sources": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources.iterdir()},
        "scope": "local independent processes; injected clock; simulated external submissions; no host power loss",
    }, indent=2) + "\n")
    cases = [("publication-" + str(p), publication, p) for p in range(9)]
    cases += [("corrupt-" + mode, corrupt_log, mode) for mode in ("short", "sequence", "seal")]
    cases += [("checkpoint-" + str(p), checkpoint, p) for p in range(7)]
    cases += [("control-" + str(p), control_recovery, p) for p in (7, 8)]
    cases += [("checkpoint-failures", lambda run, _: checkpoint_failures(run), None)]
    summary = []
    try:
        for label, scenario, argument in cases:
            print("CASE " + label, flush=True)
            run = Run(binary, root / label)
            try:
                scenario(run, argument)
            finally:
                summary.append({"case": label, "checks": run.checks})
                run.cleanup()
    finally:
        (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("TOTAL " + str(sum(len(case["checks"]) for case in summary)) + " recovery checks", flush=True)


if __name__ == "__main__":
    main()
