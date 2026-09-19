#!/usr/bin/env python3
"""Bounded diagnostic repeat of the real checkpoint-4 crash/restart/replace path."""
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback
import uuid

from independent_scenarios import Run
from crash_scenarios import checkpoint


def main():
    binary, parent = [Path(x).resolve() for x in sys.argv[1:]]
    root = parent / ('checkpoint-repeat-' + uuid.uuid4().hex[:12]);root.mkdir(parents=True)
    started = time.monotonic()
    report = {'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(), 'limit':40, 'max_seconds':60, 'trials':[]}
    for i in range(40):
        if time.monotonic()-started >= 60:
            break
        run = Run(binary, root / f'trial-{i:02}')
        result = {'trial':i}
        try:
            checkpoint(run,4)
            result['passed'] = True
        except Exception as error:
            result.update(passed=False, error=str(error), traceback=traceback.format_exc())
        finally:
            run.cleanup()
        report['trials'].append(result)
        if not result['passed']:
            break
    report['elapsed_seconds'] = time.monotonic()-started
    report['failure_reproduced'] = any(not t['passed'] for t in report['trials'])
    report['storage_accepted'] = False
    (root / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'evidence':str(root),'trials':len(report['trials']),'failure_reproduced':report['failure_reproduced']}))


if __name__ == '__main__':
    main()
