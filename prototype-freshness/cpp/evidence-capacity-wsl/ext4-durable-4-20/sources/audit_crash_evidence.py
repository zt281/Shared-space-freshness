#!/usr/bin/env python3
"""Independent offline checks of saved bytes, payloads and source provenance."""
import hashlib
import json
from pathlib import Path
import struct
import sys

MASK = (1 << 64) - 1


def seal(values):
    value = 1469598103934665603
    for field in values:
        value = ((value ^ (field & MASK)) * 1099511628211) & MASK
    return value


def events(path):
    # Deliberately separate decoder; current evidence is Linux x86_64 local ABI.
    record = struct.Struct("<QQQQqqqQQQBB6xQ")
    raw = path.read_bytes()
    assert record.size == 96 and len(raw) % record.size == 0, path
    result = []
    for offset in range(0, len(raw), record.size):
        fields = record.unpack_from(raw, offset)
        assert fields[0] == offset // record.size + 1, path
        assert fields[10] in (0, 1) and fields[11] in (0, 1), path
        assert seal(fields[:-1]) == fields[-1], path
        assert fields[9] == fields[7] ^ (fields[8] << 16) ^ fields[2] ^ 0xCAFE1234, path
        result.append(fields)
    return result


def checkpoint(path):
    fields = struct.unpack("<16Q", path.read_bytes())
    assert fields[0] == 0x545943484543484B and fields[1] == 1, path
    assert fields[5] == fields[6] and seal(fields[:-1]) == fields[-1], path
    return fields


def audit_run(root):
    manifest = json.loads((root / "manifest.json").read_text())
    for name, digest in manifest["sources"].items():
        assert hashlib.sha256((root / "sources" / name).read_bytes()).hexdigest() == digest, name
    summary = json.loads((root / "summary.json").read_text())
    assert len(summary) in (22, 23), "unfinished matrix"
    assert all(item["pass"] for case in summary for item in case["checks"]), root
    for folder in root.glob("publication-*"):
        point = int(folder.name.rsplit("-", 1)[-1])
        saved = (folder / "journal-at-crash.bin").read_bytes()
        current = folder / "PROTOTYPE-events.bin"
        if point == 1:
            assert len(saved) % 96 == 48 and current.read_bytes() == saved
            continue
        decoded = events(current)
        assert current.read_bytes().startswith(saved)
        assert len(decoded) == (10 if point == 0 else 11)
        assert decoded[-1][1] == 2 and decoded[-1][5] == 120
        if point:
            assert decoded[9][0:3] == (10, 1, 10) and decoded[9][5] == 100
        for label in ("fast", "slow"):
            rows = [json.loads(line) for line in (folder / (label + ".jsonl")).read_text().splitlines()]
            delivered = [event for row in rows if row.get("kind") == "response" for event in row.get("events", [])]
            assert len(delivered) == len(decoded)
            names = ("epoch", "version", "proof", "value_ms", "verified_ms", "received_ms",
                     "price", "quantity", "checksum", "gap", "time_known")
            for actual, source in zip(delivered, decoded):
                assert (actual["sequence"], *(actual["record"][name] for name in names), actual["seal"]) == source
    for point in range(7):
        folder = root / ("checkpoint-" + str(point))
        history = events(folder / "PROTOTYPE-events.bin")
        saved = checkpoint(folder / "PROTOTYPE-consumer.checkpoint")
        interrupted = checkpoint(folder / "checkpoint-at-crash.bin")
        cursor = 1 if point <= 3 else 2
        assert interrupted[5] == cursor and interrupted[8] == sum(e[8] for e in history[:cursor])
        assert interrupted[9] == sum(e[7] for e in history[:cursor]) and interrupted[11] == 1
        assert saved[5] == len(history) and saved[7] == history[-1][-1]
        assert saved[8] == sum(e[8] for e in history) and saved[9] == sum(e[7] for e in history)
        assert saved[10] == seal([e[-1] for e in history])
        assert not (folder / "PROTOTYPE-consumer.checkpoint.simulated-submissions.jsonl").exists()
    for point in (7, 8):
        folder = root / ("control-" + str(point))
        saved = checkpoint(folder / "PROTOTYPE-consumer.checkpoint")
        assert saved[14] == 2, "unknown attempt lost"
        external = folder / "PROTOTYPE-consumer.checkpoint.simulated-submissions.jsonl"
        rows = [json.loads(line) for line in external.read_text().splitlines()] if external.exists() else []
        assert len(rows) == (0 if point == 7 else 1)
    return {"path": str(root), "cases": len(summary), "checks": sum(len(case["checks"]) for case in summary)}


def main():
    root = Path(sys.argv[1]).resolve()
    reports = [audit_run(path) for path in sorted(root.glob("*/recovery-evidence-*"))]
    assert reports, "no recovery evidence"
    for mode in ("debug", "ubsan"):
        build = json.loads((root / mode / "build.json").read_text())
        latest = json.loads((root / mode / build["last_recovery_run"] / "manifest.json").read_text())
        assert build["targets"]["independent_worker"]["sha256"] == latest["binary_sha256"]
        if mode == "ubsan":
            for target in build["targets"].values():
                assert "-fsanitize=undefined" in target["flags"] and "-fno-sanitize-recover=all" in target["flags"]
    files, rows, stderr_bytes = {}, 0, 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in {"README.md", "audit.json"}:
            continue
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes()
        files[relative] = hashlib.sha256(content).hexdigest()
        if path.suffix == ".json":
            json.loads(content)
        elif path.suffix == ".jsonl":
            for line in content.splitlines():
                json.loads(line)
                rows += 1
        if path.name.endswith(".stderr.txt"):
            stderr_bytes += len(content)
    assert stderr_bytes == 0, "unexpected child diagnostics, inspect stderr evidence"
    report = {"runs": reports, "jsonl_rows": rows, "files": len(files), "stderr_bytes": stderr_bytes,
              "sha256": files, "scope": "offline verification of saved evidence; not a performance or power-loss test"}
    (root / "audit.json").write_bytes((json.dumps(report, indent=2) + "\n").encode())
    print(json.dumps({key: value for key, value in report.items() if key != "sha256"}, indent=2))


if __name__ == "__main__":
    main()
