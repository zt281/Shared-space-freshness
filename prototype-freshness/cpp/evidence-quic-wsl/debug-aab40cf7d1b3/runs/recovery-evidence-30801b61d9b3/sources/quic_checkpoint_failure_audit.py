#!/usr/bin/env python3
"""Preserve the second observed checkpoint replacement failure without promoting its tail."""
import hashlib
import json
from pathlib import Path
import sys
from audit_crash_evidence import events, checkpoint, seal

case, output = [Path(x).resolve() for x in sys.argv[1:]]
history = events(case / 'PROTOTYPE-events.bin')
committed = case / 'PROTOTYPE-consumer.checkpoint'
pending = list(case.glob('PROTOTYPE-consumer.checkpoint.pending-*'))
assert len(pending) == 1
old, next_state = checkpoint(committed), checkpoint(pending[0])
assert next_state[4] == old[4]+1 and next_state[5] == old[5]+1
for state in [old,next_state]:
    prefix = history[:state[5]]
    assert state[7] == prefix[-1][-1] and state[8] == sum(e[8] for e in prefix)
    assert state[9] == sum(e[7] for e in prefix) and state[10] == seal([e[-1] for e in prefix])
rows = [json.loads(line) for line in (case/'after_crash.jsonl').read_text().splitlines()]
failures = [r for r in rows if r.get('checkpoint',{}).get('error')]
assert len(failures) == 1 and failures[0]['checkpoint']['cursor'] == old[5]
report = {'source_records':len(history), 'checkpoint_revision':old[4], 'checkpoint_cursor':old[5],
          'pending_revision':next_state[4], 'uncommitted_pending_cursor':next_state[5],
          'consumer_allowed':failures[0]['allowed'], 'checkpoint_error':failures[0]['checkpoint']['error'],
          'errno_recorded':False, 'cause_established':False, 'pending_promoted_by_audit':False,
          'saved_prefix_consistent':True, 'storage_accepted':False,
          'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [committed,pending[0],case/'PROTOTYPE-events.bin']}}
assert not report['consumer_allowed']
output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
