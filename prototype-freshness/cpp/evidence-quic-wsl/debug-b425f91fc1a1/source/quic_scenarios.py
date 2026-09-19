#!/usr/bin/env python3
"""Finite independent-process loopback experiment. No network shaping or trading."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import traceback
import uuid


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Process:
    def __init__(self, test, label, args, startup="started", expect_failure=False):
        self.test, self.label = test, label
        self.q, self.rows, self.request = queue.Queue(), [], 0
        self.args = list(map(str, args))
        (test.path / (label + ".command.json")).write_text(json.dumps(self.args, indent=2))
        self.raw = open(test.path / (label + ".stdout.jsonl"), "wb")
        self.err = open(test.path / (label + ".stderr.txt"), "wb")
        self.commands = open(test.path / (label + ".stdin.txt"), "w")
        self.p = subprocess.Popen(self.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.err)
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()
        test.processes.append(self)
        if not expect_failure:
            self.wait(lambda r: r.get("event") == startup)

    def read(self):
        for line in self.p.stdout:
            self.raw.write(line)
            self.raw.flush()
            try:
                row = json.loads(line)
                self.rows.append(row)
                self.q.put(row)
            except Exception:
                self.q.put({"bad_output": line.decode(errors="replace")})

    def wait(self, predicate, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                row = self.q.get(timeout=0.1)
            except queue.Empty:
                if self.p.poll() is not None:
                    raise AssertionError(f"{self.label} exited {self.p.returncode}; waiting for event")
                continue
            if predicate(row):
                return row
        raise AssertionError(f"{self.label} event timeout")

    def write(self, line):
        self.commands.write(line + "\n")
        self.commands.flush()
        self.p.stdin.write((line + "\n").encode())
        self.p.stdin.flush()

    def command(self, text, timeout=15):
        self.request += 1
        req = self.request
        self.write(f"{req} {text}")
        row = self.wait(lambda r: r.get("request") == req, timeout)
        assert row.get("event") != "command_error", row
        return row

    def until(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            row = self.command("status", timeout=timeout)
            if predicate(row):
                return row
            time.sleep(0.03)
        raise AssertionError(f"{self.label} status timeout: {row}")

    def exit(self, kill=False, expected=0):
        if self.p.poll() is None:
            if kill:
                self.p.kill()
            else:
                self.write("quit" if self.args[1] != "consumer" else "99999 quit 0")
        code = self.p.wait(timeout=15)
        self.reader.join(timeout=2)
        (self.test.path / (self.label + ".exit.json")).write_text(json.dumps({"code": code, "expected": expected}))
        self.test.check(code == expected, f"{self.label} exit {expected}")
        if not kill and expected == 0 and self.args[1] != "consumer":
            self.test.check(any(r.get("event") == "shutdown_drained" for r in self.rows), f"{self.label} drains borrowed receive/send buffers")
        self.raw.close(); self.err.close(); self.commands.close()


class Test:
    def __init__(self, suite, name):
        self.suite, self.path, self.processes = suite, suite.root / name, []
        self.path.mkdir()
        self.source_root = self.path / "source"
        self.replica_root = self.path / "replica"
        self.source_root.mkdir(); self.replica_root.mkdir()
        self.token = "q" + uuid.uuid4().hex[:18]
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.labels = {}

    def check(self, ok, what):
        self.suite.checks.append({"scenario": self.path.name, "check": what, "passed": bool(ok)})
        assert ok, what

    def node(self, role, create=True, certs=None, pin=None, expect_failure=False):
        n = self.labels.get(role, 0) + 1
        self.labels[role] = n
        certs = Path(certs or self.suite.certs)
        pin = pin or self.suite.certs / ("client.der" if role == "source" else "server.der")
        return Process(self, f"{role}-{n}", [self.suite.worker, role, self.source_root if role == "source" else self.replica_root,
                       self.token, "create" if create else "open", self.port, certs, pin], expect_failure=expect_failure)

    def start(self):
        source, remote = self.node("source"), self.node("receiver")
        remote.command("connect")
        remote.until(lambda r: r["ready"] and r["flows"][0]["D"] == 1)
        return source, remote

    def consumer(self, create=True, flow=1):
        label = f"consumer-{len(self.processes)}"
        return Process(self, label, [self.suite.worker, "consumer", self.replica_root, self.token,
                       "create" if create else "open", flow, self.path / f"PROTOTYPE-consumer-{flow}.bin", 900+flow,
                       hex(0x520000000000 + flow * 0x100000), 0], startup="consumer")

    def cleanup(self):
        for p in reversed(self.processes):
            if p.p.poll() is None:
                try:
                    p.exit()
                except Exception:
                    p.p.kill(); p.p.wait()
        result = subprocess.run([str(self.suite.worker), "unlink", str(self.source_root), self.token], capture_output=True)
        (self.path / "unlink.json").write_text(json.dumps({"code": result.returncode, "stderr": result.stderr.decode()}))


class Suite:
    def __init__(self, worker, parent):
        self.worker = Path(worker).resolve()
        self.root = Path(parent) / ("quic-evidence-" + uuid.uuid4().hex[:12])
        self.root.mkdir(parents=True)
        self.private = Path(tempfile.mkdtemp(prefix="tyche-quic-test-"))
        os.chmod(self.private, 0o700)
        self.certs = self.private / "certs"
        self.certs.mkdir()
        self.checks = []
        self.cert_commands = []
        self.certificates()

    def openssl(self, *args):
        result = subprocess.run(["openssl", *map(str, args)], capture_output=True)
        self.cert_commands.append({"argv": ["openssl", *map(str, args)], "code": result.returncode,
                                   "stdout": result.stdout.decode(), "stderr": result.stderr.decode()})
        assert result.returncode == 0, result.stderr

    def certificates(self):
        c = self.certs
        self.openssl("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
                     "-keyout", c / "ca.key", "-out", c / "ca.pem", "-days", "2", "-subj", "/CN=Tyche disposable prototype CA")
        for name in ["server", "client", "rogue"]:
            self.openssl("req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
                         "-keyout", c / (name + ".key"), "-out", c / (name + ".csr"), "-subj", f"/CN=tyche-{name}")
            ext = c / (name + ".ext")
            ext.write_text("basicConstraints=CA:FALSE\nkeyUsage=digitalSignature\nextendedKeyUsage=" +
                           ("serverAuth\nsubjectAltName=IP:127.0.0.1\n" if name == "server" else "clientAuth\n"))
            self.openssl("x509", "-req", "-in", c / (name + ".csr"), "-CA", c / "ca.pem", "-CAkey", c / "ca.key",
                         "-CAcreateserial", "-out", c / (name + ".pem"), "-days", "2", "-extfile", ext)
            self.openssl("x509", "-in", c / (name + ".pem"), "-outform", "DER", "-out", c / (name + ".der"))
        for path in c.glob("*.key"):
            os.chmod(path, 0o600)
        pub = self.root / "public-certificates"
        pub.mkdir()
        for ext in ["*.pem", "*.der", "*.ext"]:
            for path in c.glob(ext):
                shutil.copyfile(path, pub / path.name)
        (self.root / "certificate-commands.json").write_text(json.dumps(self.cert_commands, indent=2))

    def scenario(self, name, fn):
        test = Test(self, name)
        try:
            fn(test)
        finally:
            test.cleanup()

    def run(self):
        try:
            self.scenario("selective-replay-checkpoint", basic)
            for point in [1, 2, 3, 4]:
                self.scenario(f"receiver-crash-{point}", lambda t, p=point: crash_test(t, p))
            self.scenario("save-error", save_error)
            self.scenario("conflicting-duplicate", conflict)
            self.scenario("stream-reset", stream_reset)
            self.scenario("oversize-frame", oversize_frame)
            for kind in ["wrong-pin", "missing-client-cert", "wrong-ca"]:
                self.scenario(kind, lambda t, k=kind: authentication(t, k))
            self.scenario("slow-receiver", slow)
            self.scenario("source-restart", source_restart)
            result = {"passed": True}
        except Exception as exc:
            result = {"passed": False, "error": str(exc), "traceback": traceback.format_exc()}
        result["checks"] = self.checks
        (self.root / "certificate-commands.json").write_text(json.dumps(self.cert_commands, indent=2))
        result["worker_sha256"] = sha(self.worker)
        result["uname"] = os.uname()._asdict() if hasattr(os.uname(), "_asdict") else list(os.uname())
        result["source_sha256"] = {p.name: sha(p) for p in Path(__file__).parent.iterdir() if p.suffix in [".cpp", ".hpp", ".py"]}
        (self.root / "result.json").write_text(json.dumps(result, indent=2))
        # Private test keys never enter the retained evidence tree.
        shutil.rmtree(self.private)
        print(json.dumps({"evidence": str(self.root), "passed": result["passed"], "checks": len(self.checks), "error": result.get("error")}))
        return result["passed"]


def basic(t):
    s, r = t.start()
    state = r.command("status")
    t.check(state["flows"][1]["head"] == 0, "unsubscribed object remains empty")
    c = t.consumer()
    tick = state["flows"][0]["time"]
    row = c.command(f"consume {tick}")
    t.check(row["cursor"] == 1 and row["quantity_sum"] == 1, "initial committed record processed")
    t.check(row["address"] != state["flows"][0]["address"], "separate exec consumer maps same replica at different address")
    s.command("publish 1 20")
    state = r.until(lambda r: r["flows"][0]["D"] == 21)
    tick = state["flows"][0]["time"]
    row = c.command(f"consume {tick}")
    t.check(row["cursor"] == 21 and row["quantity_sum"] == sum(range(1, 22)), "consumer catches up beyond shared ring from remote durable journal")
    s.command("inject 1 3 duplicate")
    r.until(lambda r: r["duplicates"] == 1)
    t.check(c.command(f"consume {tick}")["quantity_sum"] == row["quantity_sum"], "identical duplicate does not accumulate twice")
    s.command("inject 1 3 old")
    t.check(r.until(lambda r: r["ignored"] >= 1)["flows"][0]["D"] == 21, "old subscription generation ignored")
    r.command("gate_sync")
    s.command("publish 1 1")
    gate = r.wait(lambda e: e.get("event") == "before_sync")
    t.check(gate["R"] == 22 and gate["D"] == gate["V"] == 21, "receive watermark can advance before durability/visibility")
    t.check((t.replica_root / "PROTOTYPE-replica-101.bin").stat().st_size == 22 * 124, "full record exists while sync is paused; file length is not durability")
    row = c.command(f"consume {tick}")
    t.check(row["head"] == row["cursor"] == 21, "strategy cannot read unconfirmed full disk tail")
    r.command("release_sync")
    r.until(lambda r: r["flows"][0]["D"] == 22)
    s.command("pause_flow 2")
    s.command("hold_barrier 1")
    r.command("subscribe 3")
    state = r.command("status")
    t.check(not state["ready"] and state["flows"][1]["D"] == 0, "new dependency blocks readiness until catchup")
    s.command("publish 1 2")
    r.until(lambda r: r["flows"][0]["D"] == 24)
    t.check(not r.command("status")["ready"], "one current stream cannot prove all dependencies current")
    s.command("hold_barrier 0")
    state = r.command("status")
    t.check(not state["storage_failed"] and not state["ready"], "late control barrier may precede already-durable data without rejection")
    s.command("pause_flow 0")
    state = r.until(lambda r: r["ready"] and r["flows"][1]["D"] == 1)
    tick = state["flows"][0]["time"]
    c.command(f"consume {tick}")
    c.command(f"ticket {tick}")
    t.check(c.command(f"reconcile {tick}")["ok"], "caught-up consumer separately reconciles")
    t.check(c.command(f"issue {tick+200}")["ok"], "logical-time stability gate permits mock intent")
    t.check(c.command(f"execute {tick+201}")["result"] == "unknown", "mock execution stores unknown outcome")
    r.command("disconnect")
    r.until(lambda r: r["closed"])
    s.command("publish 1 3")
    r.command("connect")
    state = r.until(lambda r: r["ready"] and r["flows"][0]["D"] == 27)
    tick = state["flows"][0]["time"]
    c.command(f"consume {tick}")
    t.check(c.command(f"execute {tick}")["result"] == "no_resubmit", "reconnect replay does not resend unknown historical intent")
    c.command(f"stop {tick}")
    before = c.command(f"status {tick}")
    c.exit()
    c = t.consumer(create=False)
    restored = c.command(f"consume {tick}")
    t.check(restored["cursor"] == before["cursor"] and restored["quantity_sum"] == before["quantity_sum"], "result and cursor restore as one checkpoint")
    t.check(restored["stopped"] == 1 and not restored["allowed"], "user stop survives restart and replay")
    # Deterministic application sequence hole: pause normal stream, inject a later committed record.
    s.command("pause_flow 1"); s.command("publish 1 3"); s.command("inject 1 30 duplicate")
    state = r.until(lambda r: r["gaps"] == 1)
    t.check(not state["ready"] and state["flows"][0]["D"] == 27, "gap closes readiness without advancing durable prefix")
    s.command("pause_flow 0")
    state = r.until(lambda r: r["ready"] and r["flows"][0]["D"] == 30)
    t.check(state["g"] >= 4, "gap automatically requests new-generation replay from durable cursor")
    # Partial stream frame is retained only in bounded parser memory and discarded on disconnect.
    s.command("inject 1 30 half")
    time.sleep(0.05)
    r.command("disconnect");r.until(lambda r: r["closed"])
    r.command("connect");r.until(lambda r: r["ready"])
    t.check(r.command("status")["flows"][0]["D"] == 30, "half-frame disconnect never appends a record")
    # Live provider cannot be replaced even by an instance with the correct credentials.
    second = t.node("receiver", create=False, expect_failure=True)
    second.exit(expected=1)
    # A consumer missing the brief restricted interval must still observe changed generation.
    s.command("publish 2 1");r.until(lambda r: r["flows"][1]["D"] == 2)
    c2 = t.consumer(flow=2)
    tick2 = r.command("status")["flows"][1]["time"]
    c2.command(f"consume {tick2}");c2.command(f"ticket {tick2}");c2.command(f"reconcile {tick2}")
    pending = c2.command(f"issue {tick2+200}")
    t.check(pending["ok"] and pending["allowed"] and pending["stopped"] == 0, "live unstopped consumer holds pending mock intent before provider restart")
    old_generation = pending["provider_generation"]
    r.exit(kill=True, expected=-9)
    r = t.node("receiver", create=False)
    r.command("connect");state = r.until(lambda r: r["ready"])
    r.command("subscribe 3");r.until(lambda r: r["ready"] and r["mask"] == 3)
    row = c2.command(f"status {tick2+201}")
    t.check(row["provider_generation"] > old_generation and not row["allowed"], "provider restart generation invalidates old local permission")
    c2.command(f"ticket {tick2+201}");c2.command(f"reconcile {tick2+201}")
    t.check(c2.command(f"status {tick2+401}")["allowed"], "fresh reconciliation and stability can restore local permission")
    t.check(c2.command(f"execute {tick2+401}")["result"] == "no_resubmit", "restored permission cannot revive pre-restart pending intent")
    c2.exit();c.exit();r.exit();s.exit()


def crash_test(t, point):
    s, r = t.start()
    c = t.consumer()
    tick = r.command("status")["flows"][0]["time"]
    c.command(f"consume {tick}")
    r.command(f"arm {point}");s.command("publish 1 1")
    r.p.wait(timeout=10);r.exit(expected=77)
    row = c.command(f"consume {tick}")
    t.check(row["head"] == (2 if point == 4 else 1), "crash cut has expected published prefix")
    if point == 1:
        t.check((t.replica_root / "PROTOTYPE-replica-101.bin").stat().st_size == 124 + 62, "partial remote log tail retained exactly")
        failed = t.node("receiver", create=False, expect_failure=True)
        failed.exit(expected=1)
        t.check(c.command(f"status {tick}")["validity"] == "gap", "partial-tail recovery remains restricted")
    else:
        r = t.node("receiver", create=False)
        before = r.command("status")
        t.check(before["flows"][0]["D"] == 2 and not before["ready"], "full validated log recovered but not yet ready")
        r.command("connect");state = r.until(lambda r: r["ready"])
        row = c.command(f"consume {state['flows'][0]['time']}")
        t.check(row["cursor"] == 2 and row["quantity_sum"] == 3, "full crash tail processed exactly once from recovered durable prefix")
        r.exit()
    c.exit();s.exit()


def save_error(t):
    s, r = t.start(); c = t.consumer()
    tick = r.command("status")["flows"][0]["time"]
    c.command(f"consume {tick}")
    r.command("sync_error");s.command("publish 1 1")
    state = r.until(lambda r: r["storage_failed"] and r["closed"])
    t.check(state["flows"][0]["R"] == 2 and state["flows"][0]["D"] == state["flows"][0]["V"] == 1, "failed save never advances durable or published watermark")
    row = c.command(f"consume {tick}")
    t.check(not row["ok"] and not row["allowed"] and row["cursor"] == 1, "save error closes consumer and retains its checkpoint")
    r.exit();r = t.node("receiver", create=False, expect_failure=True);r.exit(expected=1)
    c.exit();s.exit()


def conflict(t):
    s, r = t.start();s.command("inject 1 1 conflict")
    state = r.until(lambda r: r["storage_failed"] and r["closed"])
    t.check(state["flows"][0]["D"] == 1 and not state["ready"], "same sequence with conflicting payload is rejected and latched")
    r.exit();s.exit()


def stream_reset(t):
    s, r = t.start();s.command("inject 1 1 reset")
    state = r.until(lambda r: r["closed"] and not r["ready"])
    t.check(state["flows"][0]["D"] == 1, "stream reset preserves committed replica and closes readiness")
    s.command("publish 1 3");r.command("connect")
    state = r.until(lambda r: r["ready"] and r["flows"][0]["D"] == 4)
    t.check(not state["storage_failed"], "new connection replays required prefix after stream reset")
    r.exit();s.exit()


def oversize_frame(t):
    s, r = t.start();s.command("inject 1 1 oversize")
    state = r.until(lambda r: r["closed"] and not r["ready"])
    t.check(state["flows"][0]["D"] == 1 and "oversize" in state["failure"], "invalid declared length rejected without allocation or publication")
    r.exit();s.exit()


def authentication(t, kind):
    certs, pin = t.suite.certs, None
    if kind == "wrong-pin":
        pin = certs / "rogue.der"
    else:
        alternate = t.suite.private / kind
        shutil.copytree(certs, alternate)
        if kind == "missing-client-cert":
            (alternate / "client.key").unlink();(alternate / "client.pem").unlink()
        elif kind == "wrong-ca":
            t.suite.openssl("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
                            "-keyout", alternate / "different-ca.key", "-out", alternate / "ca.pem", "-days", "2", "-subj", "/CN=untrusted-test-ca")
        certs = alternate
    s = t.node("source", pin=pin)
    r = t.node("receiver", certs=certs)
    r.command("connect");state = r.until(lambda r: r["closed"])
    t.check(not state["ready"] and all(f["D"] == 0 for f in state["flows"]), "untrusted peer cannot publish application records")
    t.check(not any(x.get("event") == "replica_progress" for x in r.rows), "authentication failure precedes replication")
    r.exit();s.exit()


def slow(t):
    s, r = t.start();r.command("slow 150");s.command("publish 1 200", timeout=30)
    state = r.until(lambda r: r["flows"][0]["D"] == 201, timeout=40)
    source = s.command("status")
    t.check(source["max_send_bytes"] <= 8192 and source["max_send_bytes"] >= 3500, "slow receive reaches bounded send pressure without growing application buffer")
    t.check(state["max_borrowed_bytes"] <= 512*1024 and not state["storage_failed"], "borrowed receive buffer bounded; all accepted records persist")
    t.check((t.replica_root / "PROTOTYPE-replica-101.bin").stat().st_size == 201*124, "slow path retains complete exact-sized replica journal")
    r.exit();s.exit()


def source_restart(t):
    s, r = t.start();s.exit(kill=True, expected=-9)
    r.until(lambda r: r["closed"], timeout=12)
    s = t.node("source", create=False)
    r.command("connect");state = r.until(lambda r: r["ready"] and r["flows"][0]["D"] == 2)
    t.check(state["flows"][0]["epoch"] == 2, "source exit proof creates next authority epoch and replica preserves it")
    r.exit();s.exit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True)
    parser.add_argument("--evidence-root", required=True)
    args = parser.parse_args()
    raise SystemExit(0 if Suite(args.worker, args.evidence_root).run() else 1)
