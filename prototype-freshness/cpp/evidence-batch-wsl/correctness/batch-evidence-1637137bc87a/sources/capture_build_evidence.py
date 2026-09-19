#!/usr/bin/env python3
"""Capture actual build flags/binaries and the last complete CTest run."""
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

build, output = (Path(p).resolve() for p in sys.argv[1:])
metadata = {
    "platform": platform.platform(), "os_release": Path("/etc/os-release").read_text(),
    "compiler": subprocess.check_output(["c++", "--version"], text=True),
    "cmake": subprocess.check_output(["cmake", "--version"], text=True),
    "python": sys.version, "build_directory": str(build),
    "targets": {},
}
latest = max(output.glob("recovery-evidence-*"), key=lambda p: p.stat().st_mtime)
metadata["last_recovery_run"] = latest.name
assert json.loads((latest / "manifest.json").read_text())["binary_sha256"] == hashlib.sha256((build / "independent_worker").read_bytes()).hexdigest()
for target in ("freshness_probe", "ordered_probe", "independent_worker"):
    flags = (build / "CMakeFiles" / (target + ".dir") / "flags.make").read_text()
    link = (build / "CMakeFiles" / (target + ".dir") / "link.txt").read_text()
    metadata["targets"][target] = {"flags": flags, "link": link,
                                    "sha256": hashlib.sha256((build / target).read_bytes()).hexdigest()}
shutil.copyfile(build / "Testing/Temporary/LastTest.log", output / "LastTest.log")
(output / "build.json").write_bytes((json.dumps(metadata, indent=2) + "\n").encode())
print(json.dumps({"saved": str(output), "targets": list(metadata["targets"])}))
