#!/usr/bin/env python3
"""Recheck original hashes and bytes; derive comparable round-level diagnostics."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

from datetime import datetime, timezone

from capacity_run import summarize, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    cases = sorted(path for path in root.iterdir() if path.is_dir() and (path / "manifest.json").exists())
    assert cases, "no saved diagnostic cases"
    analysis = root / "analysis"
    analysis.mkdir(exist_ok=True)
    analysis_sources = analysis / "sources"
    analysis_sources.mkdir(exist_ok=True)
    source_root = Path(__file__).resolve().parent
    for filename in ["capacity_audit.py", "capacity_run.py", "audit_crash_evidence.py"]:
        shutil.copyfile(source_root / filename, analysis_sources / filename)
    report, table = [], []
    for case in cases:
        for relative, expected in json.loads((case / "hashes.json").read_text()).items():
            assert hashlib.sha256((case / relative).read_bytes()).hexdigest() == expected, (case, relative)
        config = json.loads((case / "manifest.json").read_text())
        processes = json.loads((case / "processes.json").read_text())
        assert processes["failure"] is None and processes["cleanup"]["returncode"] == 0, case
        assert all(worker["exit_code"] == 0 for worker in processes["workers"]), case
        assert all(not path.read_bytes() for path in case.glob("*.stderr.txt")), case
        for filename, expected in config["sources"].items():
            assert hashlib.sha256((case / "sources" / filename).read_bytes()).hexdigest() == expected, (case, filename)
        flags = (case / "sources" / "CMakeFiles_capacity_probe.dir_flags.make.txt").read_text()
        assert "-O3" in flags and "-DNDEBUG" in flags and "-fsanitize" not in flags, flags
        result = summarize(case, config, analysis / case.name)
        write_json(analysis / case.name / "summary.json", result)
        report.append({"case": case.name, **result})
        r, a, p = result["rounds"], result["aggregate"], result["processes"]["publisher"]
        table.append({"case": case.name, "storage": "D NTFS/9p" if "drvfs" in case.name else "C VHD/ext4",
                      "mode": config["mode"], "fanout": config["fanout"], "rate": config["rate"],
                      "input_seconds": config["seconds"], "drain_budget_seconds": config["drain_seconds"],
                      "planned_rounds": r["expected"], "window_complete_rounds": r["completed_in_window"],
                      "final_complete_rounds": r["completed"], "missing_rounds": r["missing"],
                      "expected_deliveries": a["expected_deliveries"], "final_deliveries": a["completed_deliveries"],
                      "round_p99_ms": r["scheduled_to_last_consumer"].get("p99_ms"),
                      "round_max_ms": r["scheduled_to_last_consumer"].get("max_ms"),
                      "window_round_backlog": r["window_backlog"], "oldest_wait_ms": r["window_oldest_wait_ms"],
                      "drain_ms": a["drain_ms"], "publisher_call_p99_ms": p["call_cost"].get("p99_ms"),
                      "max_consumer_p99_ms": a["max_consumer_conditional_p99_ms"],
                      "max_deadline_overrun_ms": a["max_deadline_overrun_ms"],
                      "cpu_user_ms": a["user_cpu_us"] / 1000, "cpu_system_ms": a["system_cpu_us"] / 1000,
                      "max_process_rss_kib": a["max_process_rss_kib"], "started_utc": config["started_utc"]})
    write_json(root / "summary-table.json", table)
    hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(root.rglob("*")) if p.is_file() and p.name not in ["audit.json", "README.md"]}
    audit = {"cases": len(cases), "all_original_hashes_match": True, "all_payloads_and_checkpoints_match": True,
             "all_processes_exited_zero": True, "all_shared_regions_unlinked_after_exit": True,
             "all_stats_errors_empty": True, "all_sequence_payload_error_counts_zero": True,
             "analysis_utc": datetime.now(timezone.utc).isoformat(), "analysis_command": [sys.executable, *sys.argv],
             "analysis_sources": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(analysis_sources.iterdir())},
             "original_manifest_sha256": {p.name: hashlib.sha256((p / "manifest.json").read_bytes()).hexdigest() for p in cases},
             "original_summary_sha256": {p.name: hashlib.sha256((p / "summary.json").read_bytes()).hexdigest() for p in cases},
             "measured_binary_sha256": sorted({json.loads((p / "manifest.json").read_text())["binary_sha256"] for p in cases}),
             "scheduled_rounds": sum(x["planned_rounds"] for x in table),
             "completed_rounds": sum(x["final_complete_rounds"] for x in table),
             "expected_deliveries": sum(x["expected_deliveries"] for x in table),
             "completed_deliveries": sum(x["final_deliveries"] for x in table), "files": len(hashes), "sha256": hashes,
             "limitations": "short diagnostic, conditional quantiles, incomplete work included; no sustained capacity or tail guarantee"}
    write_json(root / "audit.json", audit)
    for row in table:
        print(json.dumps(row))
    print(json.dumps({k: v for k, v in audit.items() if k != "sha256"}))


if __name__ == "__main__":
    main()
