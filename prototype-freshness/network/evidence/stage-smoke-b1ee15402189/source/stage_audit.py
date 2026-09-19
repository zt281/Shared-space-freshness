#!/usr/bin/env python3
"""Offline byte/clock/stage audit; no benchmark process or timing sampling runs here."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE if (HERE / 'audit_crash_evidence.py').exists() else HERE.parent / 'cpp'))
from audit_crash_evidence import events, checkpoint, seal


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def distribution(values):
    if not values:
        return None
    values = sorted(values)
    return {'n': len(values), 'p50_ms': values[(len(values) - 1) // 2] / 1e6,
            'p99_ms': values[math.ceil(.99 * len(values)) - 1] / 1e6, 'max_ms': values[-1] / 1e6}


def trace(path):
    data = rows(path)
    summary = data[-1]
    assert summary['stage'] == 'trace_summary' and summary['clock'] == 'CLOCK_MONOTONIC'
    assert summary['attempted'] == len(data) - 1 and summary['overflow'] == summary['clock_errors'] == 0
    assert data[0]['stage'] == 'trace_started' and data[-2]['stage'] == 'trace_finished'
    per_thread = defaultdict(int)
    for index, row in enumerate(data[:-1]):
        assert row['index'] == index and row['ns'] > 0
        assert row['ns'] >= per_thread[row['tid']]
        per_thread[row['tid']] = row['ns']
    return data[:-1]


def audit_case(root, expect_overflow=False):
    summary = json.loads((root / 'summary.json').read_text())
    plan = json.loads((root / 'planned.json').read_text())
    samples = json.loads((root / 'consumer-observations.json').read_text())
    assert summary['passed'] and len(plan) == summary['planned'] == round(summary['planned_rate'] * summary['input_seconds'])
    assert len({(p['identity'], p['sequence']) for p in plan}) == len(plan)
    assert not list(root.glob('*.simulated-submissions.jsonl'))
    for path in root.glob('*.exit.json'):
        assert json.loads(path.read_text()) == {'code': 0, 'expected': 0}
    assert len(list(root.glob('*.exit.json'))) == 4
    assert json.loads((root / 'unlink.json').read_text())['code'] == 0
    for row in samples:
        if row['validity'] in ['gap', 'expired', 'unknown', 'damaged', 'old_epoch']:
            assert not row['allowed']
    histories = {}
    for flow in [1, 2]:
        history = events(root / 'source' / f'PROTOTYPE-source-{flow}.bin')
        raw = (root / 'replica' / f'PROTOTYPE-replica-{100 + flow}.bin').read_bytes()
        assert len(raw) % 124 == 0
        replica = []
        for offset in range(0, len(raw), 124):
            length, *words = struct.unpack_from('>I15Q', raw, offset)
            assert length == 120 and words[:2] == [0x5459515500000001, 100 + flow]
            assert seal(words[2:-1]) == words[-1]
            replica.append(tuple(words[2:]))
        assert replica == history
        saved = checkpoint(root / f'PROTOTYPE-consumer-{flow}.bin')
        assert saved[2:4] == (100 + flow, 900 + flow) and saved[5] == saved[6] == len(history)
        assert saved[8] == sum(e[8] for e in history) and saved[9] == sum(e[7] for e in history)
        assert saved[10] == seal([e[-1] for e in history]) and saved[14] == 0
        assert len(history) == 1 + sum(p['flow'] == flow for p in plan)
        histories[flow] = history
    for p in plan:
        assert p['identity'] == 100 + p['flow'] and p['epoch'] == histories[p['flow']][p['sequence'] - 1][1]
        assert p['planned_ns'] == summary['input_start_ns'] + int(p['index'] * 1e9 / summary['planned_rate'])
        assert p['write_end_ns'] >= p['write_begin_ns'] >= p['planned_ns']
        observed = min(s['observed_ns'] for s in samples if s['flow'] == p['flow'] and s['cursor'] >= p['sequence'])
        assert observed == p['observed_complete_ns']

    stats = json.loads((root / 'quic-statistics.json').read_text())
    assert len(stats) == 6
    for sample in stats:
        for row in sample['value']['connections'] + sample['value']['streams']:
            assert sample['before_ns'] <= row['start_ns'] <= row['end_ns'] <= sample['after_ns']
            assert row['status'] == 0
    assert json.loads((root / 'resources.json').read_text()), 'resource samples required'
    result = {'case': root.name, 'planned': len(plan), 'trace_enabled': summary['trace_enabled'],
              'observed_in_window': sum(p['observed_complete_ns'] <= summary['input_end_ns'] for p in plan),
              'observer_upper_bound': distribution([p['observed_complete_ns'] - p['planned_ns'] for p in plan]),
              'expired_observations': sum(s['validity'] == 'expired' for s in samples)}
    if not summary['trace_enabled']:
        assert not list(root.glob('PROTOTYPE-*-trace.jsonl'))
        return result
    if expect_overflow:
        result['trace_incomplete'] = []
        for path in root.glob('PROTOTYPE-*-trace.jsonl'):
            info = rows(path)[-1]
            assert info['overflow'] > 0 and info['attempted'] > info['capacity']
            try:
                trace(path)
            except AssertionError:
                result['trace_incomplete'].append(path.name)
            else:
                raise AssertionError('ordinary audit must reject incomplete traces')
        assert len(result['trace_incomplete']) == 4
        return result

    traces = {label: trace(root / f'PROTOTYPE-{label}-trace.jsonl') for label in ['source', 'receiver', 'consumer-1', 'consumer-2']}
    for label, data in traces.items():
        envelope = json.loads((root / f'{label}.clock-envelopes.json').read_text())
        assert envelope['startup']['before_ns'] <= data[0]['ns'] <= envelope['startup']['after_ns']
        commands = {e['request']: e for e in envelope['commands']}
        for row in data:
            if row['stage'] == 'consumer_command':
                command = commands[row['request']]
                assert command['before_ns'] <= row['ns'] <= command['after_ns']

    def one(data, stage, p, by_request=False):
        found = [r for r in data if r['stage'] == stage and (r['request'] == p['request'] if by_request else
                 (r['identity'], r['sequence']) == (p['identity'], p['sequence']))]
        assert len(found) == 1, (root.name, stage, p, len(found))
        return found[0]

    segments = defaultdict(list)
    measured = []
    for p in plan:
        source, receiver, consumer = traces['source'], traces['receiver'], traces[f'consumer-{p["flow"]}']
        validated = one(receiver, 'remote_validated', p)
        first, last = validated['b'], validated['b'] + validated['c']
        callbacks = [r for r in receiver if r['stage'] == 'receive_callback' and r['a'] == validated['a']
                     and r['b'] < last and r['b'] + r['c'] > first]
        assert callbacks and min(r['b'] for r in callbacks) <= first and max(r['b'] + r['c'] for r in callbacks) >= last
        callback = max(callbacks, key=lambda r: r['ns'])
        jobs = [r for r in receiver if r['stage'] == 'receive_job' and (r['a'], r['b'], r['c']) == (callback['a'], callback['b'], callback['c'])]
        assert len(jobs) == 1
        milestones = [
            ('planned', p['planned_ns']),
            ('source_ingress', one(source, 'command_received', p, True)['ns']),
            ('source_job', one(source, 'command_started', p, True)['ns']),
            ('source_locked', one(source, 'source_locked', p)['ns']),
            ('source_written', one(source, 'source_written', p)['ns']),
            ('source_durable', one(source, 'source_sync_end', p)['ns']),
            ('source_published', one(source, 'source_published', p)['ns']),
            ('send', one(source, 'source_send', p)['ns']),
            ('last_receive_callback', callback['ns']),
            ('receive_job', jobs[0]['ns']),
            ('R', validated['ns']),
            ('remote_written', one(receiver, 'replica_written', p)['ns']),
            ('D', one(receiver, 'replica_sync_end', p)['ns']),
            ('V', one(receiver, 'replica_published', p)['ns']),
            ('consumer_begin', one(consumer, 'consumer_begin', p)['ns']),
            ('consumer_calculated', one(consumer, 'consumer_calculated', p)['ns']),
            ('checkpoint_opened', one(consumer, 'checkpoint_opened', p)['ns']),
            ('checkpoint_written', one(consumer, 'checkpoint_written', p)['ns']),
            ('checkpoint_synced', one(consumer, 'checkpoint_sync_end', p)['ns']),
            ('checkpoint_replaced', one(consumer, 'checkpoint_replaced', p)['ns']),
            ('checkpoint_dirsynced', one(consumer, 'checkpoint_dirsync_end', p)['ns']),
            ('A', one(consumer, 'consumer_completed', p)['ns']),
            ('observer', p['observed_complete_ns']),
        ]
        parts = {}
        for (left, begin), (right, end) in zip(milestones, milestones[1:]):
            assert end >= begin, (root.name, p['index'], left, right, begin, end)
            key = left + '_to_' + right
            parts[key] = end - begin
            segments[key].append(end - begin)
        clocks = dict(milestones)
        assert sum(parts.values()) == clocks['observer'] - clocks['planned']
        assert one(source, 'source_sync_end', p)['a'] == 1
        # Same-event direct syscall brackets, kept separately from the disjoint critical path.
        syscall = {}
        for label, data, begin_stage, end_stage in [
            ('source_fdatasync', source, 'source_sync_begin', 'source_sync_end'),
            ('replica_fdatasync', receiver, 'replica_sync_begin', 'replica_sync_end'),
            ('checkpoint_fdatasync', consumer, 'checkpoint_sync_begin', 'checkpoint_sync_end'),
            ('checkpoint_rename', consumer, 'checkpoint_replace_begin', 'checkpoint_replaced'),
            ('checkpoint_directory_fsync', consumer, 'checkpoint_dirsync_begin', 'checkpoint_dirsync_end'),
        ]:
            duration = one(data, end_stage, p)['ns'] - one(data, begin_stage, p)['ns']
            assert duration >= 0
            syscall[label] = duration
            segments[label].append(duration)
        measured.append({'index': p['index'], 'identity': p['identity'], 'epoch': p['epoch'], 'sequence': p['sequence'],
                         'milestones_ns': clocks, 'segments_ns': parts, 'syscalls_ns': syscall,
                         'complete_delay_ns': clocks['A'] - clocks['planned']})
    result['internal_in_window'] = sum(r['milestones_ns']['A'] <= summary['input_end_ns'] for r in measured)
    result['internal_complete_delay'] = distribution([r['complete_delay_ns'] for r in measured])
    result['segments'] = {key: distribution(values) for key, values in segments.items()}
    result['longest_events'] = sorted(measured, key=lambda r: r['complete_delay_ns'], reverse=True)[:5]
    result['events'] = measured
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--expect-overflow', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((args.root / 'manifest.json').read_text())
    assert manifest['passed'] and not list(args.root.rglob('*.key'))
    for name, digest in manifest['source_sha256'].items():
        assert hashlib.sha256((args.root / 'source' / name).read_bytes()).hexdigest() == digest
    result = {'passed': True, 'audited_utc': datetime.now(timezone.utc).isoformat(), 'expected_overflow': args.expect_overflow,
              'cases': [audit_case(args.root / case['name'], args.expect_overflow) for case in manifest['results']]}
    result['sha256'] = {str(p.relative_to(args.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(args.root.rglob('*')) if p.is_file() and p.name != 'stage-audit.json'}
    (args.root / 'stage-audit.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({'evidence': str(args.root), 'passed': True, 'cases': len(result['cases']),
                      'files': len(result['sha256']), 'planned': sum(c['planned'] for c in result['cases'])}))


if __name__ == '__main__':
    main()
