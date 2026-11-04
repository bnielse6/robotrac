"""Visual dashboard for the simulator and the tests.

    python dashboard.py

Opens http://127.0.0.1:8765 in your browser. Standard library only.
The page (ui/index.html) polls this server a few times a second.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from roofbot.detail import FLOWS
from roofbot.messages import FaultCode, MsgType, Step
from roofbot.route import Route, RowPlan
from roofbot.sim import SimWorld, done, fault, refill, silent

HERE = Path(__file__).resolve().parent
UI_FILE = HERE / "ui" / "index.html"
SIM_DT = 0.01
TRACE_LIMIT = 250


def parse_outcome(text: str):
    """'DONE', 'FAULT:OFF_BEAM', 'REFILL:PLATES' or 'SILENT'."""
    kind, _, arg = text.partition(":")
    if kind == "DONE":
        return done()
    if kind == "FAULT":
        return fault(FaultCode(arg))
    if kind == "REFILL":
        return refill(arg)
    if kind == "SILENT":
        return silent()
    raise ValueError(f"unknown outcome {text!r}")


# name -> (description, auto_start, injections as (stub name, step, [outcomes]))
PRESETS = {
    "happy": ("Happy path, nothing goes wrong", True, []),
    "retry-ok": ("Plate fails once, the retry works", True,
                 [("plate", "PLATE", ["FAULT:PLATE_NOT_ARRIVED"])]),
    "plate-jam": ("Plate fails 3 times, robot stops, operator resolves", True,
                  [("plate", "PLATE", ["FAULT:PLATE_NOT_ARRIVED"] * 3)]),
    "torque": ("Torque times out twice, then works", True,
               [("fastening", "FASTEN", ["FAULT:TORQUE_TIMEOUT"] * 2)]),
    "out-of-screws": ("Screws run out at the first spot (refill them on the SCREW panel, then RESOLVED)", True,
                      [("screw", "SCREW", ["REFILL:SCREWS"])]),
    "off-beam": ("Robot goes off the beam 3 times (no skip allowed)", True,
                 [("locomotion", "DRIVE", ["FAULT:OFF_BEAM"] * 3)]),
    "silent-screw": ("Screw subsystem stops answering (timeout)", True,
                     [("screw", "SCREW", ["SILENT"])]),
    "manual": ("Empty, press START yourself", False, []),
}


class Controller:
    """Owns the simulated world and advances it in real time."""

    def __init__(self):
        self.lock = threading.RLock()
        self.speed = 1.0
        self.paused = False
        self._acc = 0.0
        self._quit = False
        self.preset = "manual"
        self.rows, self.spots = 2, 3
        self._new_world()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ---- world

    def _new_world(self) -> None:
        route = Route([RowPlan(self.spots, 300.0, 100.0 if i == 0 else 0.0) for i in range(self.rows)])
        self.world = SimWorld(route, detailed=True)

    def _stub(self, name: str):
        stubs = {"locomotion": self.world.locomotion, "plate": self.world.plate,
                 "screw": self.world.screw, "fastening": self.world.fastening}
        return stubs[name]

    def _loop(self) -> None:
        last = time.monotonic()
        while not self._quit:
            time.sleep(0.02)
            now = time.monotonic()
            real = min(now - last, 0.2)
            last = now
            with self.lock:
                if self.paused:
                    continue
                self._acc += real * self.speed
                while self._acc >= SIM_DT:
                    self.world.step(SIM_DT)
                    self._acc -= SIM_DT

    def stop(self) -> None:
        self._quit = True

    # ---- actions

    def action(self, req: dict) -> dict:
        kind = req.get("action")
        with self.lock:
            if kind == "operator":
                self.world.operator(MsgType(req["type"]))
            elif kind == "inject":
                outcomes = [parse_outcome(o) for o in req["outcomes"]]
                self._stub(req["node"]).queue(Step(req["step"]), *outcomes)
            elif kind == "clear_script":
                self._stub(req["node"]).script.clear()
            elif kind == "refill":
                self._stub(req["node"]).refill(int(req.get("count", 12)))
            elif kind == "camera":
                if "ok" in req:
                    self.world.camera.ok = bool(req["ok"])
                if "silent" in req:
                    self.world.camera.silent = bool(req["silent"])
            elif kind == "speed":
                self.speed = max(0.1, min(float(req["value"]), 50.0))
            elif kind == "pause":
                self.paused = bool(req["value"])
            elif kind == "step":
                self.world.run(float(req.get("seconds", 0.1)), SIM_DT)
            elif kind == "reset":
                self.rows = max(1, min(int(req.get("rows", self.rows)), 8))
                self.spots = max(1, min(int(req.get("spots", self.spots)), 10))
                self.preset = req.get("preset", "manual")
                self._new_world()
                self._apply_preset(self.preset)
            else:
                raise ValueError(f"unknown action {kind!r}")
        return {"ok": True}

    def _apply_preset(self, name: str) -> None:
        _, auto_start, injections = PRESETS[name]
        for stub, step, outcomes in injections:
            self._stub(stub).queue(Step(step), *[parse_outcome(o) for o in outcomes])
        if auto_start:
            self.world.start_run()

    # ---- state for the page

    def snapshot(self, include_heartbeats: bool = False) -> dict:
        with self.lock:
            w = self.world
            s = w.supervisor
            trace = []
            for i, (t, m) in enumerate(w.trace):
                if m.type is MsgType.HEARTBEAT and not include_heartbeats:
                    continue
                d = m.to_dict()
                d.pop("t", None)
                d["time"] = round(t, 3)
                d["i"] = i
                trace.append(d)
            pending = None
            if s.pending:
                pending = {"node": s.pending.node.value, "step": s.pending.step.value,
                           "deadline": round(s.pending.deadline, 2)}
            stubs = {}
            for name in ("locomotion", "plate", "screw", "fastening"):
                st = self._stub(name)
                stubs[name] = {
                    "detail": st.detail(w.now) if hasattr(st, "detail") else None,
                    "busy": st._due is not None,
                    "commands": len(st.commands),
                    "aborts": len(st.aborts),
                    "last_step": st.commands[-1].step if st.commands else None,
                    "last_attempt": st.commands[-1].attempt if st.commands else None,
                    "script": {step.value: [self._describe(o) for o in q]
                               for step, q in st.script.items() if q},
                }
            return {
                "time": round(w.now, 2),
                "paused": self.paused,
                "speed": self.speed,
                "preset": self.preset,
                "state": s.state.value,
                "resume_state": s.resume_state.value if s.resume_state else None,
                "row": s.row,
                "spot": s.spot,
                "retries": s.retries,
                "max_retries": s.config.max_retries,
                "allow_skip": s.allow_skip,
                "pending": pending,
                "route": [r.spots for r in w.supervisor.route.rows],
                "skipped": [list(x) for x in s.skipped_spots],
                "stubs": stubs,
                "camera": {"ok": w.camera.ok, "silent": w.camera.silent, "usable": s.camera_usable},
                "light": {"color": w.light[0], "mode": w.light[1]} if w.light else None,
                "alerts": [a.to_dict() for a in w.alerts[-15:]],
                "fault_log": [vars(r) for r in s.fault_log],
                "events": s.events[-40:],
                "trace": trace[-TRACE_LIMIT:],
                "trace_total": len(w.trace),
            }

    @staticmethod
    def _describe(o) -> str:
        if o.kind == "FAULT":
            return f"FAULT:{o.code.value}"
        if o.kind == "REFILL":
            return f"REFILL:{o.item}"
        return o.kind


class TestRunner:
    """Runs the unittest suite in a subprocess and keeps the output."""

    LINE = re.compile(r"^(\w+) \(([\w.]+)\) \.\.\. (ok|FAIL|ERROR|skipped.*)$")

    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.output = ""
        self.finished_at = None

    def start(self) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.output = ""
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _run(self) -> None:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"],
                cwd=HERE, capture_output=True, text=True, timeout=300)
            text = proc.stdout + proc.stderr
        except Exception as exc:  # noqa: BLE001
            text = f"Could not run the tests: {exc}"
        with self.lock:
            self.output = text
            self.running = False
            self.finished_at = time.time()

    def result(self) -> dict:
        with self.lock:
            tests, ran, status = [], None, None
            for line in self.output.splitlines():
                m = self.LINE.match(line.strip())
                if m:
                    tests.append({"name": m.group(1), "group": m.group(2).rsplit(".", 1)[0],
                                  "result": m.group(3)})
                elif line.startswith("Ran "):
                    ran = line
                elif line.strip() in ("OK",) or line.startswith("FAILED"):
                    status = line.strip()
            return {"running": self.running, "tests": tests, "ran": ran, "status": status,
                    "output": self.output}


def make_handler(ctrl: Controller, runner: TestRunner):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        def _json(self, payload, code=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                body = UI_FILE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif url.path == "/api/state":
                hb = parse_qs(url.query).get("hb", ["0"])[0] == "1"
                self._json(ctrl.snapshot(include_heartbeats=hb))
            elif url.path == "/api/meta":
                self._json({"presets": {k: v[0] for k, v in PRESETS.items()},
                            "fault_codes": [c.value for c in FaultCode],
                            "flows": FLOWS})
            elif url.path == "/api/tests":
                self._json(runner.result())
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/action":
                    self._json(ctrl.action(req))
                elif self.path == "/api/run_tests":
                    self._json({"started": runner.start()})
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, 400)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    ctrl, runner = Controller(), TestRunner()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(ctrl, runner))
    url = f"http://127.0.0.1:{args.port}"
    print(f"Dashboard running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ctrl.stop()
        server.server_close()


if __name__ == "__main__":
    main()
