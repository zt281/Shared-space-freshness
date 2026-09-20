#!/usr/bin/env python3
"""Offline source/replica/checkpoint decode for the remote save-queue scenarios, independent of worker assertions."""
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

CRASH_JOURNAL_BYTES = {0: 124, 1: 248, 2: 248 + 62, 3: 620, 4: 620, 5: 620, 6: 620}
CRASH_RECOVERED_PREFIX = {0: 1, 1: 2, 3: 5, 4: 5, 5: 5, 6: 5}


def audit(root):
    result = json.loads((root / 'result.json').read_text())
    assert result['passed'] and all(c['passed'] for c in result['checks'])
    folders = sorted(p for p in root.iterdir() if (p / 'source').is_dir())
    assert len(folders) == 13, (root, 'incomplete remote scenario set')
    cases = []
    for folder in folders:
        histories, report = {}, {'name': folder.name, 'flows': []}
        for flow in [1, 2]:
            history = []
            raw = (folder / 'source' / f'PROTOTYPE-source-{flow}.bin').read_bytes()
            whole, tail = divmod(len(raw), 96)
            assert tail == 0
            for k in range(whole):
                event = struct.unpack_from('<QQQQqqqQQQBB6xQ', raw, k * 96)
                assert event[0] == k + 1 and event[10:12] == (0, 1)
                assert seal(event[:-1]) == event[-1]
                assert event[9] == event[7] ^ (event[8] << 16) ^ event[2] ^ 0xCAFE1234
                history.append(event)
            histories[flow] = history
            replica_tail_expected = 62 if folder.name == 'remote-crash-2' and flow == 1 else 0
            replica, replica_tail = decode_replica(folder / 'replica' / f'PROTOTYPE-replica-{100+flow}.bin', 100+flow)
            assert len(replica_tail) == replica_tail_expected and replica == list(history[:len(replica)])
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
            report['flows'].append({'flow': flow, 'source_records': whole,
                                    'replica_records': len(replica), 'replica_tail_bytes': len(replica_tail),
                                    'checkpoint_cursor': cursor})
        if folder.name.startswith('remote-crash-'):
            point = int(folder.name.rsplit('-', 1)[-1])
            before = (folder / 'replica-at-crash.bin').read_bytes()
            after = (folder / 'replica' / 'PROTOTYPE-replica-101.bin').read_bytes()
            assert len(before) == CRASH_JOURNAL_BYTES[point]
            if point == 2:
                assert after == before
            else:
                assert after.startswith(before)
                assert len(histories[1]) == 5 and report['flows'][0]['replica_records'] == 5
                assert report['flows'][0]['checkpoint_cursor'] == 5
        if folder.name == 'remote-save-error':
            assert report['flows'][0]['replica_records'] == 5 and report['flows'][0]['checkpoint_cursor'] == 1
        if folder.name == 'overflow':
            assert report['flows'][0]['replica_records'] == 7 and report['flows'][0]['checkpoint_cursor'] == 7
        rows = [json.loads(s) for path in folder.glob('*.stdout.jsonl') for s in path.read_text().splitlines()]
        assert not [r for r in rows if r.get('event') == 'worker_error']
        overflow_events = [r for r in rows if r.get('event') == 'remote_overflow']
        assert (len(overflow_events) == 1) == (folder.name == 'overflow')
        # A failed save reports exactly one failure; overflow closes without a storage failure, though
        # frames already inside the same receive job may still trip the closed-connection guard.
        failure_events = [r for r in rows if r.get('event') == 'failure']
        if folder.name == 'remote-save-error':
            assert len(failure_events) == 1
        elif folder.name != 'overflow':
            assert not failure_events
        for path in folder.glob('*.exit.json'):
            record = json.loads(path.read_text())
            assert record['code'] == record['expected']
        for path in folder.glob('*.stderr.txt'):
            assert 'runtime error:' not in path.read_text()
        assert json.loads((folder / 'unlink.json').read_text())['code'] == 0
        cases.append(report)
    return {'passed': True, 'cases': cases, 'checks': len(result['checks']), 'worker_sha256': result['worker_sha256']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    report = audit(args.root)
    report['audited_utc'] = datetime.now(timezone.utc).isoformat()
    report['audit_tool_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (args.root / 'remote-commit-audit.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'passed': True, 'root': str(args.root), 'cases': len(report['cases']), 'checks': report['checks']}))
