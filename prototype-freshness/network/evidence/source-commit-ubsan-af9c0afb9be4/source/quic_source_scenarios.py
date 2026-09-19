#!/usr/bin/env python3
"""Finite source commit integration faults; no real market/order connection."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import tempfile
import time
import traceback

from quic_scenarios import Suite, Process, sha
from audit_crash_evidence import events, checkpoint, seal


def source(t, mode='batch', capacity=64, wait=100000000, create=True, label='source', failure=False):
    return Process(t, label, [t.suite.worker, 'source', t.source_root, t.token,
                   'create' if create else 'open', t.port, t.suite.certs, t.suite.certs / 'client.der'],
                   expect_failure=failure, environment_overrides={
                       'TYCHE_QUIC_SOURCE_MODE': mode, 'TYCHE_QUIC_SOURCE_CAPACITY': str(capacity),
                       'TYCHE_QUIC_SOURCE_WAIT_NS': str(wait if mode == 'batch' else 0)})


def start(t, **kwargs):
    s = source(t, **kwargs)
    r = t.node('receiver')
    r.command('connect')
    r.until(lambda v: v['ready'] and v['flows'][0]['D'] == 1)
    return s, r


def submit(s, count=4, flow=1):
    s.request += 1
    req = s.request
    s.write(f'{req} publish {flow} {count}')
    return req


def receipt(s, req):
    return next((r for r in s.rows if r.get('request') == req), None) or s.wait(lambda r: r.get('request') == req)


def byte_check(t, flow=1):
    history = events(t.source_root / f'PROTOTYPE-source-{flow}.bin')
    raw = (t.replica_root / f'PROTOTYPE-replica-{100 + flow}.bin').read_bytes()
    remote = []
    assert len(raw) % 124 == 0
    for offset in range(0, len(raw), 124):
        length, *words = struct.unpack_from('>I15Q', raw, offset)
        assert length == 120 and words[:2] == [0x5459515500000001, 100 + flow]
        assert seal(words[2:-1]) == words[-1]
        remote.append(tuple(words[2:]))
    t.check(history == remote, 'source and replica bytes encode every identical committed event')
    return history


def consume_and_check(t, r, count, create=True):
    r.until(lambda v: v['ready'] and v['flows'][0]['D'] == count)
    c = t.consumer(create=create)
    final = c.command('consume 0')
    history = byte_check(t)
    cp = checkpoint(t.path / 'PROTOTYPE-consumer-1.bin')
    t.check(final['cursor'] == count and cp[5] == cp[6] == count,
            'consumer saves processing result and exact cursor together')
    t.check(cp[8] == sum(e[8] for e in history) and cp[9] == sum(e[7] for e in history)
            and cp[10] == seal([e[-1] for e in history]), 'consumer accumulation has no omitted or duplicate event')
    return c


def ordered(t, mode):
    s, r = start(t, mode=mode)
    row = s.command('publish 1 24')
    t.check(row['event'] == 'ack' and len(row['receipts']) == 24, 'one command retains all individual commit receipts')
    t.check(all(v['accepted'] and v['state'] == 1 and 0 < v['sync_ns'] <= v['published_ns'] <= v['confirmed_ns']
                for v in row['receipts']), 'success follows sync and complete publication')
    v = s.command('status')['publishers'][0]
    t.check(v['committed'] == 24 and v['syncs'] == (24 if mode == 'worker' else 3),
            'single writer and batching have distinct measured sync counts')
    c = consume_and_check(t, r, 25)
    c.exit()
    consume_and_check(t, r, 25, create=False)


def gate(t, mode):
    s, r = start(t, mode=mode)
    s.command('source_gate 1')
    req = submit(s)
    held = s.until(lambda v: v['publishers'][0]['at_gate'])
    t.check(held['flows'][0]['head'] == 1 and receipt_if_present(s, req) is None,
            'control status progresses while disk is gated; admission is not success')
    t.check(len(events(t.source_root / 'PROTOTYPE-source-1.bin')) == (2 if mode == 'worker' else 5),
            'full unconfirmed bytes are retained but not advertised')
    t.check(r.command('status')['flows'][0]['D'] == 1, 'remote cannot consume the unsynced source tail')
    s.command('source_release 1')
    row = receipt(s, req)
    t.check(row['event'] == 'ack' and all(v['state'] == 1 for v in row['receipts']), 'gate release confirms original proposals')
    consume_and_check(t, r, 5)


def receipt_if_present(s, req):
    return next((r for r in s.rows if r.get('request') == req), None)


def overflow(t):
    s, r = start(t, capacity=4)
    s.command('source_gate 1')
    req = submit(s, 6)
    held = s.until(lambda v: v['publishers'][0]['at_gate'])
    t.check(held['publishers'][0]['max_pending'] == 4 and held['failed_sources'] == 1,
            'bounded queue includes inflight records and latches the required-input gap')
    r.until(lambda v: not v['ready'])
    t.check(r.command('status')['flows'][0]['validity'] == 'gap', 'source overflow restricts subscribed remote dependents')
    s.command('source_release 1')
    row = receipt(s, req)
    t.check(row['event'] == 'command_error' and row['unattempted'] == 1
            and [v['state'] for v in row['receipts']] == [1, 1, 1, 1, 0],
            'accepted prefix commits, rejected identity and never-attempted suffix remain explicit')
    before = (t.source_root / 'PROTOTYPE-source-1.bin').read_bytes()
    req2 = submit(s, 1)
    t.check(receipt(s, req2)['event'] == 'command_error', 'latched source does not automatically retry')
    t.check((t.source_root / 'PROTOTYPE-source-1.bin').read_bytes() == before, 'retry rejection does not append or overwrite')
    s.exit()
    replacement = source(t, create=False, label='replacement', failure=True)
    replacement.p.wait(timeout=15)
    replacement.exit(expected=1)
    t.check((t.source_root / 'PROTOTYPE-source-1.bin').read_bytes() == before, 'takeover cannot erase an ingress gap')


def sync_error(t):
    s, r = start(t)
    s.command('source_sync_error 1')
    row = receipt(s, submit(s))
    t.check(row['event'] == 'command_error' and all(v['state'] == 2 for v in row['receipts']),
            'failed durable confirmation is unknown, not acknowledged success')
    t.check(s.command('status')['flows'][0]['head'] == 1, 'failed source save cannot advance visible head')
    r.until(lambda v: not v['ready'])
    before = (t.source_root / 'PROTOTYPE-source-1.bin').read_bytes()
    t.check(len(events(t.source_root / 'PROTOTYPE-source-1.bin')) == 5, 'unknown full tail retained for investigation')
    s.exit()
    replacement = source(t, create=False, label='replacement', failure=True)
    replacement.p.wait(timeout=15)
    replacement.exit(expected=1)
    t.check((t.source_root / 'PROTOTYPE-source-1.bin').read_bytes() == before, 'detected save failure is not silently repaired')


def completion_limit(t):
    s, r = start(t, capacity=1)
    r.command('subscribe 3')
    r.until(lambda v: v['ready'] and v['flows'][1]['D'] == 1)
    s.command('source_gate 1')
    s.command('source_gate 2')
    first, second = submit(s, 1, 1), submit(s, 1, 2)
    held = s.until(lambda v: all(p['at_gate'] for p in v['publishers']))
    t.check(held['source_pending_commands'] == 2, 'both bounded completion slots are occupied by unconfirmed calls')
    rejected = receipt(s, submit(s, 1, 1))
    state = s.command('status')
    t.check(rejected['event'] == 'command_error' and state['failed_sources'] == 1
            and state['flows'][0]['validity'] == 'gap', 'completion-capacity rejection latches required-input gap')
    r.until(lambda v: not v['ready'])
    s.command('source_release 1')
    s.command('source_release 2')
    t.check(receipt(s, first)['event'] == receipt(s, second)['event'] == 'ack',
            'previously admitted identities still drain after completion-capacity rejection')
    t.check(s.command('status')['flows'][0]['validity'] == 'gap', 'drain does not clear completion-capacity input gap')


def crash(t, point):
    s, r = start(t)
    s.command(f'source_arm 1 {point}')
    req = submit(s)
    s.p.wait(timeout=15)
    s.exit(expected=77) # Confirm exit before starting a new publisher.
    t.check(receipt_if_present(s, req) is None, 'crashed call has no fabricated success response')
    path = t.source_root / 'PROTOTYPE-source-1.bin'
    before = path.read_bytes()
    (t.path / 'source-at-crash.bin').write_bytes(before)
    if point == 2:
        t.check(len(before) == 2 * 96 + 48, 'partial source record retained')
        replacement = source(t, create=False, label='replacement', failure=True)
        replacement.p.wait(timeout=15)
        replacement.exit(expected=1)
        t.check(path.read_bytes() == before, 'partial tail is neither truncated nor promoted')
        return
    complete = 0 if point == 0 else 1 if point == 1 else 4
    replacement = source(t, create=False, label='replacement')
    head = replacement.command('status')['flows'][0]['head']
    t.check(head == complete + 2 and path.read_bytes()[:len(before)] == before,
            'confirmed exit recovers exact complete log prefix before appending fresh epoch')
    r.until(lambda v: v['closed'])
    r.command('connect')
    c = consume_and_check(t, r, head)
    t.check(not c.command('status 0')['allowed'], 'replay does not bypass startup reconciliation')
    row = replacement.command('publish 1 1')
    t.check(row['receipts'][0]['sequence'] == head + 1 and row['receipts'][0]['epoch'] == 2,
            'new admission follows recovered sequence without resubmitting old calls')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', required=True)
    parser.add_argument('--evidence-root', required=True)
    parser.add_argument('--completion-limit-only', action='store_true')
    args = parser.parse_args()
    suite = Suite(args.worker, args.evidence_root)
    result = {'worker_sha256': sha(suite.worker), 'source_sha256': {
        p.name: sha(p) for p in Path(__file__).parent.iterdir() if p.suffix in ['.cpp', '.hpp', '.py']}}
    try:
        suite.scenario('completion-limit', completion_limit)
        if not args.completion_limit_only:
            for mode in ['worker', 'batch']:
                suite.scenario(mode + '-ordered', lambda t, m=mode: ordered(t, m))
                suite.scenario(mode + '-gate', lambda t, m=mode: gate(t, m))
            suite.scenario('overflow', overflow)
            suite.scenario('source-save-error', sync_error)
            for point in range(7):
                suite.scenario(f'source-crash-{point}', lambda t, p=point: crash(t, p))
        result['passed'] = True
    except Exception:
        result.update(passed=False, error=traceback.format_exc())
    finally:
        result['checks'] = suite.checks
        (suite.root / 'result.json').write_text(json.dumps(result, indent=2))
        private = suite.private.resolve()
        assert private.parent == Path(tempfile.gettempdir()).resolve() and private.name.startswith('tyche-quic-test-')
        shutil.rmtree(private)
    print(json.dumps({'evidence': str(suite.root), 'passed': result['passed'], 'checks': len(suite.checks), 'error': result.get('error')}), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
