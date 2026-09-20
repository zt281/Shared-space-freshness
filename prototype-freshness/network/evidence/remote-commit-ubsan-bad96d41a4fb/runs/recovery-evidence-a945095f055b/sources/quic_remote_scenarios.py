#!/usr/bin/env python3
"""Finite remote save-queue integration faults; no real market/order connection."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import tempfile
import traceback

from quic_scenarios import Suite, Process, sha
from audit_crash_evidence import events, checkpoint, seal


def receiver(t, mode='batch', capacity=64, wait=2000000, create=True, label='receiver', failure=False):
    return Process(t, label, [t.suite.worker, 'receiver', t.replica_root, t.token,
                   'create' if create else 'open', t.port, t.suite.certs, t.suite.certs / 'server.der'],
                   expect_failure=failure, environment_overrides={
                       'TYCHE_QUIC_REMOTE_MODE': mode, 'TYCHE_QUIC_REMOTE_CAPACITY': str(capacity),
                       'TYCHE_QUIC_REMOTE_WAIT_NS': str(wait if mode == 'batch' else 0)})


def start(t, **kwargs):
    r = receiver(t, **kwargs)
    s = t.node('source')
    r.command('connect')
    r.until(lambda v: v['ready'] and v['flows'][0]['D'] == 1)
    return s, r


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


def consume_and_check(t, count, create=True):
    c = t.consumer(create=create)
    final = c.command('consume 0')
    history = byte_check(t)
    cp = checkpoint(t.path / 'PROTOTYPE-consumer-1.bin')
    t.check(final['cursor'] == count and cp[5] == cp[6] == count,
            'consumer saves processing result and exact cursor together')
    t.check(cp[8] == sum(e[8] for e in history) and cp[9] == sum(e[7] for e in history)
            and cp[10] == seal([e[-1] for e in history]), 'consumer accumulation has no omitted or duplicate event')
    return c


def check_consumed(t, c, count):
    final = c.command('consume 0')
    history = byte_check(t)
    cp = checkpoint(t.path / 'PROTOTYPE-consumer-1.bin')
    t.check(final['cursor'] == count and cp[5] == cp[6] == count,
            'recovered consumer saves processing result and exact cursor together')
    t.check(cp[8] == sum(e[8] for e in history) and cp[9] == sum(e[7] for e in history)
            and cp[10] == seal([e[-1] for e in history]), 'replay accumulation has no omitted or duplicate event')


def ordered(t, mode):
    s, r = start(t, mode=mode)
    r.command('remote_gate 1')
    s.command('publish 1 24')
    held = r.until(lambda v: v['savers'][0]['pending'] == 24 and v['savers'][0]['at_gate'])
    t.check(held['flows'][0]['R'] == 25 and held['flows'][0]['D'] == held['flows'][0]['V'] == 1,
            'admission advances only the receive watermark while the saver is gated')
    t.check((t.replica_root / 'PROTOTYPE-replica-101.bin').stat().st_size == 124,
            'gated admissions have not touched the replica journal')
    r.command('remote_release 1')
    state = r.until(lambda v: v['flows'][0]['D'] == 25)
    saver = state['savers'][0]
    t.check(saver['completed'] == 25 and saver['syncs'] == (25 if mode == 'worker' else 4)
            and saver['batches'] == (25 if mode == 'worker' else 4) and saver['max_pending'] == 24,
            'single saver and batching have distinct measured sync counts')
    s.command('inject 1 3 duplicate')
    state = r.until(lambda v: v['duplicates'] == 1)
    t.check(state['savers'][0]['duplicates'] == 1 and state['flows'][0]['D'] == 25,
            'identical duplicate is answered without a second save')
    c = consume_and_check(t, 25)
    c.exit()
    consume_and_check(t, 25, create=False)


def gate(t, mode):
    s, r = start(t, mode=mode)
    r.command('remote_gate 1')
    s.command('publish 1 4')
    held = r.until(lambda v: v['savers'][0]['pending'] == 4 and v['savers'][0]['at_gate'])
    t.check(held['flows'][0]['R'] == 5 and held['flows'][0]['D'] == held['flows'][0]['V'] == 1,
            'save gate holds D/V while R advances; admission is not durability')
    c = t.consumer()
    row = c.command('consume 0')
    t.check(row['cursor'] == row['head'] == 1, 'consumer cannot read gated admissions')
    r.command('remote_release 1')
    r.until(lambda v: v['flows'][0]['D'] == 5)
    c.exit()
    consume_and_check(t, 5, create=False)


def overflow(t):
    s, r = start(t, capacity=4)
    r.command('remote_gate 1')
    s.command('publish 1 6')
    held = r.until(lambda v: v['savers'][0]['restricted'] and not v['connected'])
    t.check(held['savers'][0]['pending'] == 4 and held['savers'][0]['max_pending'] == 4 and held['overflows'] == 1,
            'bounded queue includes inflight records and overflow closes the shared connection')
    t.check(held['flows'][0]['validity'] == 'gap' and not held['storage_failed'],
            'overflow restricts the affected object without latching a storage failure')
    r.until(lambda v: not v['ready'])
    r.command('remote_release 1')
    state = r.until(lambda v: v['closed'] and v['flows'][0]['D'] == 5)
    t.check((t.replica_root / 'PROTOTYPE-replica-101.bin').stat().st_size == 5 * 124,
            'admitted prefix keeps draining after overflow')
    r.command('connect')
    state = r.until(lambda v: v['ready'] and v['flows'][0]['D'] == 7)
    t.check(not state['storage_failed'] and state['savers'][0]['completed'] == 7,
            'reconnect replays the gap from the durable cursor and clears the restriction')
    consume_and_check(t, 7)


def save_error(t):
    s, r = start(t)
    c = t.consumer()
    t.check(c.command('consume 0')['cursor'] == 1, 'initial record consumed before the fault')
    r.command('remote_sync_error 1')
    r.command('remote_gate 1')
    s.command('publish 1 4')
    r.until(lambda v: v['savers'][0]['pending'] == 4 and v['savers'][0]['at_gate'])
    r.command('remote_release 1')
    state = r.until(lambda v: v['storage_failed'] and v['closed'])
    t.check(state['flows'][0]['R'] == 5 and state['flows'][0]['D'] == state['flows'][0]['V'] == 1,
            'failed remote save never advances durable or published watermark')
    path = t.replica_root / 'PROTOTYPE-replica-101.bin'
    before = path.read_bytes()
    t.check(len(before) == 5 * 124, 'unknown full batch tail retained for investigation')
    row = c.command('consume 0')
    t.check(not row['ok'] and not row['allowed'] and row['cursor'] == 1,
            'save failure closes consumption and retains the consumer checkpoint')
    r.exit()
    replacement = receiver(t, create=False, label='replacement', failure=True)
    replacement.p.wait(timeout=15)
    replacement.exit(expected=1)
    t.check(path.read_bytes() == before, 'detected remote save failure is not silently repaired')
    c.exit()
    s.exit()


def crash(t, point):
    s, r = start(t)
    c = t.consumer()
    c.command('consume 0')
    r.command(f'remote_arm 1 {point}')
    r.command('remote_gate 1')
    s.command('publish 1 4')
    r.until(lambda v: v['savers'][0]['pending'] == 4 and v['savers'][0]['at_gate'])
    r.command('remote_release 1')
    r.p.wait(timeout=15)
    r.exit(expected=77)  # Confirm exit before starting a new provider.
    path = t.replica_root / 'PROTOTYPE-replica-101.bin'
    before = path.read_bytes()
    (t.path / 'replica-at-crash.bin').write_bytes(before)
    sizes = {0: 124, 1: 248, 2: 248 + 62, 3: 620, 4: 620, 5: 620, 6: 620}
    t.check(len(before) == sizes[point], 'remote crash cut retains the exact journal prefix')
    row = c.command('consume 0')
    t.check(row['head'] == (5 if point == 6 else 1),
            'crash cut has the expected published prefix')
    if point == 2:
        replacement = receiver(t, create=False, label='replacement', failure=True)
        replacement.p.wait(timeout=15)
        replacement.exit(expected=1)
        t.check(path.read_bytes() == before, 'partial tail is neither truncated nor promoted')
        c.exit()
        s.exit()
        return
    recovered = {0: 1, 1: 2, 3: 5, 4: 5, 5: 5, 6: 5}[point]
    r = receiver(t, create=False, label='replacement')
    state = r.command('status')
    t.check(state['flows'][0]['D'] == recovered and not state['ready'],
            'confirmed exit recovers the exact durable prefix, still restricted')
    r.command('connect')
    r.until(lambda v: v['ready'] and v['flows'][0]['D'] == 5)
    t.check(path.read_bytes()[:len(before)] == before, 'recovery never rewrites the crash prefix')
    check_consumed(t, c, 5)
    t.check(not c.command('status 0')['allowed'], 'replay does not bypass reconciliation')
    c.exit()
    r.exit()
    s.exit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', required=True)
    parser.add_argument('--evidence-root', required=True)
    args = parser.parse_args()
    suite = Suite(args.worker, args.evidence_root)
    result = {'worker_sha256': sha(suite.worker), 'source_sha256': {
        p.name: sha(p) for p in Path(__file__).parent.iterdir() if p.suffix in ['.cpp', '.hpp', '.py']}}
    try:
        for mode in ['worker', 'batch']:
            suite.scenario(mode + '-ordered', lambda t, m=mode: ordered(t, m))
            suite.scenario(mode + '-gate', lambda t, m=mode: gate(t, m))
        suite.scenario('overflow', overflow)
        suite.scenario('remote-save-error', save_error)
        for point in range(7):
            suite.scenario(f'remote-crash-{point}', lambda t, p=point: crash(t, p))
        result['passed'] = True
    except Exception:
        result.update(passed=False, error=traceback.format_exc())
    finally:
        result['checks'] = suite.checks
        (suite.root / 'result.json').write_text(json.dumps(result, indent=2))
        private = suite.private.resolve()
        assert private.parent == Path(tempfile.gettempdir()).resolve() and private.name.startswith('tyche-quic-test-')
        shutil.rmtree(private)
    print(json.dumps({'evidence': str(suite.root), 'passed': result['passed'], 'checks': len(suite.checks),
                      'error': result.get('error')}), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
