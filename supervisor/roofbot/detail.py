"""Detailed subsystem model: each subsystem walks through its own flowchart (S1 to S5).

The outside is the same as the simple stub: one CMD_START in, exactly one
DONE / FAULT / NEED_REFILL out, and CMD_ABORT stops it. The difference is the
inside. While a step runs, the subsystem visits the nodes of its flowchart in
order, with a duration for each, and its sensors change as it goes. The
dashboard draws that.

The scripted outcome (done, fault(code), refill(item), silent) decides which
branch of the flowchart is taken.

Times are in simulated seconds. They are placeholders, not measurements,
except the 10 s torque limit from the guide.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Optional

from .messages import FaultCode, Message, MsgType, Node, Step
from .sim import Outcome, StubSubsystem

CHECK_S = 0.25          # a sensor or camera check
OVERSHOOT_DEMO_MM = 60.0  # how far past the spot a scripted OVERSHOT_SPOT rolls. Placeholder
ALIGN_ACCEPT_MM = 0.2   # stop-and-nudge: at the spot the sideways error must be within this (firmware ALIGN_ACCEPT_MM)
ALIGN_MAX_TRIES = 3     # nudges before NOT_ALIGNED (firmware ALIGN_MAX_ATTEMPTS)
NUDGE_S = 1.5           # time for one nudge. Placeholder
NUDGE_RESIDUAL_MM = 0.1  # sideways error left after a nudge. Placeholder
START_LATERAL_SIGMA_MM = 3.0   # how far off the crest the robot is first put down. Placeholder
TURN_LATERAL_SIGMA_MM = 3.0    # the sideways error a turn leaves. Placeholder
SETTLE_MM = 200.0       # driving that cuts the sideways error to 1/e of what it was. Placeholder
TORQUE_LIMIT_S = 10.0   # from the guide
TORQUE_TARGET_NM = 4.0  # placeholder
SUPPLY_FULL = 12


# ---------------------------------------------------------------- flowcharts


def _n(node_id: str, kind: str, text: str, **edges: str) -> dict:
    return {"id": node_id, "kind": kind, "text": text, "edges": edges}


# kind: start, act, check, ok, bad. edges: next, yes, no (ids of other nodes)
FLOWS: dict[str, list[dict]] = {
    "DRIVE": [
        _n("start", "start", "CMD_START: drive to the next spot", next="crest"),
        _n("crest", "check", "On the crest? (crest sensors)", yes="at_spot", no="limit_crest"),
        _n("limit_crest", "check", "Time limit used up?", yes="x_off_crest", no="relocate"),
        _n("relocate", "act", "Relocate to the crest", next="crest"),
        _n("at_spot", "check", "At the right spot? (encoder + route map)", yes="over", no="limit_spot"),
        _n("over", "check", "Past the spot by more than the limit? (encoder)", yes="x_overshot", no="aligned"),
        _n("aligned", "check", "Sideways error within the limit? (crest sensors)", yes="done", no="limit_align"),
        _n("limit_align", "check", "Tried too many times?", yes="x_not_aligned", no="nudge"),
        _n("nudge", "act", "Nudge sideways by the error", next="aligned"),
        _n("limit_spot", "check", "Time limit used up?", yes="x_cannot_reach", no="move"),
        _n("move", "act", "Keep moving to the spot", next="crest"),
        _n("done", "ok", "DONE: stop at the spot"),
        _n("x_off_crest", "bad", "FAULT: OFF_CREST (wheels stop)"),
        _n("x_cannot_reach", "bad", "FAULT: CANNOT_REACH_SPOT (wheels stop)"),
        _n("x_overshot", "bad", "FAULT: OVERSHOT_SPOT (wheels stop, no retry)"),
        _n("x_not_aligned", "bad", "FAULT: NOT_ALIGNED (wheels stop)"),
    ],
    "TURN": [
        _n("start", "start", "CMD_START: turn to the next row", next="run_out"),
        _n("run_out", "act", "Drive on to the turn point (run-out), if the route map has one", next="t90a"),
        _n("t90a", "check", "Turned 90? (encoder)", yes="drive_fwd", no="turn1"),
        _n("turn1", "act", "Turn", next="t90a"),
        _n("drive_fwd", "act", "Drive forward", next="front"),
        _n("front", "check", "Crossed the planned number of crests? (front sensor)", yes="enc", no="limit_turn"),
        _n("limit_turn", "check", "Distance or time limit used up?", yes="x_turn", no="front"),
        _n("enc", "check", "Encoder agrees with the planned row gap?", yes="t90b", no="limit_turn"),
        _n("t90b", "check", "Turned 90 again? (encoder)", yes="done", no="turn2"),
        _n("turn2", "act", "Turn", next="t90b"),
        _n("done", "ok", "DONE: facing the other way on the next crest"),
        _n("x_turn", "bad", "FAULT: TURN_FAILED (wheels stop)"),
    ],
    "PLATE": [
        _n("start", "start", "CMD_START: place a plate", next="supply"),
        _n("supply", "check", "Plates available?", yes="feed", no="x_refill"),
        _n("feed", "act", "Feed the plate toward fastening position", next="arrived"),
        _n("arrived", "check", "Live camera: did the plate arrive?", yes="release", no="limit_plate"),
        _n("limit_plate", "check", "Time limit used up?", yes="x_notarrived", no="push"),
        _n("push", "act", "Push the plate again", next="arrived"),
        _n("release", "act", "Release the plate", next="approve"),
        _n("approve", "check", "Live camera + tripwire approve the placement?", yes="done", no="x_rejected"),
        _n("done", "ok", "DONE"),
        _n("x_refill", "bad", "NEED_REFILL: plates"),
        _n("x_notarrived", "bad", "FAULT: PLATE_NOT_ARRIVED (feed stopped, plate clear)"),
        _n("x_rejected", "bad", "FAULT: PLACEMENT_REJECTED (plate released and clear)"),
    ],
    "SCREW": [
        _n("start", "start", "CMD_START: load a screw", next="supply"),
        _n("supply", "check", "Screws available?", yes="load", no="x_refill"),
        _n("load", "act", "Load the screw into fastening position", next="both"),
        _n("both", "check", "Live camera sees plate and screw together, both in the right spot?",
           yes="done", no="x_notinpos"),
        _n("done", "ok", "DONE: ready to fasten"),
        _n("x_refill", "bad", "NEED_REFILL: screws"),
        _n("x_notinpos", "bad", "FAULT: SCREW_NOT_IN_POSITION (missing or not lined up)"),
    ],
    "FASTEN": [
        _n("start", "start", "CMD_START: fasten the screw", next="drill"),
        _n("drill", "act", "Drill the screw in", next="torque"),
        _n("torque", "check", "Right torque? (torque sensor)", yes="photo", no="limit_torque"),
        _n("limit_torque", "check", "10 second limit used up?", yes="retract_t", no="keep"),
        _n("keep", "act", "Keep screwing", next="torque"),
        _n("photo", "act", "Live camera takes a photo", next="accepted"),
        _n("accepted", "check", "Photo accepted?", yes="retract_ok", no="retract_p"),
        _n("retract_ok", "act", "Retract the drill (safe to move)", next="done"),
        _n("retract_p", "act", "Retract the drill (safe to move)", next="x_photo"),
        _n("retract_t", "act", "Retract the drill (safe to move)", next="x_torque"),
        _n("done", "ok", "DONE"),
        _n("x_torque", "bad", "FAULT: TORQUE_TIMEOUT"),
        _n("x_photo", "bad", "FAULT: PHOTO_REJECTED"),
    ],
}

# Which fault codes each flow can produce.
FLOW_FAULTS = {
    "DRIVE": {"OFF_CREST", "CANNOT_REACH_SPOT", "OVERSHOT_SPOT", "NOT_ALIGNED"},
    "TURN": {"TURN_FAILED"},
    "PLATE": {"PLATE_NOT_ARRIVED", "PLACEMENT_REJECTED"},
    "SCREW": {"SCREW_NOT_IN_POSITION"},
    "FASTEN": {"TORQUE_TIMEOUT", "PHOTO_REJECTED"},
}

INITIAL_SENSORS = {
    "LOCOMOTION": {"crest_sensors": "on crest", "front_sensor": "not on a crest", "encoder_mm": 0.0,
                   "target_mm": 0.0, "lateral_mm": 0.0, "heading_deg": 0, "wheels": "stopped"},
    "PLATE": {"plates_left": SUPPLY_FULL, "plate_position": "in hopper", "plate_x": 0.0,
              "camera_sees_plate": False, "tripwire": "idle"},
    "SCREW": {"screws_left": SUPPLY_FULL, "screw_position": "in magazine", "camera_sees_both": False},
    "FASTENING": {"drill": "retracted", "drill_depth": 0.0, "torque_nm": 0.0,
                  "torque_target_nm": TORQUE_TARGET_NM, "timer_s": 0.0, "limit_s": TORQUE_LIMIT_S,
                  "photo": "none"},
}


# ---------------------------------------------------------------- phases


@dataclass
class Phase:
    node: str
    duration: float
    result: Optional[str] = None  # "yes" or "no" for a check
    note: str = ""
    sets: dict = field(default_factory=dict)    # sensor values applied when the phase starts
    ramps: dict = field(default_factory=dict)   # sensor -> (from, to), moves smoothly over the phase


def P(node, duration, result=None, note="", sets=None, ramps=None) -> Phase:
    return Phase(node, duration, result, note, sets or {}, ramps or {})


# (kind, payload): ("DONE", None), ("FAULT", code), ("REFILL", item)
Final = tuple


class ProcessSubsystem(StubSubsystem):
    """A StubSubsystem that runs its flowchart in detail. Same outside, richer inside."""

    def __init__(self, node: Node, response_time_s: float = 0.2):
        super().__init__(node, response_time_s)
        self.sensors: dict = dict(INITIAL_SENSORS[node.value])
        self.status = "idle"          # idle, working, silent, aborted
        self.last_result: Optional[str] = None
        self.flow: Optional[str] = None
        self.current_node: Optional[str] = None
        self.note = ""
        self.visits: dict[str, dict] = {}
        self.path: list[dict] = []
        self._phases: Optional[list[Phase]] = None
        self._idx = 0
        self._t0 = 0.0
        self._cmd: Optional[Message] = None
        self._final: Final = ("DONE", None)
        self._effect: Optional[Callable[[], None]] = None
        self._done_params: Optional[dict] = None   # extra fields on the DONE (Locomotion: lateral_mm)
        # Locomotion only: how far off the crest centre the robot is now (mm, positive = right)
        self._lateral_mm = random.Random(1).gauss(0.0, START_LATERAL_SIGMA_MM)

    # ---- the outside: same contract as StubSubsystem

    def on_message(self, msg: Message, now: float) -> None:
        if msg.type is MsgType.CMD_ABORT:
            self.aborts.append(msg)
            if self._phases is not None or self.status == "silent":
                self._phases = None
                self.status = "aborted"
                self.note = "Aborted by the Supervisor. Moved to the safe state."
                self._make_safe()
        elif msg.type is MsgType.CMD_START:
            self.commands.append(msg)
            steps = self.script.get(Step(msg.step))
            outcome = steps.popleft() if steps else Outcome("DONE")
            self._begin(msg, outcome, now)

    def tick(self, now: float) -> list[Message]:
        replies: list[Message] = []
        while self._phases is not None:
            phase = self._phases[self._idx]
            end = self._t0 + phase.duration
            if now < end:
                self._apply_ramps(phase, (now - self._t0) / phase.duration)
                break
            self._apply_ramps(phase, 1.0)
            self.path.append({"t": round(end, 2), "node": phase.node, "result": phase.result})
            self.visits[phase.node]["last"] = phase.result
            self._idx += 1
            if self._idx >= len(self._phases):
                replies.append(self._finish())
                break
            self._t0 = end
            self._start_phase(self._phases[self._idx])
        return replies

    # ---- for the dashboard

    def refill(self, count: int = SUPPLY_FULL) -> None:
        key = self._supply_key()
        if key:
            self.sensors[key] = count

    def detail(self, now: float) -> dict:
        progress = 0.0
        if self._phases is not None:
            phase = self._phases[self._idx]
            progress = max(0.0, min(1.0, (now - self._t0) / phase.duration))
        sensors = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in self.sensors.items()}
        if "heading_deg" in sensors:
            sensors["heading_deg"] = round(self.sensors["heading_deg"]) % 360
        return {
            "flow": self.flow,
            "node": self.current_node,
            "status": self.status,
            "note": self.note,
            "progress": round(progress, 3),
            "visits": {k: dict(v) for k, v in self.visits.items()},
            "path": self.path[-14:],
            "sensors": sensors,
            "supply_key": self._supply_key(),
            "last_result": self.last_result,
        }

    # ---- running a step

    def _supply_key(self) -> Optional[str]:
        return {"PLATE": "plates_left", "SCREW": "screws_left"}.get(self.node.value)

    def _begin(self, msg: Message, outcome: Outcome, now: float) -> None:
        self._cmd = msg
        self.flow = msg.step
        self.visits = {}
        self.path = []
        self.last_result = None
        self._effect = None
        self._done_params = None
        if outcome.kind == "SILENT":
            self._phases = None
            self.status = "silent"
            self.current_node = "start"
            self.visits["start"] = {"count": 1, "last": None}
            self.note = "Received the command and stopped responding"
            return
        phases, final, effect = self._build(msg, outcome)
        self._phases, self._final, self._effect = phases, final, effect
        self._idx = 0
        self._t0 = now
        self.status = "working"
        self._start_phase(phases[0])

    def _start_phase(self, phase: Phase) -> None:
        self.current_node = phase.node
        self.note = phase.note
        self.sensors.update(phase.sets)
        entry = self.visits.setdefault(phase.node, {"count": 0, "last": None})
        entry["count"] += 1
        entry["last"] = None

    def _apply_ramps(self, phase: Phase, p: float) -> None:
        for key, (a, b) in phase.ramps.items():
            self.sensors[key] = a + (b - a) * p

    def _finish(self) -> Message:
        kind, payload = self._final
        self._phases = None
        self.status = "idle"
        if kind == "DONE":
            if self._effect:
                self._effect()
            outcome = Outcome("DONE", params=self._done_params)
            self.last_result = "DONE"
        elif kind == "REFILL":
            outcome = Outcome("REFILL", item=payload)
            self.last_result = f"NEED_REFILL {payload}"
        else:
            outcome = Outcome("FAULT", code=payload)
            self.last_result = f"FAULT {payload.value}"
        return self._reply(self._cmd, outcome)

    def _make_safe(self) -> None:
        s = self.sensors
        name = self.node.value
        if name == "LOCOMOTION":
            s["wheels"] = "stopped"
        elif name == "FASTENING":
            s["drill"] = "retracted"
            s["drill_depth"] = 0.0
        elif name == "PLATE" and s["plate_position"] == "being fed":
            s["plate_position"] = "cleared"
            s["plate_x"] = 0.0

    # ---- building the path through each flowchart

    def _build(self, msg: Message, outcome: Outcome):
        step = msg.step
        code = outcome.code.value if outcome.kind == "FAULT" else None
        if code is not None and code not in FLOW_FAULTS[step]:
            return self._unknown_fault(step, outcome.code)
        if outcome.kind == "REFILL" and self._supply_key():
            self.sensors[self._supply_key()] = 0  # the hopper is empty. The operator must refill it.
        build = {"DRIVE": self._drive, "TURN": self._turn, "PLATE": self._plate,
                 "SCREW": self._screw, "FASTEN": self._fasten}[step]
        return build(msg, code)

    def _unknown_fault(self, step: str, code: FaultCode):
        """A fault code that this flowchart cannot produce. Fail right after the start."""
        bad = next(n["id"] for n in FLOWS[step] if n["kind"] == "bad")
        phases = [P("start", 0.1, note="Starting"),
                  P(bad, 0.2, note=f"Reporting {code.value}")]
        return phases, ("FAULT", code), None

    # S1: drive straight
    def _drive(self, msg: Message, code: Optional[str]):
        signed = float(msg.params.get("distance_mm", 300.0))   # negative means reverse
        dist = abs(signed)
        reverse = signed < 0
        moving = "reversing" if reverse else "driving"
        move_s = max(0.8, min(dist / 200.0, 3.0))
        phases = [P("start", 0.1, note=f"{'Reverse' if reverse else 'Drive'} {dist:.0f} mm to the next spot",
                    sets={"encoder_mm": 0.0, "target_mm": dist, "wheels": "stopped"})]
        if code == "OFF_CREST":
            for i in range(3):
                phases.append(P("crest", CHECK_S, "no", "Crest sensors: NOT on the crest",
                                sets={"crest_sensors": "OFF CREST", "wheels": "stopped"}))
                last = i == 2
                phases.append(P("limit_crest", CHECK_S, "yes" if last else "no",
                                "Time limit used up, stopping" if last else "Time limit not used up"))
                if not last:
                    phases.append(P("relocate", 0.6, note="Trying to find the crest again",
                                    sets={"wheels": "relocating"}))
            phases.append(P("x_off_crest", 0.2, note="Wheels stopped. Reporting OFF_CREST",
                            sets={"wheels": "stopped"}))
            return phases, ("FAULT", FaultCode.OFF_CREST), None
        on_crest = {"crest_sensors": "on crest"}
        # where the sideways error stands when it stops: the steering pulls it in with distance
        lat_pre = (self._lateral_mm * math.exp(-dist / SETTLE_MM)
                   + random.Random(msg.row * 100 + msg.spot + 7).gauss(0.0, 0.1))
        if dist <= 0:
            phases += [P("crest", CHECK_S, "yes", "Crest sensors: on the crest", sets=on_crest),
                       P("at_spot", CHECK_S, "yes", "Already at the spot"),
                       P("over", CHECK_S, "no", "Encoder: not past the spot")]
            return self._align(msg, phases, lat_pre, code)
        if code == "OVERSHOT_SPOT":
            past = dist + OVERSHOOT_DEMO_MM   # the robot rolls on past the spot
            phases += [P("crest", CHECK_S, "yes", "Crest sensors: on the crest", sets=on_crest),
                       P("at_spot", CHECK_S, "no", f"Encoder: 0 of {dist:.0f} mm, not there yet"),
                       P("limit_spot", CHECK_S, "no", "Time limit not used up"),
                       P("move", move_s, note="Driving to the spot", sets={"wheels": moving},
                         ramps={"encoder_mm": (0.0, past)}),
                       P("crest", CHECK_S, "yes", "Crest sensors: on the crest", sets=on_crest),
                       P("at_spot", CHECK_S, "yes", "Encoder: at the spot, stopping the wheels",
                         sets={"wheels": "stopped"}),
                       P("over", CHECK_S, "yes", f"Encoder: {OVERSHOOT_DEMO_MM:.0f} mm past the spot"),
                       P("x_overshot", 0.2, note="Wheels stopped. Reporting OVERSHOT_SPOT")]
            return phases, ("FAULT", FaultCode.OVERSHOT_SPOT), None
        if code == "CANNOT_REACH_SPOT":
            reached = 0.0
            for fraction in (0.7, 0.85):
                phases += [P("crest", CHECK_S, "yes", "Crest sensors: on the crest", sets=on_crest),
                           P("at_spot", CHECK_S, "no", "Encoder: not at the spot yet"),
                           P("limit_spot", CHECK_S, "no", "Time limit not used up")]
                phases.append(P("move", move_s * 0.6, note="Moving, but falling short",
                                sets={"wheels": moving},
                                ramps={"encoder_mm": (reached, dist * fraction)}))
                reached = dist * fraction
            phases += [P("crest", CHECK_S, "yes", "Crest sensors: on the crest", sets=on_crest),
                       P("at_spot", CHECK_S, "no", "Encoder: still short of the spot"),
                       P("limit_spot", CHECK_S, "yes", "Time limit used up, stopping"),
                       P("x_cannot_reach", 0.2, note="Wheels stopped. Reporting CANNOT_REACH_SPOT",
                         sets={"wheels": "stopped"})]
            return phases, ("FAULT", FaultCode.CANNOT_REACH_SPOT), None
        phases += [P("crest", CHECK_S, "yes", "Crest sensors: on the crest", sets=on_crest),
                   P("at_spot", CHECK_S, "no", f"Encoder: 0 of {dist:.0f} mm, not there yet"),
                   P("limit_spot", CHECK_S, "no", "Time limit not used up"),
                   P("move", move_s, note="Driving to the spot", sets={"wheels": moving},
                     ramps={"encoder_mm": (0.0, dist)}),
                   P("crest", CHECK_S, "yes", "Crest sensors: on the crest", sets=on_crest),
                   P("at_spot", CHECK_S, "yes", "Encoder: at the right spot", sets={"wheels": "stopped"}),
                   P("over", CHECK_S, "no", "Encoder: not past the spot")]
        return self._align(msg, phases, lat_pre, code)

    def _align(self, msg: Message, phases: list, lat_pre: float, code: Optional[str]):
        """The stop-and-nudge step at the spot: check the sideways error, nudge it out, check again.

        `lat_pre` is the sideways error when the robot stopped. A scripted NOT_ALIGNED makes every
        nudge fail, so it runs out of tries.
        """
        rng = random.Random(msg.row * 100 + msg.spot)
        lat, tries = lat_pre, 0
        while True:
            ok = abs(lat) <= ALIGN_ACCEPT_MM and code != "NOT_ALIGNED"
            phases.append(P("aligned", CHECK_S, "yes" if ok else "no",
                            f"Crest sensors: sideways error {lat:+.2f} mm, "
                            + ("within the limit" if ok else f"outside {ALIGN_ACCEPT_MM} mm"),
                            sets={"lateral_mm": round(lat, 2)}))
            if ok:
                break
            last = tries >= ALIGN_MAX_TRIES
            phases.append(P("limit_align", CHECK_S, "yes" if last else "no",
                            "Tried too many times, stopping" if last else "Not tried too many times yet"))
            if last:
                phases.append(P("x_not_aligned", 0.2, note="Wheels stopped. Reporting NOT_ALIGNED",
                                sets={"wheels": "stopped"}))
                return phases, ("FAULT", FaultCode.NOT_ALIGNED), None
            phases.append(P("nudge", NUDGE_S, note=f"Nudging {abs(lat):.1f} mm {'left' if lat > 0 else 'right'}",
                            sets={"wheels": "nudging"}))
            lat = lat * 0.95 if code == "NOT_ALIGNED" else rng.gauss(0.0, NUDGE_RESIDUAL_MM)
            tries += 1
        phases.append(P("done", 0.1, note="Stopped at the spot", sets={"wheels": "stopped"}))

        def remember() -> None:     # runs when the DONE is sent
            self._lateral_mm = lat
            self._done_params = {"lateral_mm": round(lat, 2)}
        return phases, ("DONE", None), remember

    # S2: turn to the next row
    def _turn(self, msg: Message, code: Optional[str]):
        sign = 90 if msg.params.get("direction", "RIGHT") == "RIGHT" else -90
        h0 = self._heading_now()
        crests = int(msg.params.get("crests", 0))            # crests to cross, 0 when the route map does not say
        shift = float(msg.params.get("distance_mm", 0.0))    # the sideways gap to the next row
        across = (f"{crests} crests, {shift:.0f} mm" if crests and shift else
                  f"{crests} crests" if crests else f"{shift:.0f} mm" if shift else "")
        drive_s = max(0.8, min(shift / 200.0, 3.0)) if shift else 0.8
        run_out = float(msg.params.get("run_out_mm", 0.0))   # drive on past the last spot before turning
        phases = [P("start", 0.1, note=f"Turn {msg.params.get('direction', 'RIGHT')} twice onto the next crest",
                    sets={"front_sensor": "not on a crest", "wheels": "stopped"}),
                  *([P("run_out", max(0.8, min(run_out / 200.0, 3.0)),
                       note=f"Driving on {run_out:.0f} mm past the last spot, to the turn point",
                       sets={"wheels": "driving", "encoder_mm": 0.0}, ramps={"encoder_mm": (0.0, run_out)}),
                    P("t90a", CHECK_S, "no", "Wheels stopped at the turn point", sets={"wheels": "stopped"})]
                    if run_out > 0 else []),
                  P("t90a", CHECK_S, "no", "Encoder: not turned yet"),
                  P("turn1", 1.0, note="Turning 90", sets={"wheels": "turning"},
                    ramps={"heading_deg": (h0, h0 + sign)}),
                  P("t90a", CHECK_S, "yes", "Encoder: turned 90"),
                  P("drive_fwd", drive_s,
                    note="Driving forward toward the next crest" + (f" ({across})" if across else ""),
                    sets={"wheels": "driving", "encoder_mm": 0.0},
                    ramps={"encoder_mm": (0.0, shift)} if shift else {})]
        if code == "TURN_FAILED":
            for i in range(3):
                phases.append(P("front", CHECK_S, "no", "Front sensor: not on the next crest"))
                last = i == 2
                phases.append(P("limit_turn", 0.5, "yes" if last else "no",
                                "Limit used up, stopping" if last else "Not used up, keep driving"))
            phases.append(P("x_turn", 0.2, note="Wheels stopped. Reporting TURN_FAILED",
                            sets={"wheels": "stopped"}))
            return phases, ("FAULT", FaultCode.TURN_FAILED), None
        phases += [P("front", CHECK_S, "no", "Front sensor: not on the next crest yet"),
                   P("limit_turn", 0.5, "no", "Limit not used up, keep driving"),
                   P("front", CHECK_S, "yes", "Front sensor: on the next crest", sets={"front_sensor": "ON NEXT CREST"}),
                   P("enc", CHECK_S, "yes",
                     f"Encoder agrees with the route map: {shift:.0f} mm" if shift else "Encoder position approved"),
                   P("t90b", CHECK_S, "no", "Encoder: second turn not done yet", sets={"wheels": "stopped"}),
                   P("turn2", 1.0, note="Turning 90 again", sets={"wheels": "turning"},
                     ramps={"heading_deg": (h0 + sign, h0 + 2 * sign)}),
                   P("t90b", CHECK_S, "yes", "Encoder: turned 90 again", sets={"wheels": "stopped"}),
                   P("done", 0.1, note="Facing the other way on the next crest")]

        def after_turn() -> None:   # the turn leaves the robot a little off the new crest
            self._lateral_mm = random.Random(msg.row * 100 + 3).gauss(0.0, TURN_LATERAL_SIGMA_MM)
        return phases, ("DONE", None), after_turn

    def _heading_now(self) -> float:
        return float(self.sensors["heading_deg"])

    # S3: plate
    def _plate(self, msg: Message, code: Optional[str]):
        s = self.sensors
        s.update({"plate_position": "in hopper", "plate_x": 0.0, "camera_sees_plate": False, "tripwire": "idle"})
        left = s["plates_left"]
        phases = [P("start", 0.1, note="Placing a plate")]
        if left <= 0:
            phases += [P("supply", CHECK_S, "no", "Plate sensors: no plates left"),
                       P("x_refill", 0.2, note="Reporting NEED_REFILL plates")]
            return phases, ("REFILL", "PLATES"), None
        phases += [P("supply", CHECK_S, "yes", f"Plate sensors: {int(left)} plates left"),
                   P("feed", 0.8, note="Feeding the plate toward fastening position",
                     sets={"plate_position": "being fed"},
                     ramps={"plate_x": (0.0, 0.6 if code == "PLATE_NOT_ARRIVED" else 1.0)})]
        if code == "PLATE_NOT_ARRIVED":
            for i in range(3):
                phases.append(P("arrived", 0.3, "no", "Camera: no plate in fastening position",
                                sets={"camera_sees_plate": False}))
                last = i == 2
                phases.append(P("limit_plate", CHECK_S, "yes" if last else "no",
                                "Time limit used up, stopping the feed" if last else "Time limit not used up"))
                if not last:
                    phases.append(P("push", 0.6, note="Pushing the plate again",
                                    ramps={"plate_x": (0.6 + 0.05 * i, 0.65 + 0.05 * i)}))
            phases.append(P("x_notarrived", 0.3, note="Feed stopped, plate cleared. Reporting PLATE_NOT_ARRIVED",
                            sets={"plate_position": "cleared", "plate_x": 0.0}))
            return phases, ("FAULT", FaultCode.PLATE_NOT_ARRIVED), None
        phases += [P("arrived", 0.3, "yes", "Camera: plate has arrived",
                     sets={"camera_sees_plate": True, "plate_position": "at position"}),
                   P("release", 0.5, note="Releasing the plate", sets={"plate_position": "released"})]
        if code == "PLACEMENT_REJECTED":
            phases += [P("approve", 0.3, "no", "Camera + tripwire: placement NOT approved",
                         sets={"tripwire": "nothing detected"}),
                       P("x_rejected", 0.3, note="Plate released and cleared. Reporting PLACEMENT_REJECTED",
                         sets={"plate_position": "cleared", "plate_x": 0.0, "camera_sees_plate": False})]
            return phases, ("FAULT", FaultCode.PLACEMENT_REJECTED), None
        phases += [P("approve", 0.3, "yes", "Camera + tripwire: placement approved",
                     sets={"tripwire": "plate detected"}),
                   P("done", 0.1, note="Plate placed")]
        return phases, ("DONE", None), lambda: s.update({"plates_left": s["plates_left"] - 1})

    # S4: screw
    def _screw(self, msg: Message, code: Optional[str]):
        s = self.sensors
        s.update({"screw_position": "in magazine", "camera_sees_both": False})
        left = s["screws_left"]
        phases = [P("start", 0.1, note="Loading a screw")]
        if left <= 0:
            phases += [P("supply", CHECK_S, "no", "Screw sensor: no screws left"),
                       P("x_refill", 0.2, note="Reporting NEED_REFILL screws")]
            return phases, ("REFILL", "SCREWS"), None
        phases += [P("supply", CHECK_S, "yes", f"Screw sensor: {int(left)} screws left"),
                   P("load", 0.8, note="Loading the screw into fastening position",
                     sets={"screw_position": "loading"})]
        if code == "SCREW_NOT_IN_POSITION":
            phases += [P("both", 0.4, "no", "Camera: screw missing or not lined up with the plate",
                         sets={"camera_sees_both": False, "screw_position": "not aligned"}),
                       P("x_notinpos", 0.3, note="Reporting SCREW_NOT_IN_POSITION",
                         sets={"screw_position": "cleared"})]
            return phases, ("FAULT", FaultCode.SCREW_NOT_IN_POSITION), None
        phases += [P("both", 0.4, "yes", "Camera: plate and screw both in the right spot",
                     sets={"camera_sees_both": True, "screw_position": "loaded"}),
                   P("done", 0.1, note="Ready to fasten")]
        return phases, ("DONE", None), lambda: s.update({"screws_left": s["screws_left"] - 1})

    # S5: fastening
    def _fasten(self, msg: Message, code: Optional[str]):
        target = TORQUE_TARGET_NM
        s = self.sensors
        s.update({"drill": "retracted", "drill_depth": 0.0, "torque_nm": 0.0, "timer_s": 0.0, "photo": "none"})
        phases = [P("start", 0.1, note="Fastening the screw")]
        if code == "TORQUE_TIMEOUT":
            t = 1.5
            phases.append(P("drill", 1.5, note="Drilling the screw in", sets={"drill": "driving"},
                            ramps={"drill_depth": (0.0, 1.0), "torque_nm": (0.0, 1.5), "timer_s": (0.0, t)}))
            keeps = [2.8, 2.8]
            i = 0
            while True:
                t_end = t + 0.1
                phases.append(P("torque", 0.1, "no", "Torque sensor: torque not reached",
                                ramps={"timer_s": (t, t_end)}))
                t = t_end
                if t >= TORQUE_LIMIT_S - 1e-9:
                    phases.append(P("limit_torque", 0.1, "yes", "10 second limit used up",
                                    sets={"timer_s": TORQUE_LIMIT_S}))
                    break
                t_end = t + 0.1
                phases.append(P("limit_torque", 0.1, "no", "10 second limit not used up",
                                ramps={"timer_s": (t, t_end)}))
                t = t_end
                if i < len(keeps):
                    k = keeps[i]
                else:
                    k = max(0.1, TORQUE_LIMIT_S - t - 0.1)  # runs the timer up to the limit
                i += 1
                phases.append(P("keep", k, note="Keep screwing", ramps={"timer_s": (t, t + k)}))
                t += k
            phases += [P("retract_t", 0.4, note="Retracting the drill (safe to move)",
                         sets={"drill": "retracting"}, ramps={"drill_depth": (1.0, 0.0)}),
                       P("x_torque", 0.1, note="Drill retracted. Reporting TORQUE_TIMEOUT",
                         sets={"drill": "retracted", "torque_nm": 0.0})]
            return phases, ("FAULT", FaultCode.TORQUE_TIMEOUT), None
        phases += [P("drill", 1.5, note="Drilling the screw in", sets={"drill": "driving"},
                     ramps={"drill_depth": (0.0, 1.0), "torque_nm": (0.0, target * 0.9), "timer_s": (0.0, 1.5)}),
                   P("torque", CHECK_S, "yes", "Torque sensor: right torque reached",
                     sets={"torque_nm": target}),
                   P("photo", 0.4, note="Camera taking a photo of the screw", sets={"photo": "taking"})]
        if code == "PHOTO_REJECTED":
            phases += [P("accepted", CHECK_S, "no", "Photo NOT accepted", sets={"photo": "rejected"}),
                       P("retract_p", 0.4, note="Retracting the drill (safe to move)",
                         sets={"drill": "retracting"}, ramps={"drill_depth": (1.0, 0.0)}),
                       P("x_photo", 0.1, note="Drill retracted. Reporting PHOTO_REJECTED",
                         sets={"drill": "retracted", "torque_nm": 0.0})]
            return phases, ("FAULT", FaultCode.PHOTO_REJECTED), None
        phases += [P("accepted", CHECK_S, "yes", "Photo accepted", sets={"photo": "accepted"}),
                   P("retract_ok", 0.4, note="Retracting the drill (safe to move)",
                     sets={"drill": "retracting"}, ramps={"drill_depth": (1.0, 0.0)}),
                   P("done", 0.1, note="Screw fastened", sets={"drill": "retracted", "torque_nm": 0.0})]
        return phases, ("DONE", None), None
