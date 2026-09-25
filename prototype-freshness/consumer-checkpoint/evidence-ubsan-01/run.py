#!/usr/bin/env python3
"""Build and run the disposable C++ experiment; retain every new run independently."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import time

from audit import audit

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--sanitize', action='store_true', help='UndefinedBehaviorSanitizer correctness run')
parser.add_argument('--output', type=Path, help='New evidence directory, must not exist')
args = parser.parse_args()
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
root = (args.output or HERE / f"evidence-{'ubsan' if args.sanitize else 'release'}-{stamp}").resolve()
if root.exists():
    parser.error('evidence directory must not exist')
flags = ['-std=c++20', '-Wall', '-Wextra', '-Wpedantic', '-Werror']
flags += ['-O1', '-g', '-fsanitize=undefined', '-fno-sanitize-recover=all'] if args.sanitize else ['-O2']
with tempfile.TemporaryDirectory(prefix='tyche-checkpoint-build-') as build:
    binary = Path(build) / 'checkpoint_experiment'
    command = ['c++', *flags, str(HERE / 'experiment.cpp'), '-o', str(binary)]
    compiled = subprocess.run(command, capture_output=True, text=True)
    if compiled.returncode:
        raise SystemExit(compiled.stdout + compiled.stderr)
    started = time.time()
    result = subprocess.run([str(binary), str(root)], capture_output=True, text=True)
    root.mkdir(exist_ok=True)
    (root / 'stdout.txt').write_text(result.stdout)
    (root / 'stderr.txt').write_text(result.stderr)
    (root / 'build.txt').write_text(compiled.stdout + compiled.stderr)
    for name in ('experiment.cpp', 'run.py', 'audit.py'):
        shutil.copy2(HERE / name, root / name)
    # Keep the exact executed binary locally; source, compiler and hash are tracked.
    shutil.copy2(binary, root / 'checkpoint_experiment')
    metadata = {'compiler': subprocess.check_output(['c++', '--version'], text=True),
                'platform': platform.platform(), 'machine': platform.machine(),
                'build_command': command, 'run_command': [str(binary), str(root)],
                'started_unix': started, 'elapsed_seconds': time.time()-started,
                'returncode': result.returncode, 'sanitizer': args.sanitize,
                'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                'filesystem': subprocess.check_output(['df', '-T', str(root)], text=True)}
    (root / 'environment.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(result.stdout, end='')
    if result.returncode:
        raise SystemExit(f'Experiment failed ({result.returncode}); retained evidence: {root}\n{result.stderr}')
    audit(root)
