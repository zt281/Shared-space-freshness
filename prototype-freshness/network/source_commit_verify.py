#!/usr/bin/env python3
"""Recheck archived bytes, final source binding, negative evidence and stage joins."""
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
from source_commit_audit import audit
from stage_audit import audit_case


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    index = json.loads((EVIDENCE / 'source-commit-archive-index.json').read_text())
    files = total_bytes = 0
    provenance = {}
    for item in index:
        root = EVIDENCE / item['archive']
        copied = json.loads((root / 'archive.json').read_text())
        for name, digest in copied['sha256'].items():
            path = root / name
            assert sha(path) == digest, path
            files += 1
            total_bytes += path.stat().st_size
        assert not list(root.rglob('*.key'))
        for p in (root / 'source').glob('*'):
            if p.is_file():
                provenance.setdefault((p.name, sha(p)), p.relative_to(HERE).as_posix())
    builds = []
    for name in ['release-84328c8ffdd5', 'ubsan-af9c0afb9be4']:
        root = EVIDENCE / ('source-commit-' + name)
        m = json.loads((root / 'manifest.json').read_text())
        assert m['passed'] and m['source_unchanged'] and all(c['code'] == 0 for c in m['commands'])
        assert '100% tests passed, 0 tests failed out of 7' in (root / '03.stdout.txt').read_text()
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
            source_run = any(c['scenario'] == 'completion-limit' for c in result['checks'])
            verified = audit(path.parent) if source_run else audit_run(path.parent)
            assert verified['checks'] == (167 if source_run else 124)
            if source_run:
                assert verified['completion_limit_covered'] and len(verified['cases']) == 14
            runs.append({'name': path.parent.name, 'source_commit_cases': source_run, 'verified': verified})
        assert len(runs) == 2
        builds.append({'archive': root.name, 'worker_sha256': m['binary_sha256']['quic_worker'], 'audited_runs': runs})
    matrices = []
    for name, expected, binary in [
        ('prior-smoke-bada1696157d', 3, '7e38dc098efd356b65539b46d9b18e9f0e68ae8c1322d6b171020fa35e61a5d5'),
        ('prior-matrix-5aceb0ca1840', 18, '7e38dc098efd356b65539b46d9b18e9f0e68ae8c1322d6b171020fa35e61a5d5'),
        ('matrix-c3401bc1b4b2', 18, builds[0]['worker_sha256']),
    ]:
        root = EVIDENCE / ('source-commit-' + name)
        manifest = json.loads((root / 'manifest.json').read_text())
        saved = json.loads((root / 'stage-audit.json').read_text())
        assert manifest['passed'] and manifest['worker_sha256'] == binary and len(manifest['results']) == expected
        for filename, digest in manifest['source_sha256'].items():
            assert sha(root / 'source' / filename) == digest
        recomputed = [audit_case(root / r['name']) for r in manifest['results']]
        assert recomputed == saved['cases']
        matrices.append({'archive': root.name, 'cases': expected, 'events': sum(r['planned'] for r in recomputed), 'worker_sha256': binary})
    negative = EVIDENCE / 'source-commit-red-completion-b2380e2dff2d'
    red = json.loads((negative / 'result.json').read_text())
    assert not red['passed'] and 'completion-capacity rejection latches required-input gap' in red['error']
    failed = EVIDENCE / 'source-commit-failed-release-6cadf8f0289b'
    assert not json.loads((failed / 'manifest.json').read_text())['passed']
    failures = [json.loads(p.read_text()) for p in (failed / 'runs').glob('quic-evidence-*/result.json')]
    assert sum(not r['passed'] for r in failures) == 1
    assert any(not r['passed'] and 'status timeout' in r['error'] and 'slow-receiver' in r['traceback'] for r in failures)
    pilots = []
    for name in ['pilot-00929367c9f2', 'slow-isolated-5753aeffcc8c', 'red-completion-b2380e2dff2d']:
        root = EVIDENCE / ('source-commit-' + name)
        m = json.loads((root / 'result.json').read_text())
        bindings = {filename: provenance[(filename, digest)] for filename, digest in m['source_sha256'].items()}
        pilots.append({'archive': root.name, 'source_files_bound_to_retained_snapshot': bindings, 'passed': m['passed']})
    tools = ['source_commit_audit.py', 'source_commit_archive.py', 'source_commit_probe.py', 'source_commit_verify.py',
             'stage_audit.py', 'stage_probe.py', 'stage_validate.py']
    report = {'verified_utc': datetime.now(timezone.utc).isoformat(), 'passed': True, 'original_files_verified': files,
              'original_bytes_verified': total_bytes, 'builds': builds, 'matrices': matrices, 'pilots': pilots,
              'expected_failure_artifacts_preserved': [negative.name, failed.name],
              'audit_tool_sha256': {name: sha(HERE / name) for name in tools}}
    (EVIDENCE / 'source-commit-verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'passed': True, 'files': files, 'bytes': total_bytes, 'final_builds': len(builds), 'measurements': matrices}), flush=True)


if __name__ == '__main__':
    main()
