"""Software simulation: fake subsystems and a world that wires them to the Supervisor.

No hardware, no real time. The clock is a number the world advances, so a
full run takes milliseconds and every test is repeatable.
"""
from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

from .messages import FaultCode, Message, MsgType, Node, Step, SUBSYSTEM_NODES
from .route import Route
from .supervisor import Config, State, Supervisor


@dataclass(frozen=True)
class Outcome:
    kind: str  # DONE, FAULT, REFILL, SILENT
    code: Optional[FaultCode] = None
    item: Optional[str] = None


def done() -> Outcome:
    return Outcome("DONE")


def fault(code: FaultCode) -> Outcome:
    return Outcome("FAULT", code=code)


def refill(item: str) -> Outcome:
    return Outcome("REFILL", item=item)


def silent() -> Outcome:
    """Accept the command and never answer. Simulates a crash or a dead cable."""
    return Outcome("SILENT")


class StubSubsystem:
    """Stands in for a real subsystem. Answers each CMD_START from a script.

    Script it with queue(Step.PLATE, fault(...), fault(...), done()). Each
    CMD_START for that step uses up one outcome. When the script is empty it
    answers DONE.
    """

    def __init__(self, node: Node, response_time_s: float = 0.2):
        self.node = node
        self.response_time_s = response_time_s
        self.script: dict[Step, deque[Outcome]] = {}
        self.commands: list[Message] = []
        self.aborts: list[Message] = []
        self._due: Optional[tuple[float, Message]] = None

    def queue(self, step: Step, *outcomes: Outcome) -> "StubSubsystem":
        self.script.setdefault(step, deque()).extend(outcomes)
        return self

    def on_message(self, msg: Message, now: float) -> None:
        if msg.type is MsgType.CMD_ABORT:
            self.aborts.append(msg)
            self._due = None
        elif msg.type is MsgType.CMD_START:
            self.commands.append(msg)
            steps = self.script.get(Step(msg.step))
            outcome = steps.popleft() if steps else done()
            if outcome.kind == "SILENT":
                self._due = None
                return
            self._due = (now + self.response_time_s, self._reply(msg, outcome))

    def tick(self, now: float) -> list[Message]:
        if self._due and now >= self._due[0]:
            reply = self._due[1]
            self._due = None
            return [reply]
        return []

    def _reply(self, cmd: Message, outcome: Outcome) -> Message:
        common = dict(src=self.node, dst=Node.SUPERVISOR, ref=cmd.id, row=cmd.row, spot=cmd.spot,
                      attempt=cmd.attempt, step=cmd.step)
        if outcome.kind == "DONE":
            return Message(MsgType.DONE, **common)
        if outcome.kind == "FAULT":
            return Message(MsgType.FAULT, code=outcome.code, **common)
        return Message(MsgType.NEED_REFILL, params={"item": outcome.item}, **common)

    def commands_for(self, step: Step) -> list[Message]:
        return [c for c in self.commands if c.step == step.value]


class StubCamera:
    """Sends a heartbeat with ok=True/False. Set ok=False for a blocked lens or dark image,
    or silent=True for a dead feed."""

    def __init__(self, interval_s: float = 0.25):
        self.interval_s = interval_s
        self.ok = True
        self.silent = False
        self._last: Optional[float] = None

    def on_message(self, msg: Message, now: float) -> None:
        pass

    def tick(self, now: float) -> list[Message]:
        if self.silent:
            return []
        if self._last is None or now - self._last >= self.interval_s:
            self._last = now
            return [Message(MsgType.HEARTBEAT, Node.CAMERA, Node.SUPERVISOR, params={"ok": self.ok})]
        return []


class SimWorld:
    """Wires a Supervisor to stub subsystems and a stub camera, with message latency."""

    def __init__(self, route: Route, config: Optional[Config] = None,
                 latency_s: float = 0.005, response_time_s: float = 0.2, detailed: bool = False):
        """detailed=True uses subsystems that walk through their own flowcharts (roofbot/detail.py).
        The default simple stubs answer after response_time_s and are what the fast tests use."""
        self.now = 0.0
        self.latency_s = latency_s
        self.trace: list[tuple[float, Message]] = []
        self.alerts: list[Message] = []
        self.light: Optional[tuple[str, str]] = None  # (color, mode) the stack light is showing
        self.light_history: list[tuple[float, str, str]] = []
        if detailed:
            from .detail import ProcessSubsystem
            make = ProcessSubsystem
        else:
            make = lambda node: StubSubsystem(node, response_time_s)  # noqa: E731
        self.detailed = detailed
        self.locomotion = make(Node.LOCOMOTION)
        self.plate = make(Node.PLATE)
        self.screw = make(Node.SCREW)
        self.fastening = make(Node.FASTENING)
        self.camera = StubCamera()
        self._stubs = {
            Node.LOCOMOTION.value: self.locomotion,
            Node.PLATE.value: self.plate,
            Node.SCREW.value: self.screw,
            Node.FASTENING.value: self.fastening,
            Node.CAMERA.value: self.camera,
        }
        self._queue: list[tuple[float, int, Message]] = []
        self._seq = 0
        self.supervisor = Supervisor(route, config, send=self._route)

    # ---- driving the simulation

    def step(self, dt: float = 0.01) -> None:
        self.now += dt
        while self._queue and self._queue[0][0] <= self.now:
            _, _, msg = heapq.heappop(self._queue)
            self._deliver(msg)
        for stub in self._stubs.values():
            for msg in stub.tick(self.now):
                self._route(msg)
        self.supervisor.tick(self.now)

    def run(self, seconds: float, dt: float = 0.01) -> None:
        end = self.now + seconds
        while self.now < end:
            self.step(dt)

    def run_until(self, predicate: Callable[[], bool], timeout_s: float = 600.0, dt: float = 0.01) -> bool:
        end = self.now + timeout_s
        while self.now < end:
            if predicate():
                return True
            self.step(dt)
        return predicate()

    def run_until_state(self, state: State, timeout_s: float = 600.0) -> bool:
        return self.run_until(lambda: self.supervisor.state is state, timeout_s)

    def start_run(self) -> None:
        """Let the camera heartbeat arrive (the Supervisor will not start without it), then press START."""
        self.run(0.1)
        self.operator(MsgType.START)

    # ---- operator and E-stop inputs

    def operator(self, mtype: MsgType) -> None:
        src = Node.ESTOP if mtype is MsgType.ESTOP else Node.OPERATOR
        self._deliver(Message(mtype, src, Node.SUPERVISOR))

    # ---- internals

    def _route(self, msg: Message) -> None:
        self.trace.append((self.now, msg))
        self._seq += 1
        heapq.heappush(self._queue, (self.now + self.latency_s, self._seq, msg))

    def _deliver(self, msg: Message) -> None:
        if msg.dst == Node.SUPERVISOR.value:
            self.supervisor.on_message(msg, self.now)
        elif msg.dst == Node.OPERATOR.value:
            self.alerts.append(msg)
        elif msg.dst == Node.LIGHT.value:
            self.light = (msg.params["color"], msg.params["mode"])
            self.light_history.append((self.now, *self.light))
        elif msg.dst == Node.ALL.value:
            for node in SUBSYSTEM_NODES:
                self._stubs[node.value].on_message(msg, self.now)
        else:
            stub = self._stubs.get(msg.dst)
            if stub:
                stub.on_message(msg, self.now)
