"""The detailed subsystem model: each subsystem walks through its own flowchart."""
import unittest

from roofbot.detail import FLOWS, FLOW_FAULTS
from roofbot.messages import FaultCode, MsgType, Step
from roofbot.route import Route, RowPlan
from roofbot.sim import SimWorld, fault, refill, silent
from roofbot.supervisor import State


def make_world(rows=((1, 300.0, 100.0),)) -> SimWorld:
    route = Route([RowPlan(spots=s, spacing_mm=sp, start_offset_mm=off) for s, sp, off in rows])
    return SimWorld(route, detailed=True)


class FlowDefinitions(unittest.TestCase):
    def test_every_edge_points_at_a_real_node(self):
        for name, nodes in FLOWS.items():
            ids = {n["id"] for n in nodes}
            for n in nodes:
                for target in n["edges"].values():
                    self.assertIn(target, ids, f"{name}.{n['id']} -> {target}")

    def test_each_flow_has_one_start_and_one_done(self):
        for name, nodes in FLOWS.items():
            kinds = [n["kind"] for n in nodes]
            self.assertEqual(kinds.count("start"), 1, name)
            self.assertEqual(kinds.count("ok"), 1, name)

    def test_every_fault_code_has_a_terminal_node(self):
        texts = {name: " ".join(n["text"] for n in nodes if n["kind"] == "bad") for name, nodes in FLOWS.items()}
        for name, codes in FLOW_FAULTS.items():
            for code in codes:
                self.assertIn(code, texts[name])


class HappyPath(unittest.TestCase):
    def test_full_run_completes_in_detail(self):
        w = make_world(rows=((2, 300.0, 100.0), (2, 300.0, 0.0)))
        w.start_run()
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 600))
        self.assertEqual(w.alerts, [])

    def test_drive_follows_the_flowchart(self):
        w = make_world()
        w.start_run()
        w.run_until(lambda: len(w.locomotion.commands) == 1 and w.locomotion.status == "idle", 60)
        v = w.locomotion.visits
        self.assertEqual([k for k in ("start", "beam", "at_spot", "limit_spot", "move", "done") if k in v],
                         ["start", "beam", "at_spot", "limit_spot", "move", "done"])
        self.assertEqual(v["beam"]["count"], 2)
        self.assertEqual(v["at_spot"]["count"], 2)
        self.assertEqual(v["at_spot"]["last"], "yes")
        self.assertEqual(w.locomotion.sensors["encoder_mm"], 100.0)

    def test_supplies_go_down_by_one_per_spot(self):
        w = make_world(rows=((3, 300.0, 100.0),))
        w.start_run()
        w.run_until_state(State.RUN_COMPLETE, 600)
        self.assertEqual(w.plate.sensors["plates_left"], 9)
        self.assertEqual(w.screw.sensors["screws_left"], 9)

    def test_a_step_takes_time_and_shows_progress(self):
        w = make_world()
        w.start_run()
        w.run(0.5)
        d = w.locomotion.detail(w.now)
        self.assertEqual(d["status"], "working")
        self.assertEqual(d["flow"], "DRIVE")
        self.assertNotEqual(d["node"], "done")


class Faults(unittest.TestCase):
    CASES = [
        ("locomotion", Step.DRIVE, FaultCode.OFF_BEAM),
        ("locomotion", Step.DRIVE, FaultCode.CANNOT_REACH_SPOT),
        ("locomotion", Step.TURN, FaultCode.TURN_FAILED),
        ("plate", Step.PLATE, FaultCode.PLATE_NOT_ARRIVED),
        ("plate", Step.PLATE, FaultCode.PLACEMENT_REJECTED),
        ("screw", Step.SCREW, FaultCode.SCREW_NOT_IN_POSITION),
        ("fastening", Step.FASTEN, FaultCode.TORQUE_TIMEOUT),
        ("fastening", Step.FASTEN, FaultCode.PHOTO_REJECTED),
    ]

    def test_each_scripted_fault_reaches_the_operator_as_that_fault(self):
        for node, step, code in self.CASES:
            with self.subTest(code=code.value):
                w = make_world(rows=((1, 300.0, 100.0), (1, 300.0, 100.0)))
                getattr(w, node).queue(step, *[fault(code)] * 3)
                w.start_run()
                self.assertTrue(w.run_until_state(State.WAIT_OPERATOR, 600))
                w.run(0.1)
                self.assertEqual(w.alerts[-1].code, code.value)
                self.assertEqual(len(getattr(w, node).commands_for(step)), 3)

    def test_plate_not_arrived_pushes_again_before_giving_up(self):
        w = make_world()
        w.plate.queue(Step.PLATE, *[fault(FaultCode.PLATE_NOT_ARRIVED)] * 3)
        w.start_run()
        w.run_until_state(State.WAIT_OPERATOR, 600)
        v = w.plate.visits
        self.assertEqual((v["arrived"]["count"], v["push"]["count"]), (3, 2))
        self.assertEqual(v["x_notarrived"]["count"], 1)
        self.assertEqual(w.plate.sensors["plate_position"], "cleared")

    def test_torque_timeout_runs_the_timer_to_10_seconds_and_retracts(self):
        w = make_world()
        w.fastening.queue(Step.FASTEN, *[fault(FaultCode.TORQUE_TIMEOUT)] * 3)
        w.start_run()
        w.run_until_state(State.WAIT_OPERATOR, 600)
        self.assertAlmostEqual(w.fastening.sensors["timer_s"], 10.0, places=1)
        self.assertEqual(w.fastening.sensors["drill"], "retracted")
        self.assertGreaterEqual(w.fastening.visits["limit_torque"]["count"], 3)

    def test_subsystem_is_in_a_safe_state_when_it_reports_a_fault(self):
        w = make_world()
        w.locomotion.queue(Step.DRIVE, *[fault(FaultCode.OFF_BEAM)] * 3)
        w.start_run()
        w.run_until_state(State.WAIT_OPERATOR, 600)
        self.assertEqual(w.locomotion.sensors["wheels"], "stopped")

    def test_failing_steps_finish_inside_the_supervisor_timeouts(self):
        # If a failing flowchart ran longer than the Supervisor's timeout, the fault would show
        # up as SUBSYSTEM_UNRESPONSIVE instead. The test above checks the code, this checks the notes.
        for node, step, code in self.CASES:
            w = make_world(rows=((1, 300.0, 100.0), (1, 300.0, 100.0)))
            getattr(w, node).queue(step, fault(code))
            w.start_run()
            w.run_until(lambda: w.supervisor.retries == 1 or w.supervisor.state is State.WAIT_OPERATOR, 600)
            self.assertFalse(any("timeout" in e for e in w.supervisor.events), code.value)


class Supplies(unittest.TestCase):
    def test_empty_hopper_stays_empty_until_the_operator_refills_it(self):
        w = make_world()
        w.plate.queue(Step.PLATE, refill("PLATES"))
        w.start_run()
        w.run_until_state(State.WAIT_OPERATOR, 600)
        w.run(0.1)
        self.assertEqual(w.alerts[-1].code, "NEED_REFILL")
        self.assertEqual(w.plate.sensors["plates_left"], 0)
        # pressing RESOLVED without refilling just stops again
        w.operator(MsgType.RESOLVED)
        w.run_until_state(State.WAIT_OPERATOR, 600)
        w.run(0.1)
        self.assertEqual(len(w.alerts), 2)
        # refilling first makes it work
        w.plate.refill(12)
        w.operator(MsgType.RESOLVED)
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 600))


class SilentAndAbort(unittest.TestCase):
    def test_silent_subsystem_shows_as_silent_then_aborted(self):
        w = make_world()
        w.screw.queue(Step.SCREW, silent())
        w.start_run()
        w.run_until(lambda: w.screw.status == "silent", 600)
        self.assertEqual(w.screw.status, "silent")
        self.assertTrue(w.run_until_state(State.WAIT_OPERATOR, 600))
        w.run(0.1)
        self.assertEqual(w.screw.status, "aborted")

    def test_abort_mid_drive_stops_the_wheels(self):
        w = make_world()
        w.start_run()
        w.run_until(lambda: w.locomotion.sensors["wheels"] == "driving", 30)
        w.operator(MsgType.ESTOP)
        w.run(0.1)
        self.assertEqual(w.locomotion.status, "aborted")
        self.assertEqual(w.locomotion.sensors["wheels"], "stopped")

    def test_estop_retracts_a_drill_that_is_driving(self):
        w = make_world()
        w.start_run()
        w.run_until(lambda: w.fastening.sensors["drill"] == "driving", 120)
        w.operator(MsgType.ESTOP)
        w.run(0.1)
        self.assertEqual(w.fastening.sensors["drill"], "retracted")


if __name__ == "__main__":
    unittest.main()
