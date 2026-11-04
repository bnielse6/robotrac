"""Run a simulated roof and print what happened.

    python run_sim.py happy
    python run_sim.py plate-jam
    python run_sim.py refill
    python run_sim.py camera
    python run_sim.py estop
"""
import argparse

from roofbot.messages import FaultCode, MsgType, Step
from roofbot.route import Route, RowPlan
from roofbot.sim import SimWorld, fault, refill
from roofbot.supervisor import State

QUIET = {MsgType.HEARTBEAT}


def new_world() -> SimWorld:
    return SimWorld(Route([RowPlan(3, 300.0, 100.0), RowPlan(3, 300.0, 0.0)]))


def show(world: SimWorld) -> None:
    for t, m in world.trace:
        if m.type in QUIET:
            continue
        where = f"r{m.row} s{m.spot}" if m.row else "     "
        extra = m.step or m.code or ""
        print(f"{t:7.2f}s  {m.src:>10} -> {m.dst:<10} {m.type.value:<11} {where}  {extra}")
    s = world.supervisor
    print(f"\nfinal state: {s.state.value}   position: row {s.row} spot {s.spot}")
    for rec in s.fault_log:
        print(f"fault: row {rec.row} spot {rec.spot} {rec.subsystem} {rec.code} -> {rec.action}")


def happy(w):
    w.start_run()
    w.run_until_state(State.RUN_COMPLETE)


def plate_jam(w):
    w.plate.queue(Step.PLATE, *[fault(FaultCode.PLATE_NOT_ARRIVED)] * 3)
    w.start_run()
    w.run_until_state(State.WAIT_OPERATOR)
    w.run(1.0)
    print("operator fixes the jam and presses RESOLVED\n")
    w.operator(MsgType.RESOLVED)
    w.run_until_state(State.RUN_COMPLETE)


def refill_case(w):
    w.screw.queue(Step.SCREW, refill("SCREWS"))
    w.start_run()
    w.run_until_state(State.WAIT_OPERATOR)
    w.run(1.0)
    w.operator(MsgType.RESOLVED)
    w.run_until_state(State.RUN_COMPLETE)


def camera_case(w):
    w.start_run()
    w.run(1.0)
    w.camera.ok = False
    w.run_until_state(State.WAIT_OPERATOR)
    w.run(1.0)
    w.camera.ok = True
    w.run(1.0)
    w.operator(MsgType.RESOLVED)
    w.run_until_state(State.RUN_COMPLETE)


def estop_case(w):
    w.start_run()
    w.run(2.0)
    w.operator(MsgType.ESTOP)
    w.run(1.0)


SCENARIOS = {"happy": happy, "plate-jam": plate_jam, "refill": refill_case,
             "camera": camera_case, "estop": estop_case}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=SCENARIOS)
    args = parser.parse_args()
    world = new_world()
    SCENARIOS[args.scenario](world)
    show(world)
