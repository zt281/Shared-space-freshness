#!/usr/bin/env python3
"""Read-only independent decode of the retained source/replica/checkpoint evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct

from audit_crash_evidence import checkpoint, events, seal


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode_replica(path, identity):
    data = path.read_bytes()
    records = []
    whole, tail = divmod(len(data), 124)
    for k in range(whole):
        length, *words = struct.unpack_from('>I15Q', data, k*124)
        assert length == 120 and words[:2] == [0x5459515500000001, identity], path
        record = tuple(words[2:])
        assert record[0] == k+1 and record[10] in [0,1] and record[11] in [0,1], path
        assert seal(record[:-1]) == record[-1], path
        assert record[9] == record[7] ^ (record[8] << 16) ^ record[2] ^ 0xCAFE1234, path
        records.append(record)
    return records, data[whole*124:] if tail else b''


def audit_run(root):
    result = json.loads((root / 'result.json').read_text())
    assert result['passed'] and all(check['passed'] for check in result['checks']), root
    cases = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and (p / 'source').is_dir()):
        flows = []
        for f in [1,2]:
            history = events(folder / 'source' / f'PROTOTYPE-source-{f}.bin')
            replica, tail = decode_replica(folder / 'replica' / f'PROTOTYPE-replica-{100+f}.bin', 100+f)
            assert replica == history[:len(replica)], (folder, f, 'source/replica mismatch')
            if tail:
                assert folder.name == 'receiver-crash-1' and f == 1 and len(tail) == 62
                next_record = history[len(replica)]
                expected = struct.pack('>I15Q',120,0x5459515500000001,100+f,*next_record)
                assert expected.startswith(tail), 'partial tail changed'
            cp = folder / f'PROTOTYPE-consumer-{f}.bin'
            if cp.exists():
                state = checkpoint(cp)
                assert state[2] == 100+f and state[3] == 900+f
                prefix = replica[:state[5]]
                assert len(prefix) == state[5]
                assert state[8] == sum(e[8] for e in prefix) and state[9] == sum(e[7] for e in prefix)
                assert state[10] == seal([e[-1] for e in prefix])
                assert state[7] == (prefix[-1][-1] if prefix else 0)
                external = Path(str(cp)+'.simulated-submissions.jsonl')
                submitted = external.read_text().splitlines() if external.exists() else []
                assert len(submitted) == (1 if folder.name == 'selective-replay-checkpoint' and f == 1 else 0)
            else:
                state = None
            flows.append({'flow': f, 'source_records': len(history), 'replica_full_records': len(replica),
                          'tail_bytes': len(tail), 'checkpoint_cursor': state[5] if state else None})
        if folder.name == 'save-error':
            assert flows[0]['replica_full_records'] == 2 and flows[0]['checkpoint_cursor'] == 1
        if folder.name in ['wrong-pin','missing-client-cert','wrong-ca']:
            assert all(flow['replica_full_records'] == 0 for flow in flows)
        cases.append({'name': folder.name, 'flows': flows})
    assert len(cases) == 14, (root, 'incomplete final scenario set')
    for path in root.rglob('*.stderr.txt'):
        assert 'runtime error:' not in path.read_text(), path
    for path in root.rglob('*.exit.json'):
        code = json.loads(path.read_text())
        assert code['code'] == code['expected'], path
    return {'path': str(root), 'checks': len(result['checks']), 'cases': cases}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('debug')
    parser.add_argument('ubsan')
    args = parser.parse_args()
    evidence = Path(__file__).resolve().parent / 'evidence-quic-wsl'
    reports = []
    for selected, name in [(args.debug,'debug'),(args.ubsan,'ubsan')]:
        root = evidence / selected
        manifest = json.loads((root / 'manifest.json').read_text())
        assert manifest['passed'] and manifest['source_unchanged'] and manifest['configuration'] == name
        for file, digest in manifest['source_sha256'].items():
            assert sha(root / 'source' / file) == digest
        if name == 'ubsan':
            commands = json.loads((root / 'compile_commands.json').read_text())
            assert all('-fsanitize=undefined' in c['command'] and '-fno-sanitize-recover=all' in c['command'] for c in commands)
        assert len(manifest['quic_runs']) == 1, 'select one exact run, never newest mtime'
        run = root / manifest['quic_runs'][0]
        result = json.loads(run.read_text())
        assert result['worker_sha256'] == manifest['binary_sha256']['quic_worker']
        for file, digest in result['source_sha256'].items():
            assert manifest['source_sha256'][file] == digest, (file, 'build/run source drift')
        reports.append(audit_run(run.parent))
        testlog = (root / '04.stdout.txt').read_text()
        assert '100% tests passed, 0 tests failed out of 6' in testlog, testlog
    private_keys = [str(p) for p in evidence.rglob('*.key')]
    assert not private_keys, 'test keys must not be retained with evidence'
    files = {p.relative_to(evidence).as_posix(): sha(p) for p in sorted(evidence.rglob('*')) if p.is_file() and p.name != 'audit.json'}
    report = {'audited_utc':datetime.now(timezone.utc).isoformat(), 'selected_runs': reports, 'files': len(files), 'sha256': files,
              'scope': 'byte integrity, source replicas and consumer results; not throughput, physical network or host power loss'}
    (evidence / 'audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='sha256'}, indent=2))


if __name__ == '__main__':
    main()
