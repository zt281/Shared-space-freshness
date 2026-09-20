#!/usr/bin/env python3
"""Rebuild a source snapshot and retain exact build/test evidence; isolated WSL paths."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parent
CACHE = Path('/home/alan/.cache/tyche-prototypes/quic-20260919')
LIB = CACHE / 'msquic-release/bin/Release/libmsquic.so.2.6.1'
INCLUDE = ROOT / '.quic-deps/msquic-v2.6.1/src/inc'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('configuration', choices=['debug', 'ubsan'])
    parser.add_argument('--storage', choices=['drvfs','ext4'], default='drvfs')
    args = parser.parse_args()
    evidence = ROOT / 'evidence-quic-wsl' / (args.configuration + '-' + args.storage + '-' + uuid.uuid4().hex[:12])
    evidence.mkdir(parents=True)
    snapshot = evidence / 'source';snapshot.mkdir()
    runtime = evidence / 'runs' if args.storage == 'drvfs' else CACHE / 'runtime-evidence' / evidence.name / 'runs'
    runtime.mkdir(parents=True)
    inputs = {p.name: p for p in ROOT.iterdir() if p.is_file() and (p.suffix in ['.cpp', '.hpp', '.py', '.cmake'] or p.name == 'CMakeLists.txt')}
    source_hashes = {n: sha(p) for n, p in inputs.items()}
    for name, path in inputs.items():
        shutil.copyfile(path, snapshot / name)
    build = CACHE / ('validated-' + args.configuration)
    commands = []
    manifest = {'configuration': args.configuration, 'source_sha256': source_hashes,
                'runtime_storage':args.storage,'original_runtime_evidence':str(runtime),
                'library': str(LIB), 'library_sha256': sha(LIB), 'include': str(INCLUDE),
                'header_sha256': sha(INCLUDE / 'msquic.h'), 'build': str(build)}

    def run(argv, timeout=200):
        n = len(commands) + 1
        out, err = evidence / f'{n:02}.stdout.txt', evidence / f'{n:02}.stderr.txt'
        record = {'argv': list(map(str, argv)), 'cwd': str(ROOT), 'started_utc': datetime.now(timezone.utc).isoformat(),
                  'stdout': out.name, 'stderr': err.name}
        commands.append(record)
        env = os.environ.copy();env['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
        record['environment_overrides'] = {'UBSAN_OPTIONS': env['UBSAN_OPTIONS']}
        print('RUN', n, ' '.join(record['argv']), flush=True)
        with out.open('wb') as stdout, err.open('wb') as stderr:
            result = subprocess.run(record['argv'], cwd=ROOT, stdout=stdout, stderr=stderr, env=env, timeout=timeout)
        record.update(code=result.returncode, finished_utc=datetime.now(timezone.utc).isoformat(), stdout_sha256=sha(out), stderr_sha256=sha(err))
        (evidence / 'commands.json').write_text(json.dumps(commands, indent=2))
        if result.returncode:
            raise RuntimeError(f'command {n} exited {result.returncode}')

    try:
        flags = '-fsanitize=undefined -fno-sanitize-recover=all -fno-omit-frame-pointer' if args.configuration == 'ubsan' else ''
        run(['cmake', '-S', ROOT, '-B', build, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Debug', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
             '-DTYCHE_QUIC_PROTOTYPE=ON', f'-DMSQUIC_INCLUDE_DIR={INCLUDE}', f'-DMSQUIC_LIBRARY={LIB}',
             f'-DPROTOTYPE_EVIDENCE_ROOT={runtime}', f'-DCMAKE_CXX_FLAGS={flags}'])
        run(['cmake', '--build', build, '-j', '4'])
        manifest['binary_sha256'] = {n: sha(build / n) for n in ['freshness_probe', 'ordered_probe', 'independent_worker', 'capacity_probe', 'quic_worker']}
        for name in ['CMakeCache.txt', 'compile_commands.json', 'build.ninja']:
            shutil.copyfile(build / name, evidence / name)
        run(['ldd', build / 'quic_worker'])
        run(['ctest', '--test-dir', build, '--output-on-failure', '-j', '1'], timeout=300)
        manifest['quic_runs'] = [str(p.relative_to(evidence)) for p in (evidence / 'runs').glob('quic-evidence-*/result.json')]
        manifest['source_unchanged'] = source_hashes == {n: sha(p) for n, p in inputs.items()}
        assert manifest['source_unchanged'], 'sources changed while validating'
        manifest['passed'] = True
    except Exception as exc:
        manifest['passed'] = False;manifest['error'] = repr(exc)
    finally:
        if args.storage == 'ext4':
            shutil.copytree(runtime,evidence/'runs')
        manifest['quic_runs'] = [str(p.relative_to(evidence)) for p in (evidence / 'runs').glob('quic-evidence-*/result.json')]
        manifest['source_unchanged'] = source_hashes == {n: sha(p) for n, p in inputs.items()}
        if (build / 'Testing/Temporary/LastTest.log').exists():
            shutil.copyfile(build / 'Testing/Temporary/LastTest.log', evidence / 'LastTest.log')
        (evidence / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'evidence': str(evidence), 'passed': manifest['passed']}), flush=True)
    return 0 if manifest['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
