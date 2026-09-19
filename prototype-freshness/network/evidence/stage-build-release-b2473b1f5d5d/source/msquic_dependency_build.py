#!/usr/bin/env python3
"""Isolated, disposable MsQuic dependency build. No system installation or network experiment."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import signal
import time

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / '.quic-deps' / 'msquic-v2.6.1'
BUILD = Path('/home/alan/.cache/tyche-prototypes/quic-20260919/msquic-release')
EVIDENCE = ROOT / 'evidence-msquic-build-wsl'
TAG = 'v2.6.1'
COMMIT = 'a01333cf7c2659cce0ff03ef3f21e1ff15bb5b83'
ORIGIN = 'https://github.com/microsoft/msquic.git'
TLS_COMMIT = 'ff36838bb69801cad56823159a036977bcbe5c75'
TLS_ORIGIN = 'https://github.com/quictls/openssl.git'
TLS_SOURCE = SOURCE / 'submodules' / 'quictls'
OVERRIDES = {'GIT_TERMINAL_PROMPT':'0', 'CMAKE_BUILD_PARALLEL_LEVEL':'4', 'MAKEFLAGS':'-j4', 'OMP_NUM_THREADS':'4'}
BUILD_BUDGET_BYTES = 4 * 1024**3


def utc():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.write_bytes((json.dumps(value, indent=2) + '\n').encode())


def run(command, *, cwd=None, timeout=180):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    history_path = EVIDENCE / 'commands.json'
    history = json.loads(history_path.read_text()) if history_path.exists() else []
    number = len(history) + 1
    out = EVIDENCE / ('step-%02d.stdout.txt' % number)
    err = EVIDENCE / ('step-%02d.stderr.txt' % number)
    assert not out.exists() and not err.exists(), 'never overwrite previous command output'
    record = {'command': [str(x) for x in command], 'cwd': str(cwd or ROOT), 'started_utc': utc(),
              'stdout': out.name, 'stderr': err.name, 'timeout_seconds': timeout,
              'environment_overrides': OVERRIDES}
    history.append(record)
    save(history_path, history)
    environment = os.environ.copy()
    environment.update(OVERRIDES)
    print('RUN ' + str(number) + ': ' + ' '.join(record['command']), flush=True)
    with out.open('wb') as stdout, err.open('wb') as stderr:
        try:
            process = subprocess.Popen(command, cwd=cwd or ROOT, env=environment, stdout=stdout, stderr=stderr, start_new_session=True)
            if '--build' in command:
                deadline = time.monotonic() + timeout
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(command, timeout)
                    size = int(subprocess.check_output(['du','-sb',str(BUILD.parent)],text=True).split()[0])
                    record['peak_observed_build_bytes'] = max(record.get('peak_observed_build_bytes',0),size)
                    free = shutil.disk_usage('/mnt/c').free
                    if size > BUILD_BUDGET_BYTES or free < 8*1024**3:
                        record['budget_stop'] = {'build_bytes':size,'host_c_free_bytes':free}
                        raise subprocess.TimeoutExpired(command, timeout)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                record['returncode'] = process.returncode
            else:
                record['returncode'] = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM) # Only this script's own isolated child group.
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            record['timed_out'] = True
            record['finished_utc'] = utc()
            save(history_path, history)
            raise
    record['finished_utc'] = utc()
    record['stdout_sha256'] = hashlib.sha256(out.read_bytes()).hexdigest()
    record['stderr_sha256'] = hashlib.sha256(err.read_bytes()).hexdigest()
    save(history_path, history)
    if record['returncode']:
        raise RuntimeError('step %d failed: %s' % (number, err.read_text(errors='replace')[-4000:]))
    return out.read_text(errors='replace').strip()


def verify_source():
    assert run(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD']) == COMMIT
    assert run(['git', '-C', str(SOURCE), 'rev-parse', TAG + '^{commit}']) == COMMIT


def fetch():
    assert not SOURCE.exists(), 'source already exists; verify/reuse it, never overwrite'
    run(['git', '-c', 'http.lowSpeedLimit=1024', '-c', 'http.lowSpeedTime=30',
         'clone', '--depth', '1', '--single-branch', '--branch', TAG, '--no-recurse-submodules', ORIGIN, str(SOURCE)])
    verify_source()
    run(['git', '-C', str(SOURCE), 'ls-tree', 'HEAD', 'submodules'])
    run(['git', '-C', str(SOURCE), 'submodule', 'status'])


def inspect():
    verify_source()
    for command in [['uname','-a'], ['git','--version'], ['cmake','--version'], ['ninja','--version'],
                    ['gcc','--version'], ['g++','--version'], ['make','--version'], ['perl','-v'],
                    ['pkg-config','--version'], ['df','-h','/home/alan','/mnt/d'],
                    ['findmnt','-T',str(SOURCE),'-J','-o','TARGET,SOURCE,FSTYPE,OPTIONS']]:
        run(command)


def fetch_tls():
    verify_source()
    tree = run(['git','-C',str(SOURCE),'ls-tree','HEAD','submodules/quictls'])
    assert TLS_COMMIT in tree
    assert not (TLS_SOURCE / '.git').exists(), 'TLS source already exists; do not overwrite'
    run(['git','-C',str(SOURCE),'submodule','init','--','submodules/quictls'])
    run(['git','init',str(TLS_SOURCE)])
    run(['git','-C',str(TLS_SOURCE),'remote','add','origin',TLS_ORIGIN])
    run(['git','-C',str(TLS_SOURCE),'-c','http.lowSpeedLimit=1024','-c','http.lowSpeedTime=30',
         'fetch','--depth','1','origin',TLS_COMMIT])
    run(['git','-C',str(TLS_SOURCE),'checkout','--detach','FETCH_HEAD'])
    run(['git','-C',str(SOURCE),'submodule','absorbgitdirs','submodules/quictls'])
    assert run(['git','-C',str(TLS_SOURCE),'rev-parse','HEAD']) == TLS_COMMIT
    run(['git','-C',str(SOURCE),'submodule','status'])


def configure():
    verify_source()
    assert run(['git','-C',str(TLS_SOURCE),'rev-parse','HEAD']) == TLS_COMMIT
    assert run(['nproc']) == '4', 'MsQuic ProcessorCount/nproc must not select eight TLS make jobs'
    assert not (BUILD / 'CMakeCache.txt').exists(), 'preserve previous configure evidence; no implicit reset'
    BUILD.mkdir(parents=True, exist_ok=True)
    run(['cmake','-S',str(SOURCE),'-B',str(BUILD),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
         '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DQUIC_TLS_LIB=quictls',
         '-DQUIC_USE_SYSTEM_LIBCRYPTO=OFF','-DQUIC_USE_EXTERNAL_OPENSSL=OFF',
         '-DQUIC_ENABLE_LOGGING=OFF','-DQUIC_BUILD_TEST=OFF','-DQUIC_BUILD_TOOLS=OFF',
         '-DQUIC_BUILD_PERF=OFF','-DQUIC_BUILD_SHARED=ON','-DQUIC_LINUX_IOURING_ENABLED=OFF',
         '-DCMAKE_INSTALL_PREFIX='+str(BUILD/'unused-local-install')])
    generated = (BUILD / 'build.ninja').read_text()
    assert 'make install_dev -j4' in generated and 'make install_dev -j8' not in generated


def build():
    # Keep this prototype's cache bounded well below the host C volume's measured 25 GiB free.
    assert shutil.disk_usage('/mnt/c').free > 8 * 1024**3
    # Build the TLS custom target first so its four make workers cannot overlap
    # four unrelated Ninja compilation jobs in a fresh combined target build.
    run(['cmake','--build',str(BUILD),'--target','OpenSSL_Target','--parallel','1'],timeout=600)
    run(['cmake','--build',str(BUILD),'--target','msquic','--parallel','4'],timeout=600)
    run(['du','-sh',str(SOURCE),str(BUILD)])


def link():
    library = BUILD / 'bin' / 'Release' / 'libmsquic.so.2.6.1'
    assert library.exists()
    run(['g++','-std=c++20','-Wall','-Wextra','-Wpedantic','-Werror','-isystem',str(SOURCE/'src'/'inc'),
         str(ROOT/'msquic_link_smoke.cpp'),str(library),'-Wl,-rpath,'+str(library.parent),
         '-o',str(BUILD/'msquic_link_smoke')])
    run(['ldd',str(library)])
    run(['ldd',str(BUILD/'msquic_link_smoke')])
    run(['readelf','-d',str(library)])
    run(['nm','-D','--defined-only',str(library)])
    run(['sha256sum',str(library),str(BUILD/'msquic_link_smoke'),str(SOURCE/'src'/'inc'/'msquic.h')])
    print('READY library='+str(library)+' include='+str(SOURCE/'src'/'inc'),flush=True)


def archive():
    verify_source()
    assert run(['git','-C',str(TLS_SOURCE),'rev-parse','HEAD']) == TLS_COMMIT
    assert run(['git','-C',str(SOURCE),'status','--porcelain','--untracked-files=no']) == ''
    assert run(['git','-C',str(TLS_SOURCE),'status','--porcelain','--untracked-files=no']) == ''
    assert run(['git','-C',str(SOURCE),'rev-list','--count','HEAD']) == '1'
    assert run(['git','-C',str(TLS_SOURCE),'rev-list','--count','HEAD']) == '1'
    run(['du','-sh',str(SOURCE),str(BUILD)])
    run(['df','-h','/mnt/c','/mnt/d'])
    run(['findmnt','-T',str(BUILD),'-J','-o','TARGET,SOURCE,FSTYPE,OPTIONS'])
    snapshots = EVIDENCE / 'build-inputs'
    snapshots.mkdir(exist_ok=True)
    for name, path in {
        'MsQuic-CMakeLists.txt':SOURCE/'CMakeLists.txt',
        'TLS-CMakeLists.txt':SOURCE/'submodules'/'CMakeLists.txt',
        'gitmodules.txt':SOURCE/'.gitmodules', 'TLS-VERSION.dat':TLS_SOURCE/'VERSION.dat',
        'CMakeCache.txt':BUILD/'CMakeCache.txt', 'build.ninja':BUILD/'build.ninja',
        'compile_commands.json':BUILD/'compile_commands.json',
        'msquic_dependency_build.py':Path(__file__).resolve(), 'msquic_link_smoke.cpp':ROOT/'msquic_link_smoke.cpp',
        'LICENSE.msquic':SOURCE/'LICENSE', 'LICENSE.quictls':TLS_SOURCE/'LICENSE.txt',
        'OpenSSL-Makefile':BUILD/'_deps'/'opensslquic-build'/'submodules'/'quictls'/'Makefile',
    }.items():
        shutil.copyfile(path, snapshots/name)
    inputs = {str(p.relative_to(SOURCE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (SOURCE/'src'/'inc').glob('*.h')}
    artifacts = [BUILD/'bin'/'Release'/'libmsquic.so.2.6.1', BUILD/'msquic_link_smoke',
        BUILD/'_deps'/'opensslquic-build'/'quictls'/'lib'/'libssl.a',
        BUILD/'_deps'/'opensslquic-build'/'quictls'/'lib'/'libcrypto.a']
    dependency = {'recorded_utc':utc(), 'tag':TAG, 'msquic_commit':COMMIT, 'quictls_commit':TLS_COMMIT,
        'origins':{'msquic':ORIGIN,'quictls':TLS_ORIGIN}, 'source':str(SOURCE),'build':str(BUILD),
        'include':str(SOURCE/'src'/'inc'),'library':str(artifacts[0]), 'headers_sha256':inputs,
        'artifacts':{str(p):{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in artifacts},
        'source_worktrees_clean':True, 'shallow_commit_counts':{'msquic':1,'quictls':1},
        'scope':'Linux WSL build and link only; smoke ELF not executed; no connection/replication/performance experiment',
        'system_install':False,'private_tls':True, 'build_budget_bytes':BUILD_BUDGET_BYTES}
    save(EVIDENCE/'dependency.json',dependency)
    commands = json.loads((EVIDENCE/'commands.json').read_text())
    for entry in commands:
        assert entry.get('returncode') == 0, entry
        for stream in ['stdout','stderr']:
            assert hashlib.sha256((EVIDENCE/entry[stream]).read_bytes()).hexdigest() == entry[stream+'_sha256']
    save(EVIDENCE/'audit.json',{'recorded_utc':utc(), 'commands':len(commands),'all_recorded_commands_succeeded':True,
        'artifacts':dependency['artifacts'], 'sha256':{str(p.relative_to(EVIDENCE)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(EVIDENCE.rglob('*')) if p.is_file() and p.name != 'audit.json'}})
    print(json.dumps(dependency),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['fetch','inspect','fetch-tls','configure','build','link','archive'])
    arguments = parser.parse_args()
    {'fetch':fetch, 'inspect':inspect,'fetch-tls':fetch_tls,'configure':configure,'build':build,'link':link,'archive':archive}[arguments.action]()
