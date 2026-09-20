#!/usr/bin/env python3
"""Fixed-input comparison of synchronous, one-record saver and batch saver remote modes."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import traceback

from stage_probe import scenario, Suite, sha, CPP, HERE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', required=True)
    parser.add_argument('--evidence-root', required=True)
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    suite = Suite(args.worker, args.evidence_root)
    manifest = {'started_utc': datetime.now(timezone.utc).isoformat(), 'worker': str(suite.worker),
                'worker_sha256': sha(suite.worker), 'clock': vars(time.get_clock_info('monotonic')),
                'clock_ticks_per_second': os.sysconf('SC_CLK_TCK'), 'mode': 'remote-commit-smoke' if args.smoke else 'remote-commit-matrix',
                'kernel_schedstats_enabled': Path('/proc/sys/kernel/sched_schedstats').read_text().strip(),
                'uname': list(os.uname()), 'results': [], 'initial_disk_usage': dict(zip(['total', 'used', 'free'], shutil.disk_usage(suite.root)))}
    snapshot = suite.root / 'source'
    snapshot.mkdir()
    for p in [Path(__file__), HERE / 'stage_probe.py', HERE / 'stage_audit.py', HERE / 'quic_network_probe.py',
              CPP / 'quic_scenarios.py', CPP / 'audit_crash_evidence.py']:
        shutil.copyfile(p, snapshot / p.name)
    manifest['source_sha256'] = {p.name: sha(p) for p in snapshot.iterdir()}
    profile = {'name': 'direct', 'relay': False, 'seed': 8131, 'delay_ms': 0, 'jitter_ms': 0, 'loss': 0, 'bps': 0}
    try:
        assert manifest['initial_disk_usage']['free'] > 1024 ** 3
        modes = ['sync', 'worker', 'batch']
        for repeat in range(1 if args.smoke else 3):
            order = modes[repeat:] + modes[:repeat]
            for rate, duration, burst in ([(40, 2.0, 1)] if args.smoke else [(40, 2.0, 1), (80, 1.0, 8)]):
                for mode in order:
                    name = f'{repeat + 1}-{rate}ps-burst-{burst}-{mode}-trace-1'
                    settings = {'TYCHE_QUIC_REMOTE_MODE': mode, 'TYCHE_QUIC_REMOTE_CAPACITY': '64',
                                'TYCHE_QUIC_REMOTE_WAIT_NS': '2000000' if mode == 'batch' else '0'}
                    result = scenario(suite, name, profile, True, rate=rate, duration=duration, remote_settings=settings, burst=burst)
                    manifest['results'].append(result)
                    (suite.root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
                    print(json.dumps({'case': name, 'passed': result['passed'], 'completed': result.get('observed_complete')}), flush=True)
        manifest['passed'] = all(r['passed'] for r in manifest['results'])
    except Exception:
        manifest.update(passed=False, error=traceback.format_exc())
    finally:
        private = suite.private.resolve()
        assert private.parent == Path(tempfile.gettempdir()).resolve() and private.name.startswith('tyche-quic-test-')
        shutil.rmtree(private)
        manifest['finished_utc'] = datetime.now(timezone.utc).isoformat()
        manifest['final_disk_usage'] = dict(zip(['total', 'used', 'free'], shutil.disk_usage(suite.root)))
        (suite.root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'evidence': str(suite.root), 'passed': manifest['passed']}), flush=True)
    return 0 if manifest['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
