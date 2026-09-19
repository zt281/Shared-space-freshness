#!/usr/bin/env python3
"""Capture an isolated build/regression run for opt-in stage instrumentation."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1] / 'cpp'
HERE = Path(__file__).resolve().parent
CACHE = Path('/home/alan/.cache/tyche-prototypes/quic-20260919')
LIB = CACHE / 'msquic-release/bin/Release/libmsquic.so.2.6.1'
INCLUDE = ROOT / '.quic-deps/msquic-v2.6.1/src/inc'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('configuration', choices=['release', 'ubsan'])
    parser.add_argument('--build-only', action='store_true')
    args = parser.parse_args()
    evidence = CACHE / 'stage-build-evidence' / (args.configuration + '-' + uuid.uuid4().hex[:12])
    evidence.mkdir(parents=True)
    snapshot = evidence / 'source'
    snapshot.mkdir()
    inputs = {p.name: p for p in ROOT.iterdir() if p.is_file() and (p.suffix in ['.cpp', '.hpp', '.py', '.cmake'] or p.name == 'CMakeLists.txt')}
    hashes = {n: sha(p) for n, p in inputs.items()}
    for name, path in inputs.items():
        shutil.copyfile(path, snapshot / name)
    shutil.copyfile(Path(__file__), evidence / Path(__file__).name)
    build = CACHE / ('stage-' + args.configuration)
    runtime = evidence / 'runs'
    manifest = {'configuration': args.configuration, 'source_sha256': hashes, 'runtime_storage': 'ext4',
                'library': str(LIB), 'library_sha256': sha(LIB), 'header_sha256': sha(INCLUDE / 'msquic.h'),
                'build': str(build), 'commands': [], 'test_requested': not args.build_only}

    def run(argv, timeout=300):
        index = len(manifest['commands']) + 1
        record = {'argv': list(map(str, argv)), 'started_utc': datetime.now(timezone.utc).isoformat()}
        manifest['commands'].append(record)
        env = os.environ.copy()
        env['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
        print('RUN', index, ' '.join(record['argv']), flush=True)
        with (evidence / f'{index:02}.stdout.txt').open('wb') as out, (evidence / f'{index:02}.stderr.txt').open('wb') as err:
            result = subprocess.run(record['argv'], cwd=ROOT, env=env, stdout=out, stderr=err, timeout=timeout)
        record.update(code=result.returncode, finished_utc=datetime.now(timezone.utc).isoformat())
        if result.returncode:
            raise RuntimeError(f'command {index} failed: {result.returncode}')

    try:
        flags = '-fsanitize=undefined -fno-sanitize-recover=all -fno-omit-frame-pointer' if args.configuration == 'ubsan' else ''
        run(['cmake', '-S', ROOT, '-B', build, '-G', 'Ninja',
             '-DCMAKE_BUILD_TYPE=' + ('Debug' if args.configuration == 'ubsan' else 'Release'),
             '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '-DTYCHE_QUIC_PROTOTYPE=ON',
             f'-DMSQUIC_INCLUDE_DIR={INCLUDE}', f'-DMSQUIC_LIBRARY={LIB}',
             f'-DPROTOTYPE_EVIDENCE_ROOT={runtime}', f'-DCMAKE_CXX_FLAGS={flags}'])
        run(['cmake', '--build', build, '-j', '4'])
        for name in ['CMakeCache.txt', 'compile_commands.json', 'build.ninja']:
            shutil.copyfile(build / name, evidence / name)
        manifest['binary_sha256'] = {name: sha(build / name) for name in ['freshness_probe', 'ordered_probe', 'independent_worker', 'capacity_probe', 'quic_worker']}
        if not args.build_only:
            run(['ctest', '--test-dir', build, '--output-on-failure', '-j', '1'])
        manifest['passed'] = True
    except Exception as exc:
        manifest.update(passed=False, error=repr(exc))
    finally:
        manifest['source_unchanged'] = hashes == {n: sha(p) for n, p in inputs.items()}
        manifest['passed'] &= manifest['source_unchanged']
        log = build / 'Testing/Temporary/LastTest.log'
        if not args.build_only and log.exists():
            shutil.copyfile(log, evidence / 'LastTest.log')
        (evidence / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'evidence': str(evidence), 'passed': manifest['passed']}), flush=True)
    return 0 if manifest['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
