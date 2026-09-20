#!/usr/bin/env python3
"""Recheck archived remote-commit bytes, final source binding and stage joins."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
CPP = HERE.parent / 'cpp'
EVIDENCE = HERE / 'evidence'
sys.path.insert(0, str(CPP))
from quic_evidence_audit import audit_run
from source_commit_audit import audit as audit_source_commit
from remote_commit_audit import audit as audit_remote_commit
from stage_audit import audit_case


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    index = json.loads((EVIDENCE / 'remote-commit-archive-index.json').read_text())
    files = total_bytes = 0
    for item in index:
        root = EVIDENCE / item['archive']
        copied = json.loads((root / 'archive.json').read_text())
        for name, digest in copied['sha256'].items():
            path = root / name
            assert sha(path) == digest, path
            files += 1
            total_bytes += path.stat().st_size
        assert not list(root.rglob('*.key'))
    builds = []
    for name in ['release-f9169e17e608', 'ubsan-bad96d41a4fb']:
        root = EVIDENCE / ('remote-commit-' + name)
        m = json.loads((root / 'manifest.json').read_text())
        assert m['passed'] and m['source_unchanged'] and all(c['code'] == 0 for c in m['commands'])
        assert '100% tests passed, 0 tests failed out of 8' in (root / '03.stdout.txt').read_text()
        for filename, digest in m['source_sha256'].items():
            assert sha(root / 'source' / filename) == digest == sha(CPP / filename)
        commands = json.loads((root / 'compile_commands.json').read_text())
        flag = '-fsanitize=undefined' if name.startswith('ubsan') else '-O3'
        assert all(flag in c['command'] for c in commands)
        runs = []
        for path in (root / 'runs').glob('quic-evidence-*/result.json'):
            result = json.loads(path.read_text())
            assert result['worker_sha256'] == m['binary_sha256']['quic_worker']
            for filename, digest in result['source_sha256'].items():
                assert m['source_sha256'][filename] == digest
            scenarios = {c['scenario'] for c in result['checks']}
            if 'completion-limit' in scenarios:
                verified = audit_source_commit(path.parent)
                assert verified['checks'] == 167 and len(verified['cases']) == 14
                kind = 'source-commit'
            elif 'remote-save-error' in scenarios:
                verified = audit_remote_commit(path.parent)
                assert verified['checks'] == 169 and len(verified['cases']) == 13
                kind = 'remote-commit'
            else:
                verified = audit_run(path.parent)
                assert verified['checks'] == 124
                kind = 'replication'
            runs.append({'name': path.parent.name, 'kind': kind, 'checks': verified['checks']})
        assert len(runs) == 3 and {r['kind'] for r in runs} == {'replication', 'source-commit', 'remote-commit'}
        builds.append({'archive': root.name, 'worker_sha256': m['binary_sha256']['quic_worker'], 'audited_runs': runs})
    root = EVIDENCE / 'remote-commit-matrix-07ed7631b01c'
    manifest = json.loads((root / 'manifest.json').read_text())
    saved = json.loads((root / 'stage-audit.json').read_text())
    assert manifest['passed'] and manifest['worker_sha256'] == builds[0]['worker_sha256'] and len(manifest['results']) == 18
    for filename, digest in manifest['source_sha256'].items():
        assert sha(root / 'source' / filename) == digest
    recomputed = [audit_case(root / r['name']) for r in manifest['results']]
    assert recomputed == saved['cases']
    matrix = {'archive': root.name, 'cases': 18, 'events': sum(r['planned'] for r in recomputed),
              'worker_sha256': builds[0]['worker_sha256']}
    assert matrix['events'] == 1440
    tools = ['remote_commit_audit.py', 'remote_commit_archive.py', 'remote_commit_probe.py', 'remote_commit_verify.py',
             'stage_audit.py', 'stage_probe.py', 'stage_validate.py']
    report = {'verified_utc': datetime.now(timezone.utc).isoformat(), 'passed': True, 'original_files_verified': files,
              'original_bytes_verified': total_bytes, 'builds': builds, 'matrix': matrix,
              'audit_tool_sha256': {name: sha(HERE / name) for name in tools}}
    (EVIDENCE / 'remote-commit-verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'passed': True, 'files': files, 'bytes': total_bytes, 'final_builds': len(builds)}), flush=True)


if __name__ == '__main__':
    main()
