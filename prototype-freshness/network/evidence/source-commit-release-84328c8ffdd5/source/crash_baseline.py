#!/usr/bin/env python3
"""Observe known baseline gaps. Passing checks confirm defects, not recovery correctness."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from independent_scenarios import Run, Worker, canonical, write_json


def main():
    if len(sys.argv) != 5:
        raise SystemExit("usage: crash_baseline.py WORKER FAULT_SO INSPECTOR NEW_EVIDENCE_DIRECTORY")
    binary, fault, inspector, root = map(lambda value: Path(value).resolve(), sys.argv[1:])
    run = Run(binary, root)
    cpp = Path(__file__).resolve().parent
    sources = root / "sources"
    sources.mkdir()
    for source in sorted(cpp.iterdir()):
        if source.suffix in {".cpp", ".hpp", ".py", ".cmake"} or source.name == "CMakeLists.txt":
            original = subprocess.run(["git", "-C", str(cpp), "show",
                                       "0d33ccf:prototype-freshness/cpp/" + source.name], capture_output=True)
            (sources / source.name).write_bytes(original.stdout if original.returncode == 0 else source.read_bytes())
    manifest = {
        "purpose": "baseline defect reproduction; not a recovery acceptance suite",
        "platform": platform.platform(), "python": sys.version,
        "source_head": "0d33ccf7eda70bd5d342b08839d3c13d3abfed37",
        "source_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources.iterdir()},
        "binaries": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (binary, fault, inspector)},
        "fault": "second successful fdatasync exits with 77 before returning to Space::append",
        "identity": run.identity, "name": run.name,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def inspect_copy(label):
        saved = root / (label + ".bin")
        shutil.copyfile(run.journal, saved)
        decoded = subprocess.check_output([str(inspector), str(saved)], text=True)
        (root / (label + ".jsonl")).write_text(decoded, encoding="utf-8")
        return [json.loads(line) for line in decoded.splitlines()]

    try:
        owner = Worker(run, "creator", "create")
        run.check("created_unique_region", owner.initial["ok"])
        run.created_names.add(run.name)
        owner.exit()
        previous = {key: os.environ.get(key) for key in ("LD_PRELOAD", "TYCHE_PROTOTYPE_CRASH_ON_SYNC")}
        try:
            os.environ["LD_PRELOAD"] = str(fault)
            os.environ["TYCHE_PROTOTYPE_CRASH_ON_SYNC"] = "2"
            publisher = Worker(run, "publisher_before_crash", "publisher", address=0x310000000000)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        publisher.send("replace", 0)
        old_reader = Worker(run, "reader_before_restart", "reader", address=0x320000000000)
        consumed = old_reader.send("consume", 0, 8)
        old_reader.send("capture", 0)
        old_reader.send("reconcile", 0)
        run.check("baseline_reader_ready", old_reader.send("inspect", 200)["allowed"])
        run.check("baseline_user_stop_blocks", not old_reader.send("stop", 200)["allowed"])
        old_reader.exit()

        reader = Worker(run, "reader_after_restart", "reader", address=0x330000000000)
        run.check("observed_restart_loses_cursor", consumed["cursor"] == 1 and reader.initial["cursor"] == 0)
        repeated = reader.send("consume", 200, 8)
        run.check("observed_first_event_processed_again", canonical(consumed["events"]) == canonical(repeated["events"]))
        reader.send("capture", 200)
        reader.send("reconcile", 200)
        run.check("observed_reconciliation_forgets_user_stop", reader.send("inspect", 400)["allowed"])

        publisher.send("prepare", 410)
        try:
            publisher.send("publish", 410)
            raise AssertionError("publisher should die before replying")
        except EOFError:
            pass
        code = publisher.process.wait(timeout=10)
        write_json(publisher.records, {"kind": "exit", "pid": publisher.process.pid, "code": code})
        run.check("injected_exit_after_successful_sync", code == 77)
        before = inspect_copy("journal_after_crash")
        observed = reader.send("inspect", 410)
        run.check("observed_valid_tail_beyond_shared_head", len(before) == 2 and all(e["valid"] for e in before)
                  and before[-1]["sequence"] == 2 and before[-1]["epoch"] == 1 and observed["head"] == 1)
        run.check("owner_death_restricts_reader", observed["view"]["validity"] == "damaged" and not observed["allowed"])

        replacement = Worker(run, "publisher_after_crash", "publisher", address=0x340000000000)
        run.check("takeover_keeps_old_head", replacement.initial["authority"] == 2 and replacement.initial["head"] == 1)
        published = replacement.send("replace", 420)
        after = inspect_copy("journal_after_replacement")
        run.check("observed_saved_tail_overwritten", len(after) == 2 and after[0] == before[0]
                  and after[1]["sequence"] == before[1]["sequence"] and after[1] != before[1]
                  and after[1]["epoch"] == 2 and before[1]["verified_ms"] == 410 and after[1]["verified_ms"] == 420)
        delivered = reader.send("consume", 420, 8)
        run.check("observed_replaced_tail_never_delivered", delivered["cursor"] == 2
                  and canonical(delivered["events"]) == canonical(published["events"])
                  and delivered["events"][0]["record"]["epoch"] == 2)
        (root / "verdict.json").write_text(json.dumps({
            "baseline_gaps_reproduced": True, "checks": len(run.checks),
            "not_recovery_acceptance": True,
            "tail_before": before[-1], "tail_after": after[-1],
        }, indent=2) + "\n", encoding="utf-8")
    finally:
        run.cleanup()


if __name__ == "__main__":
    main()
