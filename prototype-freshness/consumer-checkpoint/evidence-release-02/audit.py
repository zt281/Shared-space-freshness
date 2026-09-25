#!/usr/bin/env python3
"""Independently decode retained C++ experiment records and recalculate results."""
import csv
import hashlib
import json
from pathlib import Path
import struct
import sys

MASK = (1 << 64) - 1
SEED = 1469598103934665603
MAGIC = 0x5459434845505231


def mix(h, v):
    return ((h ^ v) * 1099511628211) & MASK


def seal(words):
    h = SEED
    for word in words:
        h = mix(h, word)
    return h


def read(path, kind):
    data = path.read_bytes()
    assert len(data) >= 32 and len(data) % 8 == 0, path
    words = struct.unpack('<' + 'Q' * (len(data) // 8), data)
    assert words[:2] == (MAGIC, kind), path
    assert words[2] == len(words) - 4 and seal(words[:-1]) == words[-1], path
    return list(words[3:-1])


def state(source, cursor):
    assert source[0] == 1 and len(source) == 2 + 5 * source[1]
    assert 0 <= cursor <= source[1]
    total, chain = 0, SEED
    for i in range(cursor):
        event = source[2 + 5*i:7 + 5*i]
        seq, price, quantity, parameter, fit = event
        assert seq == i + 1
        total = (total + price * quantity + parameter + fit) & MASK
        chain = mix(chain, seal(event))
    return [1, cursor, total, chain]


def audit(root):
    observations = [json.loads(line) for line in (root / 'checks.jsonl').read_text().splitlines()]
    assert observations and all(o['pass'] for o in observations)
    summary = json.loads((root / 'summary.json').read_text())
    assert summary == {'checks_passed': len(observations), 'status': 'pass'}
    decoded = []
    damaged = {'corrupt-input', 'corrupt-checkpoint'}
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        name = directory.name
        if name in damaged:
            path = directory / ('PROTOTYPE-inputs.bin' if name == 'corrupt-input' else 'PROTOTYPE-checkpoint.bin')
            try:
                read(path, 1 if name == 'corrupt-input' else 2)
            except AssertionError:
                decoded.append({'scenario': name, 'intentional_corruption_detected': True})
                continue
            raise AssertionError(f'{name}: injected corruption was not detected')
        source_path = directory / 'PROTOTYPE-inputs.bin'
        if name == 'missing-input':
            assert not source_path.exists()
            source_path = directory / 'retained-input.bin'
        source = read(source_path, 1)
        if name == 'wrong-algorithm':
            assert source[0] == 99
            decoded.append({'scenario': name, 'unsupported_algorithm': 99})
            continue
        count = source[1]
        # Independent generated input oracle, including changing parameters/fit.
        for i in range(1, count + 1):
            assert source[2 + 5*(i-1):2 + 5*i] == [i, 100+i, 1+i % 3, 10+i//4, 200+i*7]
        checkpoint_path = directory / 'PROTOTYPE-checkpoint.bin'
        if name == 'missing-checkpoint':
            assert not checkpoint_path.exists()
            checkpoint_path = directory / 'retained-checkpoint.bin'
        checkpoint = read(checkpoint_path, 2)
        assert checkpoint == state(source, checkpoint[1]), directory
        stop_path = directory / 'PROTOTYPE-stop.bin'
        if name == 'missing-stop':
            assert not stop_path.exists()
            stop_path = directory / 'retained-stop.bin'
        stop = read(stop_path, 3)
        assert stop == ([1, 1] if name == 'stop-survives' else [0, 0]), directory
        for snapshot in ('checkpoint-at-crash.bin', 'checkpoint-at-failure.bin'):
            if (directory / snapshot).exists():
                at_crash = read(directory / snapshot, 2)
                assert at_crash == state(source, at_crash[1])
                if name.startswith('checkpoint-crash-'):
                    assert at_crash[1] == (8 if int(name[-1]) < 4 else 16)
                else:
                    assert at_crash[1] == (0 if name.endswith('6') else 8)
        broker_path = directory / 'PROTOTYPE-broker.bin'
        should_send = name in {'normal-submission', 'submission-crash-3'}
        assert broker_path.exists() == should_send, directory
        if should_send:
            assert read(broker_path, 6) == [8, 1]
        intent_path = directory / 'PROTOTYPE-intent.bin'
        if intent_path.exists():
            intent = read(intent_path, 4)
            if name == 'wrong-intent':
                assert intent[3] != state(source, intent[2])[3]
            else:
                seq = intent[2]
                assert intent[:2] == [1, 1]
                assert intent[3] == state(source, seq)[3]
                assert intent[4] == seal(source[2+5*(seq-1):2+5*seq])
                assert intent[5] == source[2+5*(seq-1)+2]
                assert intent[6] == {'submission-crash-1': 4, 'submission-crash-2': 2,
                                     'submission-crash-3': 3, 'normal-submission': 3,
                                     'intent-save-7': 4, 'attempt-save-6': 4, 'attempt-save-7': 2}[name]
        observations_path = directory / 'observations.jsonl'
        if observations_path.exists():
            for observation in map(json.loads, observations_path.read_text().splitlines()):
                expected = state(source, observation['computed'])
                assert [observation['sum'], observation['chain']] == expected[2:]
                assert observation['pending'] == observation['computed'] - observation['saved']
                assert observation['pending_bytes'] == observation['pending'] * 40
                if observation['failed'] or observation['stopped'] or observation['unknown']:
                    assert observation['allowed'] == 0
                if observation['label'] == 'at-bound':
                    assert observation['pending'] == 4 and observation['allowed'] == 0
                if observation['label'] == 'recovered' and name.startswith('checkpoint-crash-'):
                    assert observation['allowed'] == 0
        result_path = directory / 'PROTOTYPE-result.bin'
        if name == 'publication-3':
            assert not result_path.exists()
            assert not (directory / 'PROTOTYPE-downstream.bin').exists()
        if result_path.exists():
            published = read(result_path, 5)
            assert published == state(source, 8)
            assert read(directory / 'PROTOTYPE-downstream.bin', 7) == [8, seal(published)]
            assert checkpoint[1] == 0  # Consumption preceded producer checkpoint.
        decoded.append({'scenario': name, 'saved_cursor': checkpoint[1], 'saved_sum': checkpoint[2],
                        'saved_chain': checkpoint[3], 'stopped': stop[1], 'mock_submissions': int(should_send)})
    timings = []
    for row in csv.DictReader((root / 'timings.csv').open()):
        directory = root / f"timing-{row['round']}-{row['mode']}"
        events = list(csv.DictReader((directory / 'events.csv').open()))
        assert len(events) == int(row['events']) == 200
        latency = []
        completions = []
        for i, event in enumerate(events):
            planned, computed, durable = (float(event[k]) for k in ('planned_ms', 'computed_ms', 'durable_ms'))
            assert int(event['sequence']) == i + 1
            assert planned == (i//20)*100
            assert planned <= computed <= durable
            latency.append(durable - planned)
            completions.append(durable)
        assert completions == sorted(completions)
        assert len(set(completions)) == int(row['checkpoint_commits'])
        assert int(row['sync_calls']) == 2 * int(row['checkpoint_commits'])
        latency.sort()
        # CSV precision is six significant figures; use rounding tolerance, not exact floats.
        for column, value in [('p50_durable_ms', latency[99]), ('p99_durable_ms', latency[197]),
                              ('max_durable_ms', latency[-1])]:
            assert abs(float(row[column]) - value) < .02, (column, row, value)
        assert read(directory / 'PROTOTYPE-checkpoint.bin', 2)[1] == 200
        timings.append(row)
    assert len(timings) == 6
    files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(root.rglob('*')) if p.is_file() and p.name not in {'audit.json', 'manifest.json'}}
    report = {'status': 'pass', 'cpp_observations': len(observations), 'scenarios': decoded,
              'timings': timings, 'sha256': files}
    (root / 'audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f"Independent audit PASS: {len(decoded)} scenarios, {len(timings)*200} timed events, {len(files)} files")
    return report


if __name__ == '__main__':
    audit(Path(sys.argv[1]))
