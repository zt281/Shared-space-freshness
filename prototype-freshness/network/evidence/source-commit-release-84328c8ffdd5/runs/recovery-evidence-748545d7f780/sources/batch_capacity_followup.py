#!/usr/bin/env python3
"""Finish the four preplanned cases, then exactly one same-condition failure repeat."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from capacity_run import utc, write_json

binary, root = [Path(v).resolve() for v in sys.argv[1:]]
source = Path(__file__).resolve().parent
output = root / "followup-matrix.json"
assert not output.exists()
cases = [("drvfs-batch10ms-durable4-r100", "batch", 4, 100),
         ("drvfs-sync-durable4-r100", "sync", 4, 100),
         ("drvfs-sync-durable20-r5", "sync", 20, 5),
         ("drvfs-batch10ms-durable20-r5", "batch", 20, 5),
         ("drvfs-batch10ms-durable1-r200-repeat", "batch", 1, 200)]
matrix = {"started_utc": utc(), "command": [sys.executable, *sys.argv],
          "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "cases": [],
          "reason": "complete original matrix plus one bounded repeat after a real checkpoint rename failure; no binary or durability change"}
write_json(output, matrix)
for name, mode, fanout, rate in cases:
    command = [sys.executable, str(source / "capacity_run.py"), "--binary", str(binary), "--root", str(root/name),
               "--rate", str(rate), "--fanout", str(fanout), "--publisher-mode", mode, "--seconds", "2", "--drain", "3",
               "--queue-capacity", "128", "--batch-size", "8", "--batch-wait-ns", "10000000"]
    record = {"name": name, "started_utc": utc(), "command": command}
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    record.update(finished_utc=utc(), returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
    matrix["cases"].append(record)
    write_json(output, matrix)
    print(name + " exit=" + str(result.returncode), flush=True)
    summary = root / name / "summary.json"
    if summary.exists():
        print(json.dumps(json.loads(summary.read_text())["rounds"]), flush=True)
    else:
        print(result.stderr, flush=True)
matrix["finished_utc"] = utc()
write_json(output, matrix)
