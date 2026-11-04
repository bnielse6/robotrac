"""Message schema for the roofing robot.

One JSON object per line over USB serial (and the same objects in the simulator).
See docs/message_schema.md for the written contract.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Union

PROTOCOL_VERSION = 1
MAX_LINE_BYTES = 512  # the ESP32 line buffer is this size too


class MessageError(ValueError):
    """A line could not be decoded or failed validation."""


class MsgType(str, Enum):
    # operator and E-stop to Supervisor
    START = "START"
    RESOLVED = "RESOLVED"
    SKIP_SPOT = "SKIP_SPOT"
    ESTOP = "ESTOP"
    RESET = "RESET"
    # Supervisor to subsystem
    CMD_START = "CMD_START"
    CMD_ABORT = "CMD_ABORT"
    # subsystem to Supervisor
    DONE = "DONE"
    FAULT = "FAULT"
    NEED_REFILL = "NEED_REFILL"
    # Supervisor to operator screen
    ALERT = "ALERT"
    # Supervisor to the stack light on the robot (output only, no reply)
    LIGHT = "LIGHT"
    # liveness
    HEARTBEAT = "HEARTBEAT"
    READY = "READY"
    # subsystem to camera and back. The camera runs on the Pi, the subsystems on the ESP32.
    QUERY = "QUERY"
    ANSWER = "ANSWER"


class Node(str, Enum):
    SUPERVISOR = "SUP"
    OPERATOR = "OPERATOR"
    ESTOP = "ESTOP"
    LOCOMOTION = "LOCOMOTION"
    PLATE = "PLATE"
    SCREW = "SCREW"
    FASTENING = "FASTENING"
    CAMERA = "CAMERA"
    LIGHT = "LIGHT"  # the stack light, driven by the ESP32's outputs
    ALL = "ALL"  # broadcast, used for the Supervisor heartbeat


SUBSYSTEM_NODES = (Node.LOCOMOTION, Node.PLATE, Node.SCREW, Node.FASTENING)


class Step(str, Enum):
    DRIVE = "DRIVE"
    TURN = "TURN"
    PLATE = "PLATE"
    SCREW = "SCREW"
    FASTEN = "FASTEN"


class FaultCode(str, Enum):
    PLATE_NOT_ARRIVED = "PLATE_NOT_ARRIVED"
    PLACEMENT_REJECTED = "PLACEMENT_REJECTED"
    SCREW_NOT_IN_POSITION = "SCREW_NOT_IN_POSITION"
    TORQUE_TIMEOUT = "TORQUE_TIMEOUT"
    PHOTO_REJECTED = "PHOTO_REJECTED"
    OFF_BEAM = "OFF_BEAM"
    CANNOT_REACH_SPOT = "CANNOT_REACH_SPOT"
    TURN_FAILED = "TURN_FAILED"
    CAMERA_FEED_LOST = "CAMERA_FEED_LOST"
    SUBSYSTEM_UNRESPONSIVE = "SUBSYSTEM_UNRESPONSIVE"
    NEED_REFILL = "NEED_REFILL"
    ESTOP = "ESTOP"


REFILL_ITEMS = ("PLATES", "SCREWS")

# What a subsystem can ask the camera. PHOTO_OK means "take the photo and tell me if it is accepted".
CAMERA_QUESTIONS = ("PLATE_ARRIVED", "PLACEMENT_OK", "PLATE_SCREW_OK", "PHOTO_OK")


# Stack light. params.color is one of LIGHT_COLORS and params.mode one of LIGHT_MODES.
LIGHT_COLORS = ("GREEN", "AMBER", "RED", "OFF")
LIGHT_MODES = ("STEADY", "FLASH")


def _val(x: Any) -> Any:
    return x.value if isinstance(x, Enum) else x


@dataclass
class Message:
    type: MsgType
    src: str
    dst: str
    id: Optional[int] = None        # set on messages that expect an answer
    ref: Optional[int] = None       # id of the CMD_START being answered
    row: Optional[int] = None
    spot: Optional[int] = None
    attempt: Optional[int] = None   # 1 for the first try, 2 for the first retry, ...
    step: Optional[str] = None
    code: Optional[str] = None
    params: dict = field(default_factory=dict)
    t: Optional[float] = None       # sender's clock, seconds. For logging only.

    def __post_init__(self) -> None:
        self.type = MsgType(_val(self.type))
        self.src = _val(self.src)
        self.dst = _val(self.dst)
        self.step = _val(self.step)
        self.code = _val(self.code)

    def to_dict(self) -> dict:
        d: dict = {"v": PROTOCOL_VERSION, "type": self.type.value, "src": self.src, "dst": self.dst}
        for key in ("id", "ref", "row", "spot", "attempt", "step", "code", "t"):
            value = getattr(self, key)
            if value is not None:
                d[key] = value
        if self.params:
            d["params"] = self.params
        return d


_REQUIRED = {
    MsgType.CMD_START: ("id", "row", "spot", "attempt", "step"),
    MsgType.DONE: ("ref",),
    MsgType.FAULT: ("ref", "code"),
    MsgType.NEED_REFILL: ("ref",),
    MsgType.ALERT: ("code",),
    MsgType.LIGHT: (),
    MsgType.QUERY: ("id",),
    MsgType.ANSWER: ("ref",),
}

_INT_FIELDS = ("id", "ref", "row", "spot", "attempt")


def validate(msg: Message) -> None:
    for name in _REQUIRED.get(msg.type, ()):
        if getattr(msg, name) is None:
            raise MessageError(f"{msg.type.value} needs '{name}'")
    for name in _INT_FIELDS:
        value = getattr(msg, name)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise MessageError(f"'{name}' must be an integer")
    if msg.step is not None and msg.step not in {s.value for s in Step}:
        raise MessageError(f"unknown step '{msg.step}'")
    if msg.code is not None and msg.type is MsgType.FAULT and msg.code not in {c.value for c in FaultCode}:
        raise MessageError(f"unknown fault code '{msg.code}'")
    if msg.type is MsgType.NEED_REFILL and msg.params.get("item") not in REFILL_ITEMS:
        raise MessageError("NEED_REFILL needs params.item of PLATES or SCREWS")
    if msg.type is MsgType.LIGHT:
        if msg.params.get("color") not in LIGHT_COLORS:
            raise MessageError(f"LIGHT needs params.color, one of {LIGHT_COLORS}")
        if msg.params.get("mode") not in LIGHT_MODES:
            raise MessageError(f"LIGHT needs params.mode, one of {LIGHT_MODES}")
    if msg.type is MsgType.QUERY and msg.params.get("question") not in CAMERA_QUESTIONS:
        raise MessageError(f"QUERY needs params.question, one of {CAMERA_QUESTIONS}")
    if msg.type is MsgType.ANSWER and not isinstance(msg.params.get("ok"), bool):
        raise MessageError("ANSWER needs params.ok as true or false")
    if not isinstance(msg.params, dict):
        raise MessageError("'params' must be an object")


def encode(msg: Message) -> bytes:
    """Message to one newline-terminated JSON line."""
    validate(msg)
    line = json.dumps(msg.to_dict(), separators=(",", ":")).encode("utf-8")
    if len(line) + 1 > MAX_LINE_BYTES:
        raise MessageError(f"encoded message is {len(line) + 1} bytes, limit is {MAX_LINE_BYTES}")
    return line + b"\n"


def decode(line: Union[bytes, str]) -> Message:
    """One line to a Message. Raises MessageError on anything wrong."""
    if isinstance(line, bytes):
        if len(line) > MAX_LINE_BYTES:
            raise MessageError("line too long")
        try:
            line = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MessageError(f"not valid UTF-8: {exc}") from exc
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as exc:
        raise MessageError(f"not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise MessageError("message must be a JSON object")
    if raw.get("v") != PROTOCOL_VERSION:
        raise MessageError(f"unsupported protocol version {raw.get('v')!r}")
    for name in ("type", "src", "dst"):
        if name not in raw:
            raise MessageError(f"missing '{name}'")
    try:
        mtype = MsgType(raw["type"])
    except ValueError as exc:
        raise MessageError(f"unknown type {raw['type']!r}") from exc
    params = raw.get("params", {})
    msg = Message(
        type=mtype,
        src=raw["src"],
        dst=raw["dst"],
        id=raw.get("id"),
        ref=raw.get("ref"),
        row=raw.get("row"),
        spot=raw.get("spot"),
        attempt=raw.get("attempt"),
        step=raw.get("step"),
        code=raw.get("code"),
        params=params if isinstance(params, dict) else {"_bad": params},
        t=raw.get("t"),
    )
    validate(msg)
    return msg
