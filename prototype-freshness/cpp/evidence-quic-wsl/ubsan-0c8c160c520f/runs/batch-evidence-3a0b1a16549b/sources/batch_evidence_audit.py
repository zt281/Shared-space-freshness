#!/usr/bin/env python3
"""Offline evidence derivation; preserve original reports, failed runs, and byte hashes."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

from audit_crash_evidence import audit_run, checkpoint, events, seal
from batch_failure_audit import audit as audit_failure
from capacity_run import summarize, utc, write_json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_sources(root):
    value = json.loads((root / "manifest.json").read_text())
    for name, expected in value["sources"].items():
        assert digest(root / "sources" / name) == expected
    return value


def batch_run(root):
    manifest = verify_sources(root)
    summary = json.loads((root / "summary.json").read_text())
    assert len(summary) == 14 and all(c["pass"] for s in summary for c in s["checks"])
    keys = ("epoch", "version", "proof", "value_ms", "verified_ms", "received_ms", "price", "quantity", "checksum", "gap", "time_known")
    for case in root.glob("batch-crash-*"):
        point = int(case.name.rsplit("-", 1)[-1])
        raw = (case / "journal-at-crash.bin").read_bytes()
        current = case / "PROTOTYPE-events.bin"
        if point == 2:
            assert len(raw) == 240 and current.read_bytes() == raw
            continue
        count = 0 if point == 0 else 1 if point == 1 else 4
        history = events(current)
        assert len(history) == count + 2 and current.read_bytes().startswith(raw)
        responses = [json.loads(line) for line in (case / "publisher.jsonl").read_text().splitlines()]
        proposed = next(r["proposals"] for r in responses if r.get("action") == "batch_plan" and r["kind"] == "response")
        for event, saved in zip(proposed[:count], history[1:count+1]):
            assert (event["sequence"], *(event["record"][k] for k in keys), event["seal"]) == saved
        saved = checkpoint(case / "PROTOTYPE-consumer.checkpoint")
        assert saved[5] == len(history) and saved[8] == sum(e[8] for e in history)
        assert saved[9] == sum(e[7] for e in history) and saved[10] == seal([e[-1] for e in history])
    return {"path": root.name, "cases": 14, "checks": sum(len(c["checks"]) for c in summary),
            "binary_sha256": manifest["binary_sha256"]}


def main():
    root = Path(sys.argv[1]).resolve()
    source = Path(__file__).resolve().parent
    analysis = root / "analysis"
    analysis.mkdir(exist_ok=True)
    snapshots = root / "final-sources"
    snapshots.mkdir(exist_ok=True)
    for path in source.iterdir():
        if path.suffix in {".cpp", ".hpp", ".py", ".cmake"} or path.name == "CMakeLists.txt":
            shutil.copyfile(path, snapshots / path.name)
    # Both original and derived reports remain attributable to their own script versions.
    tables, cases = [], []
    for case in sorted((root / "capacity").iterdir()):
        if not (case / "manifest.json").exists():
            continue
        config = verify_sources(case)
        for relative, expected in json.loads((case / "hashes.json").read_text()).items():
            assert digest(case / relative) == expected, (case, relative)
        proc = json.loads((case / "processes.json").read_text())
        assert proc["cleanup"]["returncode"] == 0
        failed = any(w["exit_code"] != 0 for w in proc["workers"])
        report = summarize(case, config, analysis / case.name, allow_worker_errors=failed)
        write_json(analysis / case.name / "summary.json", report)
        if failed:
            assert case.name == "drvfs-batch10ms-durable1-r200"
            write_json(analysis / "checkpoint-replacement-failure-derived.json", audit_failure(case))
        assert all(not p.read_bytes() for p in case.glob("*.stderr.txt"))
        p, a, r = report["processes"]["publisher"], report["aggregate"], report["rounds"]
        readers = [v for n, v in report["processes"].items() if n.startswith("consumer-")]
        row = {"case": case.name, "included_in_pairs": case.name != "drvfs-sync-durable1-r200",
               "operational_pass": not failed, "all_rounds_drained": a["all_drained"], "mode": config["publisher_mode"],
               "fanout": config["fanout"], "rate": config["rate"], "wait_ms": config["batch_wait_ns"]/1e6,
               "planned": r["expected"], "window_complete": r["completed_in_window"], "complete": r["completed"],
               "missing": r["missing"], "window_backlog": r["window_backlog"], "oldest_wait_ms": r["window_oldest_wait_ms"],
               "round_conditional_p99_ms": r["scheduled_to_last_consumer"].get("p99_ms"),
               "slowest_consumer": report["slowest_consumer"], "drain_ms": a["drain_ms"],
               "publisher_confirm_p99_ms": p["scheduled_to_complete"].get("p99_ms"),
               "publisher_complete": p["completed"], "publisher_terminal_counts": p["terminal_counts"],
               "publisher_max_pending": p["resource"]["batch_max_pending"],
               "journal_syncs_timed": p["resource"]["batch_syncs"] if config["publisher_mode"] == "batch" else p["completed"],
               "consumer_guard_max_wait_ms": max(v["resource"]["guard_max_wait_ns"] for v in readers)/1e6,
               "consumer_guard_total_wait_ms": sum(v["resource"]["guard_wait_ns"] for v in readers)/1e6,
               "max_deadline_overrun_ms": a["max_deadline_overrun_ms"],
               "cpu_user_ms": a["user_cpu_us"]/1000, "cpu_system_ms": a["system_cpu_us"]/1000,
               "max_process_rss_kib": a["max_process_rss_kib"], "started_utc": config["started_utc"],
               "exit_codes": {w["label"]: w["exit_code"] for w in proc["workers"]}}
        tables.append(row)
        cases.append({"case": case.name, "original_manifest_sha256": digest(case / "manifest.json"),
                      "original_summary_sha256": digest(case / "summary.json") if (case / "summary.json").exists() else None,
                      "binary_sha256": config["binary_sha256"], "operation_passed": not failed})
    write_json(analysis / "capacity-table.json", tables)
    correctness = []
    # This audit addresses a frozen evidence set. Directory mtimes change during
    # Git checkout/copy and cannot identify which run was the final validation.
    final_batch_names = {
        "correctness": "batch-evidence-6b4a6608fec8",
        "correctness-ubsan": "batch-evidence-32546b2d2703",
    }
    for dirname in ["correctness", "correctness-ubsan"]:
        directory = root / dirname
        final_batch = directory / final_batch_names[dirname]
        recovery = next(directory.glob("recovery-evidence-*"))
        correctness.append({"mode": dirname, "old_recovery": audit_run(recovery), "batch": batch_run(final_batch)})
    # Keep exact build inputs and executable digests; do not check binaries into source control.
    builds = {}
    for mode in ["debug", "ubsan", "release"]:
        build = Path('/home/alan/.cache/tyche-prototypes') / ('batch-' + mode + '-20260919')
        saved = root / "build-fingerprints" / mode
        saved.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(build / "CMakeCache.txt", saved / "CMakeCache.txt")
        entries = {}
        for name in ["freshness_probe", "ordered_probe", "independent_worker", "capacity_probe"]:
            flags = build / 'CMakeFiles' / (name + '.dir') / 'flags.make'
            link = build / 'CMakeFiles' / (name + '.dir') / 'link.txt'
            shutil.copyfile(flags, saved / (name + '-flags.make'))
            shutil.copyfile(link, saved / (name + '-link.txt'))
            entries[name] = {"path": str(build / name), "sha256": digest(build / name), "flags": flags.read_text()}
        builds[mode] = entries
    hashes = {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob('*'))
              if p.is_file() and p.name != 'audit.json'}
    audit = {"audited_utc": utc(), "command": [sys.executable, *sys.argv], "analysis_sources": {p.name:digest(p) for p in snapshots.iterdir()},
             "correctness": correctness, "capacity": cases, "builds": builds,
             "all_original_hashes_match": True, "all_successful_payloads_and_checkpoint_prefixes_match": True,
             "capacity_operation_failure_cases": [x["case"] for x in cases if not x["operation_passed"]],
             "capacity_total_planned_rounds": sum(x["planned"] for x in tables),
             "capacity_total_completed_rounds": sum(x["complete"] for x in tables),
             "capacity_total_missing_rounds": sum(x["missing"] for x in tables),
             "files": len(hashes), "sha256": hashes,
             "scope": "data audit only; failed checkpoint case retained; no performance pass, capacity limit, or power-loss guarantee"}
    write_json(root / "audit.json", audit)
    for row in tables:
        print(json.dumps({k:v for k,v in row.items() if k not in ["slowest_consumer", "exit_codes"]}))
    print(json.dumps({k:v for k,v in audit.items() if k not in ["sha256", "builds", "analysis_sources", "capacity"]}))


if __name__ == '__main__':
    main()
