#!/usr/bin/env python3
"""Fixed, short same-binary D-path comparison. Run after correctness builds/tests."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from capacity_run import utc, write_json


def main():
    binary, root = [Path(v).resolve() for v in sys.argv[1:]]
    source = Path(__file__).resolve().parent
    root.mkdir(parents=True, exist_ok=True)
    matrix_path = root / "matrix.json"
    assert not matrix_path.exists(), "never overwrite a previous matrix"
    cases = [
        ("drvfs-sync-durable1-r200-quiet", "sync", 1, 200, 2_000_000),
        ("drvfs-batch2ms-durable1-r200", "batch", 1, 200, 2_000_000),
        ("drvfs-batch10ms-durable1-r200", "batch", 1, 200, 10_000_000),
        ("drvfs-batch10ms-durable4-r100", "batch", 4, 100, 10_000_000),
        ("drvfs-sync-durable4-r100", "sync", 4, 100, 10_000_000),
        ("drvfs-sync-durable20-r5", "sync", 20, 5, 10_000_000),
        ("drvfs-batch10ms-durable20-r5", "batch", 20, 5, 10_000_000),
    ]
    matrix = {"started_utc": utc(), "invocation": [sys.executable, *sys.argv],
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "cases": [], "kernel": subprocess.check_output(["uname", "-a"], text=True),
              "meminfo_before": Path("/proc/meminfo").read_text(),
              "comparison_scope": "same new Release binary, D NTFS/9p path, serial runs; uncontrolled host short-term drift remains",
              "excluded_pilot": "drvfs-sync-durable1-r200 overlapped Debug work; retained, excluded from paired comparisons"}
    write_json(matrix_path, matrix)
    for name, mode, fanout, rate, wait in cases:
        command = [sys.executable, str(source / "capacity_run.py"), "--binary", str(binary), "--root", str(root / name),
                   "--rate", str(rate), "--fanout", str(fanout), "--publisher-mode", mode,
                   "--seconds", "2", "--drain", "3", "--queue-capacity", "128", "--batch-size", "8",
                   "--batch-wait-ns", str(wait)]
        record = {"name": name, "started_utc": utc(), "command": command}
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        record.update(finished_utc=utc(), returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        matrix["cases"].append(record)
        write_json(matrix_path, matrix)
        print(name + " exit=" + str(result.returncode), flush=True)
        if result.returncode:
            raise RuntimeError(record)
        summary = json.loads((root / name / "summary.json").read_text())
        print(json.dumps(summary["rounds"]), flush=True)
    matrix["finished_utc"] = utc()
    write_json(matrix_path, matrix)


if __name__ == "__main__":
    main()
