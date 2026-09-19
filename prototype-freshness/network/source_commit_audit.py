#!/usr/bin/env python3
"""Offline source/replica/checkpoint/receipt decode, independent of worker assertions."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys

CPP = Path(__file__).resolve().parents[1] / 'cpp'
sys.path.insert(0, str(CPP))
from audit_crash_evidence import checkpoint, seal
from quic_evidence_audit import decode_replica


def audit(root):
    result = json.loads((root / 'result.json').read_text())
    assert result['passed'] and all(c['passed'] for c in result['checks'])
    folders = sorted(p for p in root.iterdir() if (p / 'source').is_dir())
    assert len(folders) in [13, 14] # Earlier, explicitly superseded runs preceded the completion-bound regression.
    cases = []
    for folder in folders:
        histories, report = {}, {'name': folder.name, 'flows': []}
        for flow in [1, 2]:
            path = folder / 'source' / f'PROTOTYPE-source-{flow}.bin'
            raw = path.read_bytes()
            whole, tail = divmod(len(raw), 96)
            assert tail == (48 if folder.name == 'source-crash-2' and flow == 1 else 0)
            history = []
            for k in range(whole):
                event = struct.unpack_from('<QQQQqqqQQQBB6xQ', raw, k * 96)
                assert event[0] == k + 1 and event[10:12] == (0, 1)
                assert seal(event[:-1]) == event[-1]
                assert event[9] == event[7] ^ (event[8] << 16) ^ event[2] ^ 0xCAFE1234
                history.append(event)
            histories[flow] = history
            replica, replica_tail = decode_replica(folder / 'replica' / f'PROTOTYPE-replica-{100+flow}.bin', 100+flow)
            assert not replica_tail and replica == history[:len(replica)]
            cp = folder / f'PROTOTYPE-consumer-{flow}.bin'
            cursor = None
            if cp.exists():
                state = checkpoint(cp)
                assert state[2:4] == (100 + flow, 900 + flow)
                cursor = state[5]
                prefix = replica[:cursor]
                assert len(prefix) == cursor and state[5] == state[6]
                assert state[7] == (prefix[-1][-1] if prefix else 0)
                assert state[8] == sum(e[8] for e in prefix) and state[9] == sum(e[7] for e in prefix)
                assert state[10] == seal([e[-1] for e in prefix]) and state[14] == 0
            report['flows'].append({'flow': flow, 'source_records': whole, 'source_tail_bytes': tail,
                                    'replica_records': len(replica), 'checkpoint_cursor': cursor})
        if folder.name.startswith('source-crash-'):
            before = (folder / 'source-at-crash.bin').read_bytes()
            after = (folder / 'source' / 'PROTOTYPE-source-1.bin').read_bytes()
            assert after.startswith(before)
            point = int(folder.name.rsplit('-', 1)[-1])
            assert len(before) == {0: 96, 1: 192, 2: 240, 3: 480, 4: 480, 5: 480, 6: 480}[point]
            if point == 2:
                assert before == after
            else:
                prefix = 1 if point == 0 else 2 if point == 1 else 5
                assert len(histories[1]) == prefix + 2 and histories[1][prefix][1] == 2
        count = 0
        for path in folder.glob('*.stdout.jsonl'):
            for row in (json.loads(s) for s in path.read_text().splitlines()):
                for receipt in row.get('receipts', []):
                    count += 1
                    key = (receipt['sequence'], receipt['epoch'], receipt['seal'])
                    saved = {(e[0], e[1], e[-1]) for e in histories[row['flow']]}
                    if receipt['state'] in [1, 2]:
                        assert receipt['accepted'] and key in saved
                    else:
                        assert key not in saved
                    if receipt['state'] == 1:
                        assert 0 < receipt['enqueued_ns'] <= receipt['sync_ns'] <= receipt['published_ns'] <= receipt['confirmed_ns']
                    if row['event'] == 'ack':
                        assert receipt['state'] == 1
        report['receipts_verified'] = count
        assert not list(folder.glob('*.simulated-submissions.jsonl'))
        for path in folder.glob('*.exit.json'):
            record = json.loads(path.read_text())
            assert record['code'] == record['expected']
        for path in folder.glob('*.stderr.txt'):
            assert 'runtime error:' not in path.read_text()
        assert json.loads((folder / 'unlink.json').read_text())['code'] == 0
        cases.append(report)
    return {'passed': True, 'cases': cases, 'checks': len(result['checks']), 'worker_sha256': result['worker_sha256'],
            'completion_limit_covered': any(f.name == 'completion-limit' for f in folders)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    report = audit(args.root)
    report['audited_utc'] = datetime.now(timezone.utc).isoformat()
    report['audit_tool_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (args.root / 'source-commit-audit.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'passed': True, 'root': str(args.root), 'cases': len(report['cases']), 'checks': report['checks']}))
