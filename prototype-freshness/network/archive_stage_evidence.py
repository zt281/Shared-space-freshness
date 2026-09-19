#!/usr/bin/env python3
"""Copy finite WSL artifacts without overwriting, then verify snapshots and QUIC bytes."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
CPP = HERE.parent / 'cpp'
sys.path.insert(0, str(CPP))
from quic_evidence_audit import audit_run


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if sys.platform != 'win32':
        raise RuntimeError('This archiver uses the existing Windows WSL share')
    cache = Path(r'\\wsl.localhost\Ubuntu\home\alan\.cache\tyche-prototypes\quic-20260919')
    destination = HERE / 'evidence'
    selections = [
        ('stage-build-evidence', 'release-b2473b1f5d5d', 'stage-build-release-b2473b1f5d5d'),
        ('stage-build-evidence', 'release-09716b1416ac', 'stage-build-release-09716b1416ac'),
        ('stage-build-evidence', 'ubsan-f0f9f14387ac', 'stage-build-ubsan-f0f9f14387ac'),
        ('stage-network-evidence', 'quic-evidence-b1ee15402189', 'stage-smoke-b1ee15402189'),
        ('stage-network-evidence', 'quic-evidence-e78a98805296', 'stage-overflow-e78a98805296'),
        ('stage-network-evidence', 'quic-evidence-c141aa16256a', 'stage-matrix-c141aa16256a'),
    ]
    reports = []
    for group, name, archived in selections:
        source, target = cache / group / name, destination / archived
        assert source.is_dir() and not target.exists(), (source, target)
        assert not list(source.rglob('*.key'))
        shutil.copytree(source, target)
        original = {p.relative_to(source).as_posix(): sha(p) for p in source.rglob('*') if p.is_file()}
        copied = {p.relative_to(target).as_posix(): sha(p) for p in target.rglob('*') if p.is_file()}
        assert original == copied
        manifest = json.loads((target / 'manifest.json').read_text())
        assert manifest['passed']
        report = {'archive': archived, 'original_runtime': f'/home/alan/.cache/tyche-prototypes/quic-20260919/{group}/{name}',
                  'copied_utc': datetime.now(timezone.utc).isoformat(), 'files_copied': len(copied), 'source_sha256': copied}
        if group == 'stage-build-evidence':
            assert manifest['source_unchanged']
            for filename, digest in manifest['source_sha256'].items():
                assert sha(target / 'source' / filename) == digest
            assert all(c['code'] == 0 for c in manifest['commands'])
            commands = json.loads((target / 'compile_commands.json').read_text())
            expected = '-O3' if manifest['configuration'] == 'release' else '-fsanitize=undefined'
            assert all(expected in row['command'] for row in commands)
            if manifest['test_requested']:
                assert '100% tests passed, 0 tests failed out of 6' in (target / '03.stdout.txt').read_text()
                runs = list((target / 'runs').glob('quic-evidence-*/result.json'))
                assert len(runs) == 1
                run_result = json.loads(runs[0].read_text())
                assert run_result['worker_sha256'] == manifest['binary_sha256']['quic_worker']
                for filename, digest in run_result['source_sha256'].items():
                    assert manifest['source_sha256'][filename] == digest
                report['quic_byte_audit'] = audit_run(runs[0].parent)
        (target / 'archive.json').write_text(json.dumps(report, indent=2))
        reports.append({k: v for k, v in report.items() if k != 'source_sha256'})
        print(json.dumps({'archive': archived, 'files': len(copied), 'verified': True}), flush=True)
    (destination / 'stage-archive-index.json').write_text(json.dumps(reports, indent=2))


if __name__ == '__main__':
    main()
