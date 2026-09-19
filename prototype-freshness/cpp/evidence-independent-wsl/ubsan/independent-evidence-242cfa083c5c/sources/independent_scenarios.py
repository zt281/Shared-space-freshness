#!/usr/bin/env python3
"""Disposable deterministic experiment; child business data comes only from Space."""
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid


def write_json(stream, value):
    stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    stream.flush()


class Worker:
    def __init__(self, run, label, role, *, identity=None, name=None, journal=None, address=0):
        self.run, self.label = run, label
        self.interactive = role in {"create", "reader", "publisher"}
        self.events = []
        self.records = (run.root / (label + ".jsonl")).open("x", encoding="utf-8")
        self.errors = (run.root / (label + ".stderr.txt")).open("x", encoding="utf-8")
        self.messages = queue.Queue()
        command = [str(run.binary), role, name or run.name, str(journal or run.journal),
                   str(run.identity if identity is None else identity), hex(address)]
        write_json(self.records, {"kind": "launch", "command": command, "role": role})
        # exec starts a fresh program; no inherited business mapping or journal fd.
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.errors, text=True, close_fds=True)
        run.workers.append(self)

        def read_output():
            try:
                for line in self.process.stdout:
                    self.messages.put(json.loads(line))
            except Exception as error:
                self.messages.put(error)
            finally:
                self.messages.put(EOFError("worker output closed"))

        threading.Thread(target=read_output, daemon=True).start()
        self.initial = self.receive()

    def receive(self):
        response = self.messages.get(timeout=10)
        if isinstance(response, Exception):
            raise response
        write_json(self.records, {"kind": "response", **response})
        self.events.extend(response.get("events", []))
        return response

    def send(self, action, now=0, budget=0, expect_ok=True):
        write_json(self.records, {"kind": "command", "action": action, "logical_ms": now, "budget": budget})
        self.process.stdin.write(f"{action} {now} {budget}\n")
        self.process.stdin.flush()
        response = self.receive()
        if expect_ok and not response["ok"]:
            raise AssertionError(f"{self.label}/{action}: {response}")
        return response

    def exit(self, abrupt=False):
        if self.process.poll() is None and self.interactive and self.initial["ok"]:
            action = "exit_abrupt" if abrupt else "quit"
            write_json(self.records, {"kind": "command", "action": action})
            self.process.stdin.write(f"{action} 0 0\n")
            self.process.stdin.flush()
        result = self.process.wait(timeout=10)
        write_json(self.records, {"kind": "exit", "pid": self.process.pid, "code": result})
        return result


class Run:
    def __init__(self, binary, root):
        self.binary, self.root = binary.resolve(), root.resolve()
        self.root.mkdir()  # Refuse to overwrite existing evidence.
        self.identity = uuid.uuid4().int & ((1 << 63) - 1)
        self.name = f"/tyche-independent-{os.getpid()}-{self.identity}"
        self.journal = self.root / "PROTOTYPE-events.bin"
        self.workers, self.checks, self.created_names = [], [], set()
        self.results = (self.root / "results.jsonl").open("x", encoding="utf-8")

    def check(self, name, condition):
        value = {"check": name, "pass": bool(condition)}
        self.checks.append(value)
        write_json(self.results, value)
        print(("PASS " if condition else "FAIL ") + name, flush=True)
        if not condition:
            raise AssertionError(name)

    def failed_start(self, label, role="reader", contains="", **kwargs):
        worker = Worker(self, label, role, **kwargs)
        result = worker.process.wait(timeout=10)
        write_json(worker.records, {"kind": "exit", "pid": worker.process.pid, "code": result})
        self.check(label, result == 2 and not worker.initial["ok"]
                   and contains in worker.initial.get("error", ""))
        return worker

    def cleanup(self):
        for worker in reversed(self.workers):
            if worker.process.poll() is None:
                os.kill(worker.process.pid, signal.SIGCONT)
                try:
                    worker.exit()
                except Exception as error:
                    write_json(worker.records, {"kind": "cleanup_error", "error": str(error)})
                    worker.process.kill()  # Only this run's own experimental child.
                    worker.process.wait(timeout=5)
            worker.records.close()
            worker.errors.close()
        # These exact names were created exclusively by this run. Keep all journals.
        for name in self.created_names:
            path = Path("/dev/shm") / name.removeprefix("/")
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        self.results.close()


def canonical(events):
    fields = ("epoch", "version", "proof", "value_ms", "verified_ms", "received_ms",
              "price", "quantity", "checksum", "gap", "time_known")
    return [(event["sequence"], event["seal"], tuple(event["record"][field] for field in fields))
            for event in events]


def scenarios(run):
    check = run.check
    run.failed_start("missing_region_rejected", contains="open named region")
    owner = Worker(run, "region_creator", "create")
    check("exclusive_region_created", owner.initial["ok"] and owner.initial["head"] == 0)
    run.created_names.add(run.name)
    run.failed_start("duplicate_creation_does_not_overwrite", role="create", contains="open named region")
    run.failed_start("wrong_region_identity_rejected", identity=run.identity + 1, contains="different region identity")
    wrong_journal = run.root / "PROTOTYPE-wrong-journal.bin"
    wrong_journal.write_bytes(b"")
    run.failed_start("wrong_journal_identity_rejected", journal=wrong_journal, contains="different journal identity")

    for label, size in (("zero_size_region_rejected", 0), ("incompatible_size_rejected", 1),
                        ("uninitialized_header_rejected", (Path("/dev/shm") / run.name[1:]).stat().st_size)):
        name = run.name + "-" + label
        path = Path("/dev/shm") / name[1:]
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        run.created_names.add(name)
        os.ftruncate(fd, size)
        os.close(fd)
        run.failed_start(label, name=name, contains="uninitialized")

    collision = Worker(run, "occupied_address", "occupied", address=0x350000000000)
    check("occupied_mapping_is_not_clobbered", collision.initial["ok"] and collision.exit() == 0)
    writer = Worker(run, "publisher_1", "publisher", address=0x310000000000)
    check("first_publisher_claims_epoch_one", writer.initial["ok"] and writer.initial["authority"] == 1)
    run.failed_start("second_live_publisher_rejected", role="publisher", contains="journal lease")
    writer.send("prepare", 0)
    check("new_authority_needs_complete_source_snapshot", not writer.send("publish", 0, expect_ok=False)["ok"])
    initial = writer.send("replace", 0)
    check("initial_snapshot_publishes_first_event", initial["head"] == 1 and initial["view"]["epoch"] == 1)
    fast = Worker(run, "consumer_fast", "reader", address=0x320000000000)
    slow = Worker(run, "consumer_slow", "reader", address=0x330000000000)
    check("three_independently_executed_business_processes", len({writer.process.pid, fast.process.pid, slow.process.pid}) == 3)
    check("distinct_real_mapping_addresses", len({writer.initial["address"], fast.initial["address"], slow.initial["address"]}) == 3)
    check("all_attach_same_region_identity", all(w.initial["identity"] == run.identity for w in (writer, fast, slow)))
    check("reader_cannot_publish", not fast.send("prepare", 0, expect_ok=False)["ok"])
    check("publisher_cannot_self_increment_epoch", not writer.send("restart", 0, expect_ok=False)["ok"])
    for reader in (fast, slow):
        reader.send("consume", 0, 1)
        check(reader.label + "_startup_needs_reconciliation", not reader.send("inspect", 0)["allowed"])
        reader.send("capture", 0)
        reader.send("reconcile", 0)
        check(reader.label + "_startup_stability_not_skipped", not reader.send("inspect", 199)["allowed"])
        check(reader.label + "_startup_ready", reader.send("inspect", 200)["allowed"])

    # A stalled process remains alive. Neither timeout nor closing its lock permits takeover.
    os.kill(writer.process.pid, signal.SIGSTOP)
    write_json(writer.records, {"kind": "injection", "signal": "SIGSTOP"})
    try:
        check("stalled_source_expiry_restricts_consumers", not fast.send("inspect", 1000)["allowed"]
              and not slow.send("inspect", 1000)["allowed"])
        run.failed_start("stopped_but_alive_publisher_not_replaced", role="publisher", contains="journal lease")
    finally:
        os.kill(writer.process.pid, signal.SIGCONT)
        write_json(writer.records, {"kind": "injection", "signal": "SIGCONT"})
    writer.send("release", 1000)
    check("publisher_released_mapping_while_still_alive", writer.receive()["action"] == "released"
          and writer.process.poll() is None)
    run.failed_start("released_lock_is_not_process_exit", role="publisher", contains="exit is not confirmed")
    check("publisher_one_confirmed_exit", writer.exit() == 0)
    replacement = Worker(run, "publisher_2", "publisher", address=0x340000000000)
    check("automatic_takeover_after_confirmed_exit", replacement.initial["ok"] and replacement.initial["authority"] == 2)
    check("takeover_preserves_journal_head", replacement.initial["head"] == 1)
    check("old_snapshot_invalid_under_new_authority", replacement.initial["view"]["validity"] == "old_epoch")
    replacement.send("replace", 1100)
    for reader in (fast, slow):
        reader.send("consume", 1100, 8)
        reader.send("capture", 1100)
        reader.send("reconcile", 1100)
    for reader in (fast, slow):
        check(reader.label + "_replacement_does_not_skip_stability", not reader.send("inspect", 1299)["allowed"])
    for reader in (fast, slow):
        check(reader.label + "_replacement_ready", reader.send("inspect", 1300)["allowed"])
        reader.send("capture", 1300)  # Save a credential from the old authority.
    check("old_epoch_intent_created", fast.send("issue", 1300)["ok"])
    slow.send("stop", 1300)
    for i in range(1, 13):
        now = 1300 + i * 10
        replacement.send("prepare", now)
        replacement.send("publish", now)
        fast.send("consume", now, 1)
    held = slow.send("inspect", 1420)
    check("slow_cursor_preserved_before_restart", held["cursor"] == 2 and held["head"] == 14 and not held["allowed"])
    check("publisher_abrupt_exit_recorded", replacement.exit(abrupt=True) == 77)
    next_writer = Worker(run, "publisher_3", "publisher", address=0x360000000000)
    check("abrupt_exit_allows_next_authority", next_writer.initial["ok"] and next_writer.initial["authority"] == 3)
    check("global_sequence_survives_publisher_crash", next_writer.initial["head"] == 14)
    check("restart_does_not_recover_pending_private_draft", not next_writer.send("publish", 1440, expect_ok=False)["ok"])
    next_writer.send("replace", 1440)
    current = fast.send("consume", 1440, 8)  # First observation is already a fresh epoch-3 snapshot.
    check("new_valid_epoch_still_enters_recovery", not current["allowed"] and current["recovering"])
    check("old_epoch_reconciliation_rejected_after_attach", not fast.send("reconcile", 1440, expect_ok=False)["ok"])
    check("old_intent_not_renewed_by_new_epoch", fast.send("execute", 1440)["outcome"] == "old_epoch")
    fast.send("capture", 1440)
    fast.send("reconcile", 1440)
    check("new_snapshot_does_not_skip_slow_backlog", not slow.send("reconcile", 1440, expect_ok=False)["ok"])
    caught = None
    for _ in range(4):
        caught = slow.send("consume", 1440, 4)
    check("slow_cross_epoch_progress_is_contiguous", caught["cursor"] == 15 and caught["processed"] == 15)
    check("evicted_old_epoch_events_replayed", caught["journal_reads"] == 5)
    check("old_slow_recovery_ticket_rejected", not slow.send("reconcile", 1440, expect_ok=False)["ok"])
    slow.send("capture", 1440)
    slow.send("reconcile", 1440)
    check("fast_recovery_waits_for_stability", not fast.send("inspect", 1639)["allowed"])
    check("fast_recovery_completes", fast.send("inspect", 1640)["allowed"])
    check("user_stop_survives_takeover_and_catchup", not slow.send("inspect", 1640)["allowed"])
    check("explicit_resume_after_all_conditions", slow.send("resume", 1640)["allowed"])

    published = writer.events + replacement.events + next_writer.events
    check("publisher_sequence_exactly_one_through_fifteen", [e["sequence"] for e in published] == list(range(1, 16)))
    check("fast_payloads_match_every_committed_event", canonical(fast.events) == canonical(published))
    check("slow_payloads_match_every_committed_event", canonical(slow.events) == canonical(published))
    check("old_intent_cannot_resubmit", fast.send("execute", 1640)["outcome"] == "no_resubmit")
    fast.send("issue", 1640)
    check("submission_result_unknown_is_retained", fast.send("execute", 1640)["outcome"] == "unknown")
    check("publisher_three_exits_normally", next_writer.exit() == 0)
    final_writer = Worker(run, "publisher_4", "publisher", address=0x370000000000)
    check("successive_takeovers_never_reset_epoch", final_writer.initial["authority"] == 4)
    final_writer.send("replace", 1700)
    for reader in (fast, slow):
        reader.send("consume", 1700, 8)
        reader.send("capture", 1700)
        reader.send("reconcile", 1700)
    all_published = published + final_writer.events
    check("both_consumers_match_all_sixteen_events", canonical(fast.events) == canonical(all_published)
          and canonical(slow.events) == canonical(all_published) and len(all_published) == 16)
    check("unknown_result_not_repeated_after_takeover", fast.send("execute", 1900)["outcome"] == "no_resubmit"
          and not fast.send("issue", 1900, expect_ok=False)["ok"])
    slow.exit()
    check("reader_detach_does_not_destroy_shared_mutex", fast.send("inspect", 1900)["allowed"])
    final_writer.send("replay", 2700)
    final_writer.send("heartbeat", 2700)
    replayed = fast.send("inspect", 2700)
    check("reattach_replay_and_heartbeat_do_not_renew_freshness", not replayed["allowed"]
          and replayed["view"]["verified_ms"] == 1700 and replayed["view"]["received_ms"] == 2700)
    fast.exit()
    final_writer.exit()
    owner.exit()
    unlink = Worker(run, "unlink_original", "unlink")
    check("experiment_owner_unlinks_after_all_users_exit", unlink.initial["ok"] and unlink.exit() == 0)
    recreated_journal = run.root / "PROTOTYPE-recreated-events.bin"
    recreated = Worker(run, "recreated_region", "create", identity=run.identity + 1, journal=recreated_journal)
    check("same_name_can_refer_to_new_region", recreated.initial["ok"] and recreated.initial["identity"] != run.identity)
    run.failed_start("old_identity_rejected_after_name_reuse", journal=recreated_journal, contains="different region identity")
    recreated.exit()
    unlink_new = Worker(run, "unlink_recreated", "unlink", identity=run.identity + 1, journal=recreated_journal)
    check("new_region_cleanup_verified_by_identity", unlink_new.initial["ok"] and unlink_new.exit() == 0)


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: independent_scenarios.py WORKER NEW_EVIDENCE_DIRECTORY")
    run = Run(Path(sys.argv[1]), Path(sys.argv[2]))
    source = Path(__file__).resolve().parent
    source_files = sorted(set(source.glob("*.hpp")) | set(source.glob("*.cpp")) |
                          {Path(__file__).resolve(), source / "CMakeLists.txt", source / "run-independent.cmake"})
    manifest = {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version(),
                "baseline_commit": "21720e963b0f4306913836c61ddfe72737b032ee", "region_identity": run.identity,
                "region_name": run.name, "binary": str(run.binary),
                "binary_sha256": hashlib.sha256(run.binary.read_bytes()).hexdigest(),
                "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
                "clock": "injected logical milliseconds", "orders_and_reconciliation": "simulated"}
    (run.root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    started = time.monotonic()
    error = None
    try:
        scenarios(run)
    except Exception as exception:
        error = f"{type(exception).__name__}: {exception}"
        raise
    finally:
        try:
            run.cleanup()
        except Exception as cleanup_error:
            error = error or f"cleanup: {cleanup_error}"
        summary = {"passed": error is None, "checks": len(run.checks), "failed": sum(not c["pass"] for c in run.checks),
                   "error": error, "elapsed_seconds": time.monotonic() - started}
        (run.root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary), flush=True)
    if error is not None:
        raise RuntimeError(error)


if __name__ == "__main__":
    main()
