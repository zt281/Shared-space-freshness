#!/usr/bin/env python3
"""Read-only audit of a failed checkpoint replacement, including uncommitted staging bytes."""
import hashlib
import json
from pathlib import Path
import sys

from audit_crash_evidence import checkpoint, events, seal
from capacity_run import rows, utc, write_json


def audit(root):
    for relative, expected in json.loads((root / "hashes.json").read_text()).items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected
    history = events(root / "PROTOTYPE-events.bin")
    stats = json.loads((root / "consumer-0.json").read_text())
    assert stats["error"] == "durable consumption: replace complete checkpoint"
    old_path = root / "PROTOTYPE-consumer-0.checkpoint"
    pending_paths = list(root.glob("PROTOTYPE-consumer-0.checkpoint.pending-*"))
    assert len(pending_paths) == 1
    old, pending = checkpoint(old_path), checkpoint(pending_paths[0])
    completed = [r for r in rows(root / "consumer-0.csv") if r["outcome"] == 1]
    assert len(completed) == stats["completed"] and old[5] == len(completed) + 1
    assert pending[5] == old[5] + 1 and pending[4] == old[4] + 1
    fields = ("sequence", "epoch", "version", "proof", "value_ms", "verified_ms", "received_ms",
              "price", "quantity", "checksum", "gap", "time_known", "seal")
    for i, row in enumerate(completed):
        assert tuple(row[k] for k in fields) == history[i+1]
    for state in [old, pending]:
        prefix = history[:state[5]]
        assert state[7] == prefix[-1][-1] and state[8] == sum(e[8] for e in prefix)
        assert state[9] == sum(e[7] for e in prefix) and state[10] == seal([e[-1] for e in prefix])
    processes = json.loads((root / "processes.json").read_text())
    return {"case": root.name, "audited_utc": utc(), "command": [sys.executable, *sys.argv],
            "evidence_consistent": True, "operation_passed": False, "errno_recorded": False,
            "published_event_count_including_initialization": len(history), "planned_inputs": stats["planned"],
            "confirmed_inputs": stats["completed"], "missing_inputs": stats["planned"]-stats["completed"],
            "checkpoint_cursor": old[5], "checkpoint_revision": old[4],
            "uncommitted_pending_cursor": pending[5], "uncommitted_pending_revision": pending[4],
            "pending_not_counted_as_committed": True, "checkpoint_staging_promoted_by_audit": False,
            "checkpoint_sha256": hashlib.sha256(old_path.read_bytes()).hexdigest(),
            "pending_sha256": hashlib.sha256(pending_paths[0].read_bytes()).hexdigest(),
            "worker_exit_codes": {w["label"]: w["exit_code"] for w in processes["workers"]},
            "error": stats["error"], "failed_attempt_start_timestamp": None,
            "timestamp_limit": "old harness fills consumer row times only on successful delivery; failed attempt start is not captured",
            "conclusion": "existing checkpoint covers exactly the confirmed prefix; complete next staging state is retained but not committed; errno/cause undetermined"}


if __name__ == "__main__":
    root, output = [Path(v).resolve() for v in sys.argv[1:]]
    output.parent.mkdir(parents=True, exist_ok=True)
    report = audit(root)
    write_json(output, report)
    print(json.dumps(report))
