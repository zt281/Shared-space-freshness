#!/usr/bin/env python3
"""Recheck archived remote-combo bytes, final source binding and stage joins."""
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
    index = json.loads((EVIDENCE / 'remote-combo-archive-index.json').read_text())
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
    root = EVIDENCE / 'remote-combo-release-7e0d40a79345'
    m = json.loads((root / 'manifest.json').read_text())
    assert m['passed'] and m['source_unchanged'] and all(c['code'] == 0 for c in m['commands'])
    assert '100% tests passed, 0 tests failed out of 8' in (root / '03.stdout.txt').read_text()
    for filename, digest in m['source_sha256'].items():
        assert sha(root / 'source' / filename) == digest == sha(CPP / filename)
    commands = json.loads((root / 'compile_commands.json').read_text())
    assert all('-O3' in c['command'] for c in commands)
    worker = m['binary_sha256']['quic_worker']
    runs = []
    for path in (root / 'runs').glob('quic-evidence-*/result.json'):
        result = json.loads(path.read_text())
        assert result['worker_sha256'] == worker
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
    build = {'archive': root.name, 'worker_sha256': worker, 'audited_runs': runs}
    matrices = []
    for name, expected_cases, expected_events in [
        ('remote-combo-matrix-848eb4898151', 18, 1440),
        ('remote-combo-heavy-28056a84d957', 9, 1800),
    ]:
        root = EVIDENCE / name
        manifest = json.loads((root / 'manifest.json').read_text())
        saved = json.loads((root / 'stage-audit.json').read_text())
        assert manifest['passed'] and manifest['worker_sha256'] == worker and len(manifest['results']) == expected_cases
        assert all(r.get('reconnects') == 0 for r in manifest['results'])
        for filename, digest in manifest['source_sha256'].items():
            assert sha(root / 'source' / filename) == digest
        recomputed = [audit_case(root / r['name']) for r in manifest['results']]
        assert recomputed == saved['cases']
        matrices.append({'archive': root.name, 'cases': expected_cases,
                         'events': sum(r['planned'] for r in recomputed), 'worker_sha256': worker})
        assert matrices[-1]['events'] == expected_events
    tools = ['remote_combo_archive.py', 'remote_combo_probe.py', 'remote_combo_verify.py',
             'remote_commit_audit.py', 'source_commit_audit.py', 'stage_audit.py', 'stage_probe.py', 'stage_validate.py']
    report = {'verified_utc': datetime.now(timezone.utc).isoformat(), 'passed': True, 'original_files_verified': files,
              'original_bytes_verified': total_bytes, 'build': build, 'matrices': matrices,
              'audit_tool_sha256': {name: sha(HERE / name) for name in tools}}
    (EVIDENCE / 'remote-combo-verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'passed': True, 'files': files, 'bytes': total_bytes, 'matrices': len(matrices)}), flush=True)


if __name__ == '__main__':
    main()
