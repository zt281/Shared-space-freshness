#!/usr/bin/env python3
"""Finite userspace UDP impairment experiment. Loopback only; no host network changes."""
import argparse
import heapq
import json
from pathlib import Path
import queue
import random
import selectors
import socket
import struct
import sys
import threading
import time
import traceback

CPP = Path(__file__).resolve().parents[1] / 'cpp'
sys.path.insert(0, str(CPP))
from quic_scenarios import Suite, Test, Process, sha
from audit_crash_evidence import events, checkpoint, seal


class Relay:
    """One client + server pair, separate directional budgets, bounded delayed packets."""
    def __init__(self, root, server_port, profile):
        self.profile, self.root = profile, root
        self.left = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.right = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for sock in [self.left,self.right]:
            sock.bind(('127.0.0.1',0));sock.setblocking(False)
        self.port = self.left.getsockname()[1]
        self.server, self.client = ('127.0.0.1',server_port), None
        self.select = selectors.DefaultSelector()
        self.select.register(self.left,selectors.EVENT_READ,0)
        self.select.register(self.right,selectors.EVENT_READ,1)
        self.random = random.Random(profile['seed'])
        self.pending, self.queued, self.next_send = [], [0,0], [0,0]
        self.serial, self.maximum = 0, [0,0]
        self.stop_event = threading.Event()
        self.blackout = (0,0)
        self.rows = open(root/'relay.jsonl','w')
        self.error = None
        self.thread = threading.Thread(target=self.run,daemon=True);self.thread.start()

    def record(self, **fields):
        self.rows.write(json.dumps({'mono_ns':time.monotonic_ns(),**fields})+'\n')
        self.rows.flush()

    def run(self):
        try:
            while not self.stop_event.is_set():
                now = time.monotonic_ns()
                while self.pending and self.pending[0][0] <= now:
                    due, serial, direction, data, target = heapq.heappop(self.pending)
                    self.queued[direction] -= len(data)
                    out = self.right if direction == 0 else self.left
                    try:
                        sent = out.sendto(data,target)
                        self.record(kind='sent',id=serial,direction=direction,payload_bytes=sent,due_ns=due,queue_bytes=self.queued[direction])
                    except OSError as exc:
                        self.record(kind='socket_error',id=serial,direction=direction,errno=exc.errno)
                delay = max(0,min(.005,(self.pending[0][0]-now)/1e9)) if self.pending else .005
                for key,_ in self.select.select(delay):
                    direction = key.data
                    while True:
                        try:
                            data, address = key.fileobj.recvfrom(65536)
                        except BlockingIOError:
                            break
                        now = time.monotonic_ns();self.serial += 1
                        if direction == 0:
                            self.client = address
                        elif address != self.server:
                            raise AssertionError('unexpected upstream address')
                        target = self.server if direction == 0 else self.client
                        assert target is not None
                        p = self.profile
                        reason = ('blackout' if self.blackout[0] <= now < self.blackout[1] else
                                  'random_loss' if self.random.random() < p['loss'] else
                                  'queue_limit' if self.queued[direction]+len(data) > 65536 else None)
                        if reason:
                            self.record(kind='dropped',id=self.serial,direction=direction,payload_bytes=len(data),reason=reason)
                            continue
                        charged = len(data)+28  # Explicit IPv4+UDP model, excludes Ethernet and real path overhead.
                        serialization = int(charged*8*1e9/p['bps']) if p['bps'] else 0
                        serialized = max(now,self.next_send[direction])+serialization
                        self.next_send[direction] = serialized
                        jitter = self.random.uniform(-p['jitter_ms'],p['jitter_ms'])
                        due = serialized+int(max(0,p['delay_ms']+jitter)*1e6)
                        self.queued[direction] += len(data)
                        self.maximum[direction] = max(self.maximum[direction],self.queued[direction])
                        heapq.heappush(self.pending,(due,self.serial,direction,data,target))
                        self.record(kind='queued',id=self.serial,direction=direction,payload_bytes=len(data),charged_bytes=charged,
                                    due_ns=due,queue_bytes=self.queued[direction])
        except Exception:
            self.error = traceback.format_exc()

    def close(self):
        self.stop_event.set();self.thread.join(timeout=3)
        self.record(kind='close',undelivered_packets=len(self.pending),undelivered_payload_bytes=sum(self.queued),maximum_queue_bytes=self.maximum)
        self.rows.close();self.left.close();self.right.close();self.select.close()
        assert not self.thread.is_alive()
        if self.error:
            raise AssertionError(self.error)


def start_consumer(test, flow):
    return Process(test,f'consumer-flow-{flow}',[test.suite.worker,'consumer',test.replica_root,test.token,'create',flow,
                   test.path/f'PROTOTYPE-network-consumer-{flow}.bin',900+flow,hex(0x530000000000+flow*0x100000)],startup='consumer')


def scenario(suite, name, profile, rate=40, duration=2.0, drain=12.0):
    test = Test(suite,name)
    relay = None
    consumers, threads = [], []
    stop = threading.Event()
    errors, plan, samples = [], [], []
    result = {'name':name,'profile':profile,'planned_rate':rate,'input_seconds':duration,'drain_seconds':drain}
    try:
        source = test.node('source')
        relay = Relay(test.path,test.port,profile)
        server_port = test.port;test.port = relay.port
        remote = test.node('receiver');test.port = server_port
        remote.command('connect');remote.until(lambda r:r['ready'],timeout=15)
        remote.command('subscribe 3');initial = remote.until(lambda r:r['ready'] and r['flows'][1]['D']==1,timeout=15)
        for flow in [1,2]:
            consumers.append(start_consumer(test,flow))
        initial_heads = [f['head'] for f in initial['flows']]
        for c in consumers:
            c.command(f'consume {time.monotonic_ns()//1000000}')
        start = time.monotonic_ns()+100_000_000
        planned_count = round(rate*duration)
        seq = initial_heads.copy()
        if profile.get('blackout_seconds'):
            relay.blackout = (start+350_000_000,start+350_000_000+int(profile['blackout_seconds']*1e9))

        def consume(c,flow):
            try:
                while not stop.is_set():
                    row = c.command(f'consume {time.monotonic_ns()//1000000}')
                    samples.append({'flow':flow,'observed_ns':time.monotonic_ns(),**row})
                    if not row['ok']:
                        errors.append(f'consumer {flow}: {row}');break
                    stop.wait(.02)
            except Exception:
                errors.append(traceback.format_exc())

        for flow,c in enumerate(consumers,1):
            thread = threading.Thread(target=consume,args=(c,flow),daemon=True);thread.start();threads.append(thread)
        for n in range(planned_count):
            target = start+int(n*1e9/rate)
            wait = (target-time.monotonic_ns())/1e9
            if wait>0:
                time.sleep(wait)
            flow = n%2+1;seq[flow-1]+=1
            source.request += 1
            item = {'index':n,'flow':flow,'sequence':seq[flow-1],'request':source.request,'planned_ns':target,
                    'enqueued_ns':time.monotonic_ns()}
            plan.append(item)
            source.write(f'{source.request} publish {flow} 1')  # Fixed schedule; never wait for previous commit.
        input_end = start+int(duration*1e9)
        deadline = input_end+int(drain*1e9)
        final = None
        while time.monotonic_ns()<deadline and not errors:
            final = remote.command('status')
            a = [max((r['cursor'] for r in samples if r['flow']==f),default=initial_heads[f-1]) for f in [1,2]]
            if all(final['flows'][i]['D']==seq[i] and a[i]==seq[i] for i in range(2)):
                break
            time.sleep(.04)
        stop.set()
        for thread in threads:
            thread.join(timeout=16)
        assert all(not t.is_alive() for t in threads)
        # Preserve every planned item, including uncommitted or undelivered ones.
        acknowledgements = {r.get('request'):r for r in source.rows if r.get('event')=='ack'}
        completions = {}
        for row in remote.rows:
            if row.get('event')=='replica_progress':
                completions.setdefault((row['flow'],row['V']),row['mono_ms']*1000000)
        for item in plan:
            key = item['flow'],item['sequence']
            item['source_ack_ms'] = acknowledgements.get(item['request'],{}).get('mono_ms')
            item['published_by_ms'] = completions.get(key,0)//1000000 if key in completions else None
            observations = [r['observed_ns'] for r in samples if r['flow']==item['flow'] and r['cursor']>=item['sequence']]
            item['consumer_observed_by_ns'] = min(observations) if observations else None
            item['consumer_observed_delay_ms'] = (item['consumer_observed_by_ns']-item['planned_ns'])/1e6 if observations else None
        # Close consumers before providers; proxy remains alive through QUIC close/drain.
        for c in consumers:c.exit()
        remote.exit();source.exit()
        # Independent bytes: source ABI -> encoded replica -> per-flow result checkpoint.
        per_flow = []
        for flow in [1,2]:
            history = events(test.source_root/f'PROTOTYPE-source-{flow}.bin')
            raw = (test.replica_root/f'PROTOTYPE-replica-{100+flow}.bin').read_bytes()
            assert len(raw)%124==0
            replica=[]
            for offset in range(0,len(raw),124):
                size,*words=struct.unpack_from('>I15Q',raw,offset)
                assert size==120 and words[:2]==[0x5459515500000001,100+flow]
                record=tuple(words[2:]);assert seal(record[:-1])==record[-1];replica.append(record)
            assert replica==history[:len(replica)]
            state=checkpoint(test.path/f'PROTOTYPE-network-consumer-{flow}.bin')
            prefix=history[:state[5]]
            assert state[8]==sum(e[8] for e in prefix) and state[9]==sum(e[7] for e in prefix)
            assert state[10]==seal([e[-1] for e in prefix]) and state[14]==0
            per_flow.append({'flow':flow,'C':len(history),'D':len(replica),'A':state[5]})
        completed=[i for i in plan if i['consumer_observed_by_ns'] is not None]
        in_window=[i for i in completed if i['consumer_observed_by_ns']<=input_end]
        assert all(not r['allowed'] for r in samples if r['validity'] in ['gap','expired','unknown','damaged'])
        expired=sum(r['validity']=='expired' for r in samples)
        if profile.get('blackout_seconds'):
            assert expired>0,'outage must exercise business expiry independently of connection state'
        result.update(passed=not errors and all(f['C']==f['D']==f['A']==seq[f['flow']-1] for f in per_flow),
                      input_start_ns=start,input_end_ns=input_end,planned=planned_count,completed=len(completed),
                      completed_in_input_window=len(in_window),missing=planned_count-len(completed),
                      per_flow=per_flow,expired_consumer_observations=expired,errors=errors,
                      final_receiver_status=final)
        if completed:
            ordered=sorted(i['consumer_observed_delay_ms'] for i in completed)
            result['conditional_observed_delay_ms']={'p50':ordered[(len(ordered)-1)//2],'p99':ordered[max(0,__import__('math').ceil(.99*len(ordered))-1)],'max':ordered[-1]}
            result['observed_after_input_end_ms']=max(0,(max(i['consumer_observed_by_ns'] for i in completed)-input_end)/1e6)
    except Exception as exc:
        result.update(passed=False,error=str(exc),traceback=traceback.format_exc())
    finally:
        stop.set()
        for thread in threads:thread.join(timeout=16)
        test.cleanup()
        if relay:
            relay.close()
        (test.path/'planned.json').write_text(json.dumps(plan,indent=2))
        (test.path/'consumer-observations.json').write_text(json.dumps(samples,indent=2))
        (test.path/'summary.json').write_text(json.dumps(result,indent=2))
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--worker',required=True)
    parser.add_argument('--evidence-root',required=True)
    args=parser.parse_args()
    suite=Suite(args.worker,args.evidence_root)
    profiles=[
        ('relay-baseline',dict(delay_ms=0,jitter_ms=0,loss=0,bps=0,seed=11)),
        ('delay-and-jitter',dict(delay_ms=40,jitter_ms=5,loss=0,bps=2000000,seed=12)),
        ('loss-and-reordering',dict(delay_ms=10,jitter_ms=8,loss=.03,bps=1000000,seed=13)),
        ('bandwidth-limited',dict(delay_ms=10,jitter_ms=2,loss=0,bps=32000,seed=14)),
        ('temporary-blackout',dict(delay_ms=5,jitter_ms=0,loss=0,bps=2000000,blackout_seconds=1.5,seed=15)),
    ]
    reports=[]
    try:
        for name,profile in profiles:
            report=scenario(suite,name,profile)
            reports.append(report)
            print(json.dumps({'case':name,'passed':report['passed'],'completed':report.get('completed'),'missing':report.get('missing'),'error':report.get('error')}),flush=True)
            if not report['passed']:
                break
    finally:
        import shutil
        shutil.rmtree(suite.private)
        manifest={'passed':len(reports)==len(profiles) and all(r['passed'] for r in reports),'profiles':reports,
                  'worker':str(suite.worker),'worker_sha256':sha(suite.worker), 'script_sha256':sha(Path(__file__)),
                  'helper_sha256':sha(CPP/'quic_scenarios.py'),
                  'scope':'2-second planned input, userspace loopback impairments, per-event checkpoint I/O; observation upper bounds, not production performance'}
        (suite.root/'network-result.json').write_text(json.dumps(manifest,indent=2))
        print(json.dumps({'evidence':str(suite.root),'passed':manifest['passed']}))
    return 0 if manifest['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
