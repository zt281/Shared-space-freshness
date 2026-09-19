#!/usr/bin/env python3
"""Recompute finite network observations and payload/checkpoint consistency off line."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cpp'))
from audit_crash_evidence import events,checkpoint,seal


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def audit(root):
    manifest=json.loads((root/'network-result.json').read_text())
    assert manifest['passed'] and len(manifest['profiles'])==5
    reports=[]
    for p in manifest['profiles']:
        folder=root/p['name']
        plan=json.loads((folder/'planned.json').read_text())
        obs=json.loads((folder/'consumer-observations.json').read_text())
        assert len(plan)==p['planned']==80 and [i['index'] for i in plan]==list(range(80))
        assert len({(i['flow'],i['sequence']) for i in plan})==80
        for i in plan:
            assert i['planned_ns']==p['input_start_ns']+int(i['index']*1e9/p['planned_rate'])
            seen=min((r['observed_ns'] for r in obs if r['flow']==i['flow'] and r['cursor']>=i['sequence']),default=None)
            assert seen==i['consumer_observed_by_ns']
            assert seen is not None and seen>=i['planned_ns']
            assert abs((seen-i['planned_ns'])/1e6-i['consumer_observed_delay_ms'])<1e-8
        complete=sum(i['consumer_observed_by_ns'] is not None for i in plan)
        in_window=sum(i['consumer_observed_by_ns']<=p['input_end_ns'] for i in plan)
        assert complete==p['completed'] and in_window==p['completed_in_input_window'] and p['missing']==80-complete
        delays=sorted(i['consumer_observed_delay_ms'] for i in plan)
        assert delays[math.ceil(.99*len(delays))-1]==p['conditional_observed_delay_ms']['p99']
        for f in [1,2]:
            history=events(folder/'source'/f'PROTOTYPE-source-{f}.bin')
            raw=(folder/'replica'/f'PROTOTYPE-replica-{100+f}.bin').read_bytes()
            assert len(raw)==len(history)*124 and len(history)==41
            remote=[]
            for at in range(0,len(raw),124):
                length,*words=struct.unpack_from('>I15Q',raw,at)
                assert length==120 and words[:2]==[0x5459515500000001,100+f]
                remote.append(tuple(words[2:]))
            assert remote==history
            state=checkpoint(folder/f'PROTOTYPE-network-consumer-{f}.bin')
            assert state[2:4]==(100+f,900+f) and state[5]==41 and state[14]==0
            assert state[7]==history[-1][-1] and state[8]==sum(e[8] for e in history)
            assert state[9]==sum(e[7] for e in history) and state[10]==seal([e[-1] for e in history])
        relay=[json.loads(line) for line in (folder/'relay.jsonl').read_text().splitlines()]
        queued={r['id']:r for r in relay if r['kind']=='queued'}
        sent=[r for r in relay if r['kind']=='sent']
        dropped=[r for r in relay if r['kind']=='dropped']
        assert not [r for r in relay if r['kind']=='socket_error']
        assert all(r['mono_ns']>=queued[r['id']]['due_ns'] and r['payload_bytes']==queued[r['id']]['payload_bytes'] for r in sent)
        assert all(r['queue_bytes']<=65536 for r in relay if 'queue_bytes' in r)
        assert all(not r['allowed'] for r in obs if r['validity'] in ['expired','gap','unknown','damaged'])
        reorders=0;maximum=[-1,-1]
        for r in sent:
            d=r['direction'];reorders+=r['id']<maximum[d];maximum[d]=max(maximum[d],r['id'])
        packet_delay=[(r['mono_ns']-queued[r['id']]['mono_ns'])/1e6 for r in sent]
        lateness=[(r['mono_ns']-queued[r['id']]['due_ns'])/1e6 for r in sent]
        for ep in folder.glob('*.exit.json'):
            exit_code=json.loads(ep.read_text());assert exit_code['code']==exit_code['expected']==0
        reports.append({'name':p['name'],'planned':80,'completed':complete,'in_window':in_window,'missing':80-complete,
                        'post_window_drain_ms':p['observed_after_input_end_ms'],'observed_delay_ms':p['conditional_observed_delay_ms'],
                        'maximum_input_schedule_lateness_ms':max((i['enqueued_ns']-i['planned_ns'])/1e6 for i in plan),
                        'datagrams_received':len(queued)+len(dropped),'datagrams_sent':len(sent),
                        'drop_reasons':dict(Counter(r['reason'] for r in dropped)), 'reordered_datagrams':reorders,
                        'max_relay_queue_payload_bytes':max((r.get('queue_bytes',0) for r in relay),default=0),
                        'max_actual_relay_residence_ms':max(packet_delay,default=0),'max_relay_send_lateness_ms':max(lateness,default=0),
                        'expired_consumer_observations':sum(r['validity']=='expired' for r in obs)})
    assert not list(root.rglob('*.key'))
    files={p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file() and p.name!='network-audit.json'}
    report={'passed':True,'worker_sha256':manifest['worker_sha256'],'profiles':reports,'sha256':files,
            'total_planned':sum(r['planned'] for r in reports),'total_completed':sum(r['completed'] for r in reports),
            'scope':'independent bytes and recomputed observation upper bounds; not trading/exchange latency'}
    (root/'network-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='sha256'},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root');args=parser.parse_args()
    audit(Path(args.root).resolve())
