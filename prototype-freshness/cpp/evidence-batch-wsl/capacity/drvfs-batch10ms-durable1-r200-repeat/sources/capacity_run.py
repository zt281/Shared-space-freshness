#!/usr/bin/env python3
"""Disposable short capacity diagnostic. Pipes carry two barriers, never events."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import select
import shutil
import subprocess
import sys
import time

from audit_crash_evidence import checkpoint, events, seal


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.write_bytes((json.dumps(value, indent=2) + "\n").encode("utf-8"))


def quantiles(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    def value(p):
        return values[max(0, math.ceil(p * len(values)) - 1)] / 1e6
    return {"n": len(values), "p50_ms": value(.5), "p99_ms": value(.99), "max_ms": values[-1] / 1e6}


def rows(path):
    with path.open(newline="") as source:
        return [{key: int(value) for key, value in row.items()} for row in csv.DictReader(source)]


def summarize(root, config, analysis_root=None):
    output = root if analysis_root is None else analysis_root
    output.mkdir(parents=True, exist_ok=True)
    publisher = rows(root / "publisher.csv")
    names = ["publisher"] + [f"consumer-{i}" for i in range(config["fanout"])]
    source = events(root / "PROTOTYPE-events.bin")
    assert len(source) >= 1
    expected_names = ("sequence", "epoch", "version", "proof", "value_ms", "verified_ms", "received_ms",
                      "price", "quantity", "checksum", "gap", "time_known", "seal")
    results, all_delays, operation_costs, consumer_series = {}, [], [], []
    start, end, deadline = config["start_ns"], config["window_end_ns"], config["deadline_ns"]
    for name in names:
        records = publisher if name == "publisher" else rows(root / (name + ".csv"))
        stats = json.loads((root / (name + ".json")).read_text())
        assert stats["error"] == "" and stats["sequence_errors"] == stats["payload_errors"] == 0, (name, stats)
        assert len(records) == config["count"] == stats["planned"]
        completed = [r for r in records if r["outcome"] == 1]
        assert len(completed) == stats["completed"]
        assert [r["index"] for r in completed] == list(range(len(completed)))
        for i, r in enumerate(records):
            assert r["index"] == i and r["planned_ns"] == start + i * 1_000_000_000 // config["rate"]
            if r["outcome"]:
                assert r["started_ns"] >= start and r["completed_ns"] >= r["started_ns"]
                expected = source[i + 1]
                actual = tuple(r[k] for k in expected_names)
                if name == "publisher":
                    assert actual[:-1] == expected[:-1]  # Publisher proposal seal is not exposed by public API.
                    assert r["planned_ns"] <= r["started_ns"] <= r["prepared_ns"] <= r["publication_started_ns"] <= r["completed_ns"]
                    if config.get("publisher_mode") == "batch":
                        assert actual == expected and r["accepted"] == r["terminal"] == 1
                        assert r["publication_started_ns"] <= r["sync_started_ns"] <= r["synced_ns"] <= r["published_ns"] <= r["completed_ns"]
                        assert r["enqueue_returned_ns"] >= r["prepared_ns"] and r["result_observed_ns"] >= r["completed_ns"]
                else:
                    assert actual == expected
                    assert publisher[i]["outcome"] == 1
                    assert r["completed_ns"] >= publisher[i]["publication_started_ns"]
                    assert r["checkpoint_confirmed_by_ns"] == (r["completed_ns"] if config["mode"] == "durable" else 0)
        if name != "publisher" and config["mode"] == "durable":
            state = checkpoint(root / ("PROTOTYPE-" + name + ".checkpoint"))
            cursor = len(completed) + 1
            assert state[5] == state[6] == cursor
            assert state[7] == source[cursor - 1][-1]
            assert state[8] == sum(e[8] for e in source[:cursor])
            assert state[9] == sum(e[7] for e in source[:cursor])
            assert state[10] == seal([e[-1] for e in source[:cursor]])
        by_end = [r for r in completed if r["completed_ns"] <= end]
        not_complete = len(records) - len(completed)
        outstanding_end = [r for r in records if not r["outcome"] or r["completed_ns"] > end]
        backlog_at_end = len(outstanding_end)
        # Demand that has not reached this stage, including work not yet published.
        earliest_end = min((r["planned_ns"] for r in outstanding_end), default=end)
        source_published_end = sum(r["outcome"] == 1 and r["completed_ns"] <= end for r in publisher)
        delays = [r["completed_ns"] - r["planned_ns"] for r in completed]
        costs = [r["completed_ns"] - r["started_ns"] for r in completed]
        result = {"planned": len(records), "completed": len(completed), "missing_at_exit": not_complete,
                  "completed_in_window": len(by_end), "window_completion_fraction": len(by_end) / len(records),
                  "window_offered_backlog": backlog_at_end,
                  "window_published_backlog": max(0, source_published_end - len(by_end)) if name != "publisher" else None,
                  "window_oldest_wait_ms": max(0, end - earliest_end) / 1e6,
                  "started_in_window": sum(0 < r["started_ns"] <= end for r in records),
                  "not_started_at_exit": sum(r["started_ns"] == 0 for r in records),
                  "scheduled_to_complete": quantiles(delays), "call_cost": quantiles(costs),
                  "last_complete_ns": max((r["completed_ns"] for r in completed), default=0),
                  "deadline_overrun_ms": max(0, stats["measured_end_ns"] - deadline) / 1e6,
                  "fully_drained": not_complete == 0,
                  "drain_ms": max(0, max((r["completed_ns"] for r in completed), default=end) - end) / 1e6 if not_complete == 0 else None,
                  "planned_window_events_per_s": config["rate"], "completed_in_window_per_s": len(by_end) / config["seconds"],
                  "resource": stats}
        if name == "publisher":
            result["terminal_counts"] = {"committed": len(completed),
                "rejected": sum(r.get("terminal") == 2 for r in records),
                "unknown": sum(r.get("terminal") == 3 for r in records),
                "not_started": sum(r["started_ns"] == 0 for r in records)}
            result["admitted"] = sum(r.get("accepted", int(r["outcome"] == 1)) for r in records)
            result["admitted_pending_at_window_end"] = sum(r.get("accepted", int(r["outcome"] == 1))
                and (not r["outcome"] or r["completed_ns"] > end) for r in records)
        results[name] = result
        if name != "publisher":
            all_delays.extend(delays)
            operation_costs.extend(costs)
            consumer_series.append(records)
    assert len(source) == results["publisher"]["completed"] + 1
    expected = config["count"] * config["fanout"]
    finished = sum(results[n]["completed"] for n in names[1:])
    window_finished = sum(results[n]["completed_in_window"] for n in names[1:])
    rounds = []
    for i, proposal in enumerate(publisher):
        participants = [series[i] for series in consumer_series]
        complete = all(item["outcome"] == 1 for item in participants)
        rounds.append({"index": i, "planned_ns": proposal["planned_ns"],
                       "completed_ns": max(item["completed_ns"] for item in participants) if complete else 0,
                       "completed_consumers": sum(item["outcome"] == 1 for item in participants),
                       "expected_consumers": config["fanout"], "outcome": int(complete)})
    with (output / "rounds.csv").open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rounds[0]))
        writer.writeheader()
        writer.writerows(rounds)
    completed_rounds = [r for r in rounds if r["outcome"]]
    in_window_rounds = [r for r in completed_rounds if r["completed_ns"] <= end]
    pending_rounds = [r for r in rounds if not r["outcome"] or r["completed_ns"] > end]
    round_summary = {"expected": len(rounds), "completed": len(completed_rounds),
                     "missing": len(rounds) - len(completed_rounds), "completed_in_window": len(in_window_rounds),
                     "window_backlog": len(pending_rounds),
                     "window_oldest_wait_ms": (end - min((r["planned_ns"] for r in pending_rounds), default=end)) / 1e6,
                     "scheduled_to_last_consumer": quantiles([r["completed_ns"] - r["planned_ns"] for r in completed_rounds])}
    slowest_name = max(names[1:], key=lambda n: (results[n]["missing_at_exit"], results[n]["window_offered_backlog"],
                                               results[n]["scheduled_to_complete"].get("p99_ms", float("inf"))))
    slowest = {"name": slowest_name, "selection": "missing count, then window backlog, then conditional p99",
               **{k: results[slowest_name][k] for k in ["completed", "missing_at_exit", "window_offered_backlog",
                                                         "window_oldest_wait_ms", "scheduled_to_complete"]}}
    max_conditional_p99 = max((results[n]["scheduled_to_complete"].get("p99_ms", 0) for n in names[1:]), default=0)
    curve = []
    for t in range(start, deadline + 1, 100_000_000):
        offered = sum(r["planned_ns"] <= t for r in publisher)
        pub = sum(r["outcome"] == 1 and r["completed_ns"] <= t for r in publisher)
        each = [sum(r["outcome"] == 1 and r["completed_ns"] <= t for r in series) for series in consumer_series]
        whole = sum(r["outcome"] == 1 and r["completed_ns"] <= t for r in rounds)
        curve.append({"ns_since_start": t-start, "offered": offered, "publication_returns": pub,
                      "publisher_waiting_or_inflight": offered-pub, "consumer_completions": each,
                      "consumer_offered_backlogs": [offered-n for n in each], "complete_rounds": whole,
                      "round_backlog": offered-whole})
    write_json(output / "backlog-100ms.json", curve)
    return {"config": config, "audit_passed": True, "processes": results,
            "rounds": round_summary, "slowest_consumer": slowest,
            "aggregate": {"expected_deliveries": expected, "completed_deliveries": finished,
                          "missing_deliveries": expected - finished, "window_completed_deliveries": window_finished,
                          "window_completion_fraction": window_finished / expected,
                          "window_offered_backlog": expected - window_finished,
                          "window_max_oldest_wait_ms": max(results[n]["window_oldest_wait_ms"] for n in names[1:]),
                          "all_drained": finished == expected,
                          "drain_ms": max(results[n]["drain_ms"] for n in names) if finished == expected else None,
                          "consumer_scheduled_to_complete": quantiles(all_delays), "consumer_call_cost": quantiles(operation_costs),
                          "max_consumer_conditional_p99_ms": max_conditional_p99,
                          "max_deadline_overrun_ms": max(results[n]["deadline_overrun_ms"] for n in names),
                          "user_cpu_us": sum(results[n]["resource"]["user_cpu_us"] for n in names),
                          "system_cpu_us": sum(results[n]["resource"]["system_cpu_us"] for n in names),
                          "max_process_rss_kib": max(results[n]["resource"]["max_rss_kib_process_lifetime"] for n in names)}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--rate", type=int, required=True)
    parser.add_argument("--seconds", type=int, default=2)
    parser.add_argument("--drain", type=int, default=3)
    parser.add_argument("--fanout", type=int, choices=[1, 4, 20], required=True)
    parser.add_argument("--mode", choices=["durable", "ordered"], default="durable")
    parser.add_argument("--idle-ns", type=int, default=100000)
    parser.add_argument("--publisher-mode", choices=["sync", "batch"], default="sync")
    parser.add_argument("--queue-capacity", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--batch-wait-ns", type=int, default=2000000)
    args = parser.parse_args()
    assert 1 <= args.rate <= 10000 and 1 <= args.seconds <= 10 and 1 <= args.drain <= 10
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    identity = time.time_ns() & ((1 << 63) - 1)
    name = "/tyche-independent-capacity-" + str(identity)
    count = args.rate * args.seconds
    binary = args.binary.resolve()
    config = {"prototype": True, "root": str(root), "region": name, "identity": identity, "rate": args.rate,
              "seconds": args.seconds, "drain_seconds": args.drain, "fanout": args.fanout,
              "mode": args.mode, "count": count, "idle_poll_ns": args.idle_ns, "started_utc": utc(),
              "publisher_mode": args.publisher_mode, "queue_capacity": args.queue_capacity,
              "batch_size": args.batch_size, "batch_wait_ns": args.batch_wait_ns,
              "publisher_confirmation": "batch worker result after journal sync and shared publication; sync mode call return; never enqueue return",
              "invocation": [sys.executable, *sys.argv],
              "clock": "CLOCK_MONOTONIC; same-host only", "platform": platform.platform(),
              "cpu_affinity": sorted(os.sched_getaffinity(0)), "binary": str(binary),
              "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "filesystem": subprocess.check_output(["findmnt", "-T", str(root), "-J", "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"], text=True),
              "excluded": ["initialization event and startup", "recovery replay", "bulk diagnostic persistence",
                           "production metric-recording hot path", "pricing/fitting", "network", "real orders"],
              "checkpoint_timestamp": "consume return is an upper bound, not exact internal fsync completion",
              "measurement_durability": "volatile arrays until all workers finish; crashes can lose this diagnostic"}
    source_root = Path(__file__).resolve().parent
    sources = root / "sources"
    sources.mkdir()
    config["sources"] = {}
    for filename in ["capacity_probe.cpp", "capacity_run.py", "audit_crash_evidence.py", "CMakeLists.txt",
                     "space.cpp", "space.hpp", "model.hpp", "ordered_consumer.hpp", "consumer.hpp",
                     "durable_consumer.cpp", "durable_consumer.hpp", "faults.hpp"]:
        content = (source_root / filename).read_bytes()
        (sources / filename).write_bytes(content)
        config["sources"][filename] = hashlib.sha256(content).hexdigest()
    for filename in ["batch_publisher.cpp", "batch_publisher.hpp"]:
        content = (source_root / filename).read_bytes()
        (sources / filename).write_bytes(content)
        config["sources"][filename] = hashlib.sha256(content).hexdigest()
    for filename in ["CMakeCache.txt", "CMakeFiles/capacity_probe.dir/flags.make", "CMakeFiles/capacity_probe.dir/link.txt"]:
        path = binary.parent / filename
        if path.exists():
            (sources / (filename.replace("/", "_") + ".txt")).write_bytes(path.read_bytes())
    write_json(root / "manifest.json", config)
    workers = []
    transcript = []
    def read(worker, phase, timeout=20):
        if not select.select([worker["process"].stdout], [], [], timeout)[0]:
            raise TimeoutError((worker["label"], phase))
        text = worker["process"].stdout.readline()
        assert text, (worker["label"], "unexpected EOF", worker["process"].poll())
        value = json.loads(text)
        transcript.append({"label": worker["label"], "received_utc": utc(), **value})
        assert value["phase"] == phase, value
        return value
    def launch(role, index):
        label = "publisher" if role in ["publisher", "batch"] else f"consumer-{index}"
        command = [str(binary), role, str(root), name, str(identity), str(index), str(args.rate), str(count), str(args.idle_ns)]
        if role == "batch":
            command += [str(args.queue_capacity), str(args.batch_size), str(args.batch_wait_ns)]
        error = (root / (label + ".stderr.txt")).open("w")
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error, text=True)
        worker = {"process": process, "error": error, "label": label, "command": command}
        workers.append(worker)
        return worker
    failure = None
    try:
        publisher = launch("batch" if args.publisher_mode == "batch" else "publisher", 0)
        read(publisher, "ready")
        consumers = [launch(args.mode, i) for i in range(args.fanout)]
        for worker in consumers:
            read(worker, "ready")
        start = time.monotonic_ns() + 300_000_000
        end = start + args.seconds * 1_000_000_000
        deadline = end + args.drain * 1_000_000_000
        config.update(start_ns=start, window_end_ns=end, deadline_ns=deadline)
        write_json(root / "manifest.json", config)
        for worker in workers:
            worker["process"].stdin.write(f"{start} {end} {deadline}\n")
            worker["process"].stdin.flush()
        for worker in workers:
            read(worker, "measured", args.seconds + args.drain + 12)
        for worker in workers:
            worker["process"].stdin.write("save\n")
            worker["process"].stdin.flush()
        for worker in workers:
            read(worker, "saved")
            worker["exit_code"] = worker["process"].wait(timeout=10)
        result = summarize(root, config)
        write_json(root / "summary.json", result)
        print(json.dumps({"root": str(root), "rate": args.rate, "fanout": args.fanout, "mode": args.mode,
                          "rounds": result["rounds"], "slowest": result["slowest_consumer"],
                          "aggregate": result["aggregate"]}), flush=True)
    except BaseException as error:
        failure = repr(error)
        write_json(root / "failure.json", {"error": failure, "utc": utc()})
        raise
    finally:
        for worker in workers:
            process = worker["process"]
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=6)
            worker["exit_code"] = process.returncode
            worker["error"].close()
        cleanup = [str(binary), "unlink", str(root), name, str(identity), "0", str(args.rate), str(count), str(args.idle_ns)]
        cleaned = subprocess.run(cleanup, capture_output=True, text=True, timeout=10)
        write_json(root / "processes.json", {"workers": [{k: w[k] for k in ["label", "command", "exit_code"]} for w in workers],
                                              "cleanup": {"command": cleanup, "returncode": cleaned.returncode,
                                                          "stdout": cleaned.stdout, "stderr": cleaned.stderr},
                                              "barriers": transcript, "failure": failure, "finished_utc": utc()})
        hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(root.rglob("*")) if p.is_file() and p.name != "hashes.json"}
        write_json(root / "hashes.json", hashes)


if __name__ == "__main__":
    main()
