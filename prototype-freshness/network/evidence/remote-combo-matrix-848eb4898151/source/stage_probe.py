#!/usr/bin/env python3
"""Fixed-schedule paired stage diagnostic; no changes to durability or recovery policy."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback

HERE = Path(__file__).resolve().parent
CPP = HERE.parent / 'cpp'
sys.path.insert(0, str(CPP))
from quic_scenarios import Suite, Test, Process, sha
from quic_network_probe import Relay


class StageProcess(Process):
    def __init__(self, test, label, args, trace, capacity=65536, environment_overrides=None, **kwargs):
        self.envelopes = []
        overrides = {'TYCHE_PROTOTYPE_TRACE': str(test.path / ('PROTOTYPE-' + label + '-trace.jsonl')) if trace else '',
                     'TYCHE_PROTOTYPE_TRACE_CAPACITY': str(capacity)}
        overrides.update(environment_overrides or {})
        before = time.monotonic_ns()
        super().__init__(test, label, args, environment_overrides=overrides, **kwargs)
        self.started_bounds = {'before_ns': before, 'after_ns': time.monotonic_ns(), 'pid': self.p.pid}

    def command(self, text, timeout=15):
        before = time.monotonic_ns()
        row = super().command(text, timeout)
        self.envelopes.append({'command': text, 'request': row.get('request'), 'before_ns': before,
                               'after_ns': time.monotonic_ns()})
        return row


class BufferedRelay(Relay):
    """Same packet scheduling as the earlier relay; bounded trace written after stop."""
    def __init__(self, *args, **kwargs):
        self.records = []
        super().__init__(*args, **kwargs)

    def record(self, **fields):
        if len(self.records) >= 100000:
            raise RuntimeError('bounded relay observation buffer exhausted')
        self.records.append({'mono_ns': time.monotonic_ns(), **fields})

    def close(self):
        try:
            super().close()
        finally:
            (self.root / 'relay.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in self.records))


def proc_snapshot(pid):
    result = {'pid': pid, 'threads': []}
    root = Path('/proc') / str(pid)
    try:
        result['status'] = {k: v.strip() for k, v in (line.split(':', 1) for line in (root / 'status').read_text().splitlines())
                            if k in ['VmRSS', 'VmHWM', 'Threads', 'voluntary_ctxt_switches', 'nonvoluntary_ctxt_switches']}
        result['io'] = (root / 'io').read_text()
        for task in sorted((root / 'task').iterdir()):
            try:
                raw = (task / 'stat').read_text()
                fields = raw[raw.rfind(')') + 2:].split()
                status = {k: v.strip() for k, v in (line.split(':', 1) for line in (task / 'status').read_text().splitlines())
                          if k in ['voluntary_ctxt_switches', 'nonvoluntary_ctxt_switches']}
                result['threads'].append({'tid': int(task.name), 'state': fields[0], 'utime_ticks': int(fields[11]),
                                          'stime_ticks': int(fields[12]), 'processor': int(fields[36]),
                                          'schedstat': (task / 'schedstat').read_text().strip(), **status})
            except (FileNotFoundError, ProcessLookupError):
                result['threads'].append({'tid': int(task.name), 'exited_during_sample': True})
    except (FileNotFoundError, ProcessLookupError):
        result['exited_during_sample'] = True
    return result


def scenario(suite, name, profile, trace, rate=40, duration=2.0, drain=12.0, capacity=65536, source_settings=None, burst=1, remote_settings=None, reconnect_on_close=False):
    test = Test(suite, name)
    result = {'name': name, 'profile': profile, 'trace_enabled': trace, 'trace_capacity': capacity,
              'planned_rate': rate, 'input_seconds': duration, 'drain_seconds': drain,
              'consumer_poll_seconds': .02, 'resource_sample_seconds': .1}
    result['source_settings'] = source_settings or {}
    result['remote_settings'] = remote_settings or {}
    result['burst_size'] = burst
    result['reconnect_on_close'] = reconnect_on_close
    relay = None
    plan, samples, resources, stats, errors, consumers, threads = [], [], [], [], [], [], []
    stop = threading.Event()

    def node(role, port):
        overrides = source_settings if role == 'source' else remote_settings
        return StageProcess(test, role, [suite.worker, role, test.source_root if role == 'source' else test.replica_root,
                            test.token, 'create', port, suite.certs,
                            suite.certs / ('client.der' if role == 'source' else 'server.der')], trace, capacity,
                            environment_overrides=overrides)

    try:
        source = node('source', test.port)
        if profile['relay']:
            relay = BufferedRelay(test.path, test.port, profile)
        remote = node('receiver', relay.port if relay else test.port)
        remote.command('connect')
        remote.until(lambda r: r['ready'], timeout=15)
        remote.command('subscribe 3')
        initial = remote.until(lambda r: r['ready'] and r['flows'][1]['D'] == 1, timeout=15)
        for flow in [1, 2]:
            c = StageProcess(test, f'consumer-{flow}', [suite.worker, 'consumer', test.replica_root, test.token, 'create', flow,
                             test.path / f'PROTOTYPE-consumer-{flow}.bin', 900 + flow,
                             hex(0x530000000000 + flow * 0x100000)], trace, capacity, startup='consumer')
            c.command(f'consume {time.monotonic_ns() // 1000000}')
            consumers.append(c)

        def take_stats(phase):
            for p in [source, remote]:
                before = time.monotonic_ns()
                value = p.command('stats')
                stats.append({'phase': phase, 'process': p.label, 'before_ns': before,
                              'after_ns': time.monotonic_ns(), 'value': value})

        def consume(c, flow):
            try:
                while not stop.is_set():
                    before = time.monotonic_ns()
                    row = c.command(f'consume {time.monotonic_ns() // 1000000}')
                    if len(samples) >= 10000:
                        raise RuntimeError('bounded consumer observation buffer exhausted')
                    samples.append({'flow': flow, 'requested_ns': before, 'observed_ns': time.monotonic_ns(), **row})
                    if not row['ok'] and not reconnect_on_close:
                        raise RuntimeError(f'consumer failed: {row}')
                    # With reconnect_on_close, transient provider restriction during overflow
                    # recovery is retained as an observation row instead of failing the tier.
                    stop.wait(.02)
            except Exception:
                errors.append(traceback.format_exc())

        def sample_resources():
            try:
                while not stop.is_set():
                    before = time.monotonic_ns()
                    if len(resources) >= 4096:
                        raise RuntimeError('bounded resource observation buffer exhausted')
                    resources.append({'before_ns': before, 'processes': [proc_snapshot(p.p.pid) for p in test.processes]
                                      + [proc_snapshot(os.getpid())], 'after_ns': time.monotonic_ns()})
                    stop.wait(.1)
            except Exception:
                errors.append(traceback.format_exc())

        take_stats('before_input')
        for flow, c in enumerate(consumers, 1):
            threads.append(threading.Thread(target=consume, args=(c, flow), daemon=True))
        threads.append(threading.Thread(target=sample_resources, daemon=True))
        for thread in threads:
            thread.start()
        start = time.monotonic_ns() + 100_000_000
        count = round(rate * duration)
        seq = [f['head'] for f in initial['flows']]
        for index in range(count):
            target = start + int((index // burst) * burst * 1e9 / rate)
            wait = (target - time.monotonic_ns()) / 1e9
            if wait > 0:
                time.sleep(wait)
            flow = index % 2 + 1
            seq[flow - 1] += 1
            source.request += 1
            item = {'index': index, 'flow': flow, 'identity': 100 + flow, 'epoch': 1, 'sequence': seq[flow - 1],
                    'request': source.request, 'planned_ns': target, 'write_begin_ns': time.monotonic_ns()}
            plan.append(item)
            source.write(f'{source.request} publish {flow} 1')
            item['write_end_ns'] = time.monotonic_ns()
        end = start + int(duration * 1e9)
        take_stats('after_inputs_enqueued') # Record actual bracket; this need not equal the nominal window end.
        deadline = end + int(drain * 1e9)
        final = None
        reconnects = 0
        while time.monotonic_ns() < deadline and not errors:
            final = remote.command('status')
            if reconnect_on_close and final['closed'] and not final['storage_failed'] and reconnects < 2:
                # Bounded-queue overflow closes the shared connection by design; reconnect replays
                # from the durable cursor (subscription mask is retained by the receiver).
                remote.command('connect')
                reconnects += 1
                continue
            cursors = [max((row['cursor'] for row in samples if row['flow'] == flow), default=1) for flow in [1, 2]]
            if all(final['flows'][i]['D'] == seq[i] and cursors[i] == seq[i] for i in range(2)):
                break
            time.sleep(.04)
        result['reconnects'] = reconnects
        stop.set()
        for thread in threads:
            thread.join(timeout=16)
        if any(t.is_alive() for t in threads):
            raise RuntimeError('diagnostic worker did not stop')
        take_stats('after_drain')
        result['final_source'] = source.command('status')
        for item in plan:
            observed = [row['observed_ns'] for row in samples if row['flow'] == item['flow'] and row['cursor'] >= item['sequence']]
            item['observed_complete_ns'] = min(observed) if observed else None
        result.update(input_start_ns=start, input_end_ns=end, planned=count, final_receiver=final,
                      observed_complete=sum(p['observed_complete_ns'] is not None for p in plan), errors=errors)
        for p in consumers:
            p.exit()
        remote.exit()
        source.exit()
        result['passed'] = not errors and result['observed_complete'] == count
    except Exception:
        result.update(passed=False, error=traceback.format_exc())
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=16)
        try:
            test.cleanup()
        except Exception:
            result.update(passed=False, cleanup_error=traceback.format_exc())
        if relay:
            try:
                relay.close()
            except Exception:
                result.update(passed=False, relay_error=traceback.format_exc())
        for p in test.processes:
            (test.path / (p.label + '.clock-envelopes.json')).write_text(json.dumps({'startup': p.started_bounds, 'commands': p.envelopes}, indent=2))
        for filename, value in [('planned.json', plan), ('consumer-observations.json', samples), ('resources.json', resources),
                                ('quic-statistics.json', stats), ('summary.json', result)]:
            (test.path / filename).write_text(json.dumps(value, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', required=True)
    parser.add_argument('--evidence-root', required=True)
    parser.add_argument('--mode', choices=['smoke', 'matrix', 'overflow'], default='smoke')
    args = parser.parse_args()
    suite = Suite(args.worker, args.evidence_root)
    manifest = {'started_utc': datetime.now(timezone.utc).isoformat(), 'worker': str(suite.worker), 'worker_sha256': sha(suite.worker),
                'mode': args.mode, 'clock': vars(time.get_clock_info('monotonic')), 'clock_ticks_per_second': os.sysconf('SC_CLK_TCK'),
                'platform': os.uname()._asdict() if hasattr(os.uname(), '_asdict') else list(os.uname()),
                'initial_disk_usage': dict(zip(['total', 'used', 'free'], shutil.disk_usage(suite.root))), 'results': []}
    schedstats = Path('/proc/sys/kernel/sched_schedstats')
    manifest['kernel_schedstats_enabled'] = schedstats.read_text().strip() if schedstats.exists() else None
    source = suite.root / 'source'
    source.mkdir()
    for p in [Path(__file__), HERE / 'quic_network_probe.py', HERE / 'stage_audit.py', CPP / 'quic_scenarios.py', CPP / 'audit_crash_evidence.py']:
        shutil.copyfile(p, source / p.name)
    manifest['source_sha256'] = {p.name: sha(p) for p in source.iterdir()}
    try:
        assert manifest['initial_disk_usage']['free'] > 1024 ** 3, 'retain at least 1 GiB guest space before finite run'
        profiles = [
            {'name': 'direct', 'relay': False, 'seed': 8131, 'delay_ms': 0, 'jitter_ms': 0, 'loss': 0, 'bps': 0},
            {'name': 'relay', 'relay': True, 'seed': 8131, 'delay_ms': 0, 'jitter_ms': 0, 'loss': 0, 'bps': 0},
            {'name': 'delay', 'relay': True, 'seed': 8131, 'delay_ms': 40, 'jitter_ms': 5, 'loss': 0, 'bps': 2000000},
        ]
        rounds = range(3) if args.mode == 'matrix' else range(1)
        for repeat in rounds:
            for profile in (profiles if args.mode == 'matrix' else profiles[:1]):
                modes = ([False, True] if repeat % 2 == 0 else [True, False]) if args.mode == 'matrix' else [True]
                for trace in modes:
                    name = f'{repeat + 1}-{profile["name"]}-trace-{int(trace)}'
                    result = scenario(suite, name, profile, trace, capacity=8 if args.mode == 'overflow' else 65536)
                    manifest['results'].append(result)
                    (suite.root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
                    print(json.dumps({'case': name, 'passed': result['passed'], 'observed_complete': result.get('observed_complete')}), flush=True)
                    if not result['passed']:
                        raise RuntimeError(f'case failed: {name}; evidence retained')
        manifest['passed'] = True
    except Exception:
        manifest.update(passed=False, error=traceback.format_exc())
    finally:
        private = suite.private.resolve()
        assert private.parent == Path(tempfile.gettempdir()).resolve() and private.name.startswith('tyche-quic-test-')
        shutil.rmtree(private)  # Only this run's generated private certificates.
        manifest['finished_utc'] = datetime.now(timezone.utc).isoformat()
        manifest['final_disk_usage'] = dict(zip(['total', 'used', 'free'], shutil.disk_usage(suite.root)))
        (suite.root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'evidence': str(suite.root), 'passed': manifest['passed']}), flush=True)
    return 0 if manifest['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
