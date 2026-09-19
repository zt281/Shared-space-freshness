"""Reparse saved evidence without running the Linux prototype. Writes audit.json."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parent
FIELDS = ("epoch", "version", "proof", "value_ms", "verified_ms", "received_ms",
          "price", "quantity", "checksum", "gap", "time_known")


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def events(path):
    return [event for row in records(path) for event in row.get("events", [])]


def payloads(items):
    return [(e["sequence"], e["seal"], tuple(e["record"][key] for key in FIELDS)) for e in items]


report = {"modes": {}, "files": {}}
for mode in ("debug", "ubsan"):
    directory = ROOT / mode
    raw_count = 0
    for path in directory.rglob("*.jsonl"):
        raw_count += len(records(path))
    for path in directory.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
    for path in directory.glob("independent-*/manifest.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for name, expected in manifest["source_sha256"].items():
            assert hashlib.sha256((path.parent / "sources" / name).read_bytes()).hexdigest() == expected
    candidates = [p.parent for p in directory.glob("independent-*/summary.json")
                  if json.loads(p.read_text())["checks"] == 69]
    assert len(candidates) == 1
    run = candidates[0]
    assert json.loads((run / "summary.json").read_text())["passed"]
    assert len(records(run / "results.jsonl")) == 69
    assert all(row["pass"] for row in records(run / "results.jsonl"))
    published = [event for i in range(1, 5) for event in events(run / f"publisher_{i}.jsonl")]
    assert [e["sequence"] for e in published] == list(range(1, 17))
    for reader in ("consumer_fast", "consumer_slow"):
        assert payloads(events(run / (reader + ".jsonl"))) == payloads(published)
    attached = []
    for label in ("publisher_1", "consumer_fast", "consumer_slow"):
        attached.append(next(row for row in records(run / (label + ".jsonl")) if row.get("action") == "attached"))
    assert len({row["pid"] for row in attached}) == len({row["address"] for row in attached}) == 3
    assert len({row["identity"] for row in attached}) == 1
    assert not any(p.stat().st_size for p in run.glob("*.stderr.txt"))
    build = json.loads((directory / "build.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["binary_sha256"] == build["binary_sha256"]["independent_worker"]
    report["modes"][mode] = {
        "final_independent_run": run.name, "checks": 69, "events_per_consumer": len(published),
        "all_saved_jsonl_records": raw_count, "mapping_addresses": [hex(row["address"]) for row in attached],
        "pids": [row["pid"] for row in attached], "source_archives_match": True,
    }
    for path in directory.rglob("*"):
        if path.is_file():
            report["files"][str(path.relative_to(ROOT)).replace("\\", "/")] = {
                "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
(ROOT / "audit.json").write_bytes((json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"))
print(json.dumps(report["modes"], indent=2))
