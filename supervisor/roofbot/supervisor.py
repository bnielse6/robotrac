"""The Supervisor state machine (section 5 of the system guide).

It knows nothing about serial ports or the simulator. It is given a `send`
callable and is driven by two calls: on_message(msg, now) and tick(now).
`now` is a number of seconds from any clock, which makes it easy to test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from .messages import FaultCode, Message, MsgType, Node, Step, SUBSYSTEM_NODES
from .route import Route


class State(str, Enum):
    IDLE = "IDLE"
    DRIVE_TO_SPOT = "DRIVE_TO_SPOT"
    PLATE = "PLATE"
    SCREW = "SCREW"
    FASTEN = "FASTEN"
    TURN_TO_NEXT_ROW = "TURN_TO_NEXT_ROW"
    WAIT_OPERATOR = "WAIT_OPERATOR"
    RUN_COMPLETE = "RUN_COMPLETE"
    ESTOP = "ESTOP"


# Which subsystem and step each working state commands.
STATE_STEP = {
    State.DRIVE_TO_SPOT: (Node.LOCOMOTION, Step.DRIVE),
    State.PLATE: (Node.PLATE, Step.PLATE),
    State.SCREW: (Node.SCREW, Step.SCREW),
    State.FASTEN: (Node.FASTENING, Step.FASTEN),
    State.TURN_TO_NEXT_ROW: (Node.LOCOMOTION, Step.TURN),
}


# What the stack light shows in each state (section 3.8 of the system guide): (color, mode).
STATE_LIGHT = {
    State.IDLE: ("GREEN", "FLASH"),
    State.DRIVE_TO_SPOT: ("GREEN", "STEADY"),
    State.PLATE: ("GREEN", "STEADY"),
    State.SCREW: ("GREEN", "STEADY"),
    State.FASTEN: ("GREEN", "STEADY"),
    State.TURN_TO_NEXT_ROW: ("GREEN", "STEADY"),
    State.WAIT_OPERATOR: ("AMBER", "FLASH"),
    State.RUN_COMPLETE: ("GREEN", "FLASH"),
    State.ESTOP: ("RED", "STEADY"),
}


@dataclass
class Config:
    max_retries: int = 2  # N in the guide. A step runs at most 1 + N times.
    # Placeholders. The guide says these are still to be found in testing.
    step_timeout_s: dict = field(default_factory=lambda: {
        Step.DRIVE: 30.0,
        Step.TURN: 30.0,
        Step.PLATE: 20.0,
        Step.SCREW: 15.0,
        Step.FASTEN: 25.0,
    })
    camera_timeout_s: float = 1.0
    heartbeat_interval_s: float = 0.5


@dataclass
class Pending:
    msg_id: int
    node: Node
    step: Step
    deadline: float


@dataclass
class FaultRecord:
    time: float
    row: int
    spot: int
    subsystem: str
    code: str
    detail: str = ""
    action: Optional[str] = None  # RESOLVED, SKIPPED, ESTOP


class Supervisor:
    def __init__(self, route: Route, config: Optional[Config] = None,
                 send: Optional[Callable[[Message], None]] = None):
        self.route = route
        self.config = config or Config()
        self._send_cb = send or (lambda msg: None)

        self.state = State.IDLE
        self.row = 0
        self.spot = 0
        self.retries = 0
        self.pending: Optional[Pending] = None

        self.resume_state: Optional[State] = None
        self.active_fault: Optional[FaultRecord] = None
        self.allow_skip = False
        self.fault_log: list[FaultRecord] = []
        self.skipped_spots: list[tuple[int, int]] = []

        self.transitions: list[tuple[float, State, State]] = []
        self.events: list[str] = []

        self._next_id = 1
        self._now = 0.0
        self._last_heartbeat_sent: Optional[float] = None
        self._camera_last_seen: Optional[float] = None
        self._camera_ok_flag = False
        self.light: Optional[tuple[str, str]] = None  # what was last sent to the stack light

    # ------------------------------------------------------------ inputs

    def on_message(self, msg: Message, now: float) -> None:
        self._now = now
        t = msg.type
        if t is MsgType.ESTOP:
            self._estop()
        elif t is MsgType.HEARTBEAT:
            if msg.src == Node.CAMERA.value:
                self._camera_last_seen = now
                self._camera_ok_flag = bool(msg.params.get("ok", True))
        elif t is MsgType.READY:
            self._on_ready(msg)
        elif t is MsgType.START:
            self._on_start()
        elif t in (MsgType.DONE, MsgType.FAULT, MsgType.NEED_REFILL):
            self._on_subsystem_reply(msg)
        elif t is MsgType.RESOLVED:
            self._on_resolved()
        elif t is MsgType.SKIP_SPOT:
            self._on_skip()
        elif t is MsgType.RESET:
            self._on_reset()
        else:
            self._log(f"ignored {t.value} from {msg.src}")

    def tick(self, now: float) -> None:
        self._now = now
        if self.light is None:
            self._update_light()  # first tick: tell the light we are in IDLE
        interval = self.config.heartbeat_interval_s
        if self._last_heartbeat_sent is None or now - self._last_heartbeat_sent >= interval:
            self._last_heartbeat_sent = now
            self._send(Message(MsgType.HEARTBEAT, Node.SUPERVISOR, Node.ALL))

        if self.state not in STATE_STEP:
            return
        if not self._camera_ok():
            self._abort_pending()
            self._stop(Node.CAMERA, FaultCode.CAMERA_FEED_LOST, allow_skip=False)
            return
        if self.pending and now >= self.pending.deadline:
            node = self.pending.node
            self._log(f"timeout waiting for {node.value} {self.pending.step.value}")
            self._abort_pending()
            self._stop(node, FaultCode.SUBSYSTEM_UNRESPONSIVE, allow_skip=False, detail="timeout")

    # ------------------------------------------------------------ handlers

    def _on_start(self) -> None:
        if self.state is not State.IDLE:
            self._log(f"START ignored in {self.state.value}")
            return
        if not self._camera_ok():
            self._alert(Node.CAMERA, FaultCode.CAMERA_FEED_LOST, allow_skip=False,
                        detail="cannot start, camera feed not usable")
            return
        self.row, self.spot = 1, 1
        self._set_state(State.DRIVE_TO_SPOT)
        self._issue_command()

    def _on_subsystem_reply(self, msg: Message) -> None:
        p = self.pending
        if p is None or msg.ref != p.msg_id or msg.src != p.node.value:
            self._log(f"ignored stale {msg.type.value} from {msg.src} (ref {msg.ref})")
            return
        self.pending = None

        if msg.type is MsgType.DONE:
            self._advance()
        elif msg.type is MsgType.NEED_REFILL:
            self._stop(p.node, FaultCode.NEED_REFILL, allow_skip=True, detail=str(msg.params.get("item")))
        else:  # FAULT
            code = FaultCode(msg.code)
            if self.retries < self.config.max_retries:
                self.retries += 1
                self._log(f"{p.node.value} {code.value}, retry {self.retries} of {self.config.max_retries}")
                self._issue_command()
            else:
                allow_skip = p.node is not Node.LOCOMOTION
                self._stop(p.node, code, allow_skip=allow_skip)

    def _on_ready(self, msg: Message) -> None:
        """A subsystem announcing it has just booted. Mid-step this means it lost the command."""
        self._update_light(force=True)  # the board that drives the light may have just restarted
        if self.pending and msg.src in {n.value for n in SUBSYSTEM_NODES}:
            node = self.pending.node
            self._log(f"{msg.src} rebooted during {self.pending.step.value}")
            self._abort_pending()
            self._stop(node, FaultCode.SUBSYSTEM_UNRESPONSIVE, allow_skip=False, detail="rebooted")

    def _on_resolved(self) -> None:
        if self.state is not State.WAIT_OPERATOR:
            self._log(f"RESOLVED ignored in {self.state.value}")
            return
        fault = self.active_fault
        if fault and fault.code == FaultCode.CAMERA_FEED_LOST.value and not self._camera_ok():
            self._alert(Node.CAMERA, FaultCode.CAMERA_FEED_LOST, allow_skip=False,
                        detail="feed still not usable")
            return
        if fault:
            fault.action = "RESOLVED"
        self.active_fault = None
        self._set_state(self.resume_state)
        self._issue_command()

    def _on_skip(self) -> None:
        if self.state is not State.WAIT_OPERATOR:
            self._log(f"SKIP_SPOT ignored in {self.state.value}")
            return
        if not self.allow_skip:
            fault = self.active_fault
            self._alert(Node(fault.subsystem), FaultCode(fault.code), allow_skip=False,
                        detail="skip is not allowed for this fault")
            return
        if self.active_fault:
            self.active_fault.action = "SKIPPED"
        self.skipped_spots.append((self.row, self.spot))
        self.active_fault = None
        self._after_spot()

    def _on_reset(self) -> None:
        if self.state in (State.ESTOP, State.RUN_COMPLETE):
            self.pending = None
            self._set_state(State.IDLE)
        else:
            self._log(f"RESET ignored in {self.state.value}")

    def _estop(self) -> None:
        if self.state is State.ESTOP:
            return
        for node in SUBSYSTEM_NODES:
            self._send(Message(MsgType.CMD_ABORT, Node.SUPERVISOR, node))
        self.pending = None
        if self.active_fault:
            self.active_fault.action = "ESTOP"
        self.fault_log.append(FaultRecord(self._now, self.row, self.spot, Node.ESTOP.value,
                                          FaultCode.ESTOP.value, action="ESTOP"))
        self.active_fault = None
        self.resume_state = None
        self._set_state(State.ESTOP)

    # ------------------------------------------------------------ flow

    def _advance(self) -> None:
        """The current step reported DONE. Move to the next one."""
        s = self.state
        if s is State.DRIVE_TO_SPOT:
            self._set_state(State.PLATE)
        elif s is State.PLATE:
            self._set_state(State.SCREW)
        elif s is State.SCREW:
            self._set_state(State.FASTEN)
        elif s is State.FASTEN:
            self._after_spot()
            return
        elif s is State.TURN_TO_NEXT_ROW:
            self.row += 1
            self.spot = 1
            self._set_state(State.DRIVE_TO_SPOT)
        self._issue_command()

    def _after_spot(self) -> None:
        """The row check: more spots, end of row, or last spot of the last row."""
        if self.spot < self.route.spots_in_row(self.row):
            self.spot += 1
            self._set_state(State.DRIVE_TO_SPOT)
        elif self.row < self.route.row_count:
            self._set_state(State.TURN_TO_NEXT_ROW)
        else:
            self._set_state(State.RUN_COMPLETE)
            return
        self._issue_command()

    def _issue_command(self) -> None:
        node, step = STATE_STEP[self.state]
        self.pending = Pending(
            msg_id=self._take_id(),
            node=node,
            step=step,
            deadline=self._now + self.config.step_timeout_s[step],
        )
        params: dict = {}
        if step is Step.DRIVE:
            params["distance_mm"] = self.route.distance_to_spot_mm(self.row, self.spot)
        elif step is Step.TURN:
            params["direction"] = self.route.turn_direction(self.row)
        self._send(Message(MsgType.CMD_START, Node.SUPERVISOR, node, id=self.pending.msg_id,
                           row=self.row, spot=self.spot, attempt=self.retries + 1,
                           step=step, params=params))

    def _stop(self, node: Node, code: FaultCode, allow_skip: bool, detail: str = "") -> None:
        """Stop where we are and wait for the operator."""
        self.resume_state = self.state
        self.pending = None
        self.allow_skip = allow_skip
        record = FaultRecord(self._now, self.row, self.spot, node.value, code.value, detail)
        self.fault_log.append(record)
        self.active_fault = record
        self._set_state(State.WAIT_OPERATOR)
        self._alert(node, code, allow_skip, detail)

    def _alert(self, node: Node, code: FaultCode, allow_skip: bool, detail: str = "") -> None:
        self._send(Message(MsgType.ALERT, Node.SUPERVISOR, Node.OPERATOR, row=self.row, spot=self.spot,
                           code=code, params={"subsystem": node.value, "allow_skip": allow_skip,
                                              "detail": detail}))

    def _abort_pending(self) -> None:
        if self.pending:
            self._send(Message(MsgType.CMD_ABORT, Node.SUPERVISOR, self.pending.node))
            self.pending = None

    # ------------------------------------------------------------ helpers

    @property
    def camera_usable(self) -> bool:
        return self._camera_ok()

    def _camera_ok(self) -> bool:
        return (self._camera_last_seen is not None
                and self._now - self._camera_last_seen <= self.config.camera_timeout_s
                and self._camera_ok_flag)

    def _take_id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    def _send(self, msg: Message) -> None:
        msg.t = self._now
        self._send_cb(msg)

    def _set_state(self, new: State) -> None:
        self.transitions.append((self._now, self.state, new))
        self.state = new
        self.retries = 0  # a retry re-issues the command without changing state
        self._update_light()

    def _update_light(self, force: bool = False) -> None:
        """Send the stack light its pattern if it changed (or always, with force)."""
        color, mode = STATE_LIGHT[self.state]
        if not force and self.light == (color, mode):
            return
        self.light = (color, mode)
        self._send(Message(MsgType.LIGHT, Node.SUPERVISOR, Node.LIGHT, params={"color": color, "mode": mode}))

    def _log(self, text: str) -> None:
        self.events.append(f"{self._now:8.3f}  {text}")
