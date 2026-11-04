"""Supervisor behaviour, one test per rule in the system guide, using the simulator."""
import unittest

from roofbot.messages import FaultCode, Message, MsgType, Node, Step
from roofbot.route import Route, RowPlan
from roofbot.sim import SimWorld, done, fault, refill, silent
from roofbot.supervisor import Config, State


def make_world(rows=((2, 300.0, 100.0), (2, 300.0, 100.0)), **kwargs) -> SimWorld:
    route = Route([RowPlan(spots=s, spacing_mm=sp, start_offset_mm=off) for s, sp, off in rows])
    return SimWorld(route, **kwargs)


def last_alert(world):
    return world.alerts[-1]


class HappyPath(unittest.TestCase):
    def test_full_run_completes(self):
        w = make_world()
        w.start_run()
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 120))
        self.assertEqual(len(w.plate.commands), 4)
        self.assertEqual(len(w.screw.commands), 4)
        self.assertEqual(len(w.fastening.commands), 4)
        self.assertEqual(w.alerts, [])
        self.assertEqual(w.supervisor.fault_log, [])

    def test_order_within_one_spot(self):
        w = make_world(rows=((1, 300.0, 100.0),))
        w.start_run()
        w.run_until_state(State.RUN_COMPLETE, 60)
        cmds = [m.step for _, m in w.trace if m.type is MsgType.CMD_START]
        self.assertEqual(cmds, ["DRIVE", "PLATE", "SCREW", "FASTEN"])

    def test_turns_alternate_and_row_changes(self):
        w = make_world(rows=((1, 300.0, 0.0), (1, 300.0, 0.0), (1, 300.0, 0.0)))
        w.start_run()
        w.run_until_state(State.RUN_COMPLETE, 120)
        turns = [m.params["direction"] for c in [w.locomotion] for m in c.commands_for(Step.TURN)]
        self.assertEqual(turns, ["RIGHT", "LEFT"])
        rows_driven = [m.row for m in w.locomotion.commands_for(Step.DRIVE)]
        self.assertEqual(rows_driven, [1, 2, 3])

    def test_drive_distances_come_from_the_route(self):
        w = make_world(rows=((3, 250.0, 80.0),))
        w.start_run()
        w.run_until_state(State.RUN_COMPLETE, 120)
        distances = [m.params["distance_mm"] for m in w.locomotion.commands_for(Step.DRIVE)]
        self.assertEqual(distances, [80.0, 250.0, 250.0])

    def test_start_is_refused_without_a_camera_feed(self):
        w = make_world()
        w.camera.silent = True
        w.run(0.1)
        w.operator(MsgType.START)
        w.run(0.1)
        self.assertEqual(w.supervisor.state, State.IDLE)
        self.assertEqual(last_alert(w).code, "CAMERA_FEED_LOST")

    def test_supervisor_sends_heartbeats(self):
        w = make_world()
        w.run(2.0)
        beats = [m for _, m in w.trace if m.type is MsgType.HEARTBEAT and m.src == "SUP"]
        self.assertGreaterEqual(len(beats), 3)


class Retries(unittest.TestCase):
    def test_one_failure_is_retried_without_alert(self):
        w = make_world(rows=((1, 300.0, 0.0),))
        w.plate.queue(Step.PLATE, fault(FaultCode.PLATE_NOT_ARRIVED))
        w.start_run()
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 60))
        self.assertEqual([m.attempt for m in w.plate.commands], [1, 2])
        self.assertEqual(w.alerts, [])

    def test_two_failures_still_retry(self):
        w = make_world(rows=((1, 300.0, 0.0),))
        w.fastening.queue(Step.FASTEN, fault(FaultCode.TORQUE_TIMEOUT), fault(FaultCode.TORQUE_TIMEOUT))
        w.start_run()
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 60))
        self.assertEqual([m.attempt for m in w.fastening.commands], [1, 2, 3])

    def test_retries_do_not_carry_over_to_the_next_step(self):
        w = make_world(rows=((1, 300.0, 0.0),))
        w.plate.queue(Step.PLATE, fault(FaultCode.PLATE_NOT_ARRIVED), fault(FaultCode.PLATE_NOT_ARRIVED))
        w.screw.queue(Step.SCREW, fault(FaultCode.SCREW_NOT_IN_POSITION), fault(FaultCode.SCREW_NOT_IN_POSITION))
        w.start_run()
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 60))
        self.assertEqual(w.alerts, [])

    def test_three_failures_stop_and_alert(self):
        w = make_world()
        w.plate.queue(Step.PLATE, *[fault(FaultCode.PLACEMENT_REJECTED)] * 3)
        w.start_run()
        self.assertTrue(w.run_until_state(State.WAIT_OPERATOR, 60))
        w.run(0.1)
        a = last_alert(w)
        self.assertEqual((a.code, a.row, a.spot), ("PLACEMENT_REJECTED", 1, 1))
        self.assertEqual(a.params["subsystem"], "PLATE")
        self.assertTrue(a.params["allow_skip"])
        self.assertEqual(len(w.plate.commands), 3)  # 1 try + N=2 retries, no more

    def test_robot_does_not_move_on_by_itself(self):
        w = make_world()
        w.plate.queue(Step.PLATE, *[fault(FaultCode.PLACEMENT_REJECTED)] * 3)
        w.start_run()
        w.run_until_state(State.WAIT_OPERATOR, 60)
        w.run(60)
        self.assertEqual(w.supervisor.state, State.WAIT_OPERATOR)
        self.assertEqual(len(w.screw.commands), 0)
        self.assertEqual(len(w.locomotion.commands), 1)


class OperatorActions(unittest.TestCase):
    def stopped_at_plate(self):
        w = make_world()
        w.plate.queue(Step.PLATE, *[fault(FaultCode.PLACEMENT_REJECTED)] * 3)
        w.start_run()
        w.run_until_state(State.WAIT_OPERATOR, 60)
        return w

    def test_resolved_resumes_the_same_step_with_fresh_retries(self):
        w = self.stopped_at_plate()
        w.operator(MsgType.RESOLVED)
        self.assertEqual(w.supervisor.state, State.PLATE)
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 120))
        self.assertEqual(w.supervisor.fault_log[0].action, "RESOLVED")
        self.assertEqual(w.plate.commands[3].attempt, 1)

    def test_skip_moves_to_the_row_check_and_is_logged(self):
        w = self.stopped_at_plate()
        w.operator(MsgType.SKIP_SPOT)
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 120))
        self.assertEqual(w.supervisor.skipped_spots, [(1, 1)])
        self.assertEqual(w.supervisor.fault_log[0].action, "SKIPPED")
        self.assertEqual(len(w.screw.commands), 3)  # spot 1 skipped, the other 3 done

    def test_skip_is_refused_for_locomotion_faults(self):
        w = make_world()
        w.locomotion.queue(Step.DRIVE, *[fault(FaultCode.OFF_BEAM)] * 3)
        w.start_run()
        w.run_until_state(State.WAIT_OPERATOR, 60)
        w.operator(MsgType.SKIP_SPOT)
        w.run(0.1)
        self.assertEqual(w.supervisor.state, State.WAIT_OPERATOR)
        self.assertFalse(last_alert(w).params["allow_skip"])
        w.operator(MsgType.RESOLVED)
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 120))

    def test_resolved_and_skip_do_nothing_while_running(self):
        w = make_world()
        w.start_run()
        w.run(0.05)
        before = w.supervisor.state
        w.operator(MsgType.RESOLVED)
        w.operator(MsgType.SKIP_SPOT)
        self.assertEqual(w.supervisor.state, before)

    def test_refill_stops_at_once_without_retry(self):
        w = make_world()
        w.plate.queue(Step.PLATE, refill("PLATES"))
        w.start_run()
        w.run_until_state(State.WAIT_OPERATOR, 60)
        w.run(0.1)
        self.assertEqual(len(w.plate.commands), 1)
        a = last_alert(w)
        self.assertEqual((a.code, a.params["detail"]), ("NEED_REFILL", "PLATES"))
        w.operator(MsgType.RESOLVED)
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 120))
        self.assertEqual(len(w.plate.commands), 5)  # 1 refused + 4 spots

    def test_turn_failure_waits_for_the_operator_and_resumes_the_turn(self):
        w = make_world()
        w.locomotion.queue(Step.TURN, *[fault(FaultCode.TURN_FAILED)] * 3)
        w.start_run()
        self.assertTrue(w.run_until_state(State.WAIT_OPERATOR, 120))
        self.assertEqual(w.supervisor.resume_state, State.TURN_TO_NEXT_ROW)
        w.operator(MsgType.RESOLVED)
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 120))


class Robustness(unittest.TestCase):
    def test_silent_subsystem_times_out_and_is_aborted(self):
        cfg = Config()
        cfg.step_timeout_s[Step.SCREW] = 2.0
        w = make_world(config=cfg)
        w.screw.queue(Step.SCREW, silent())
        w.start_run()
        self.assertTrue(w.run_until_state(State.WAIT_OPERATOR, 60))
        w.run(0.1)
        self.assertEqual(last_alert(w).code, "SUBSYSTEM_UNRESPONSIVE")
        self.assertFalse(last_alert(w).params["allow_skip"])
        self.assertEqual(len(w.screw.aborts), 1)

    def test_stale_reply_is_ignored(self):
        from roofbot.messages import Message
        w = make_world()
        w.start_run()
        w.run(0.05)
        w.operator(MsgType.RESOLVED)  # no-op, just to make sure nothing breaks first
        state = w.supervisor.state
        stale = Message(MsgType.DONE, Node.LOCOMOTION, Node.SUPERVISOR, ref=999)
        w.supervisor.on_message(stale, w.now)
        self.assertEqual(w.supervisor.state, state)

    def test_reply_from_the_wrong_subsystem_is_ignored(self):
        from roofbot.messages import Message
        w = make_world()
        w.start_run()
        w.run(0.05)
        pending_id = w.supervisor.pending.msg_id
        w.supervisor.on_message(Message(MsgType.DONE, Node.PLATE, Node.SUPERVISOR, ref=pending_id), w.now)
        self.assertEqual(w.supervisor.state, State.DRIVE_TO_SPOT)

    def test_subsystem_reboot_mid_step_is_a_fault(self):
        from roofbot.messages import Message
        w = make_world()
        w.start_run()
        w.run(0.05)
        w.supervisor.on_message(Message(MsgType.READY, Node.LOCOMOTION, Node.SUPERVISOR), w.now)
        self.assertEqual(w.supervisor.state, State.WAIT_OPERATOR)
        self.assertEqual(w.supervisor.active_fault.code, "SUBSYSTEM_UNRESPONSIVE")


class CameraFeed(unittest.TestCase):
    def test_bad_image_stops_the_robot_and_aborts_the_active_step(self):
        w = make_world()
        w.start_run()
        w.run(0.05)
        w.camera.ok = False
        self.assertTrue(w.run_until_state(State.WAIT_OPERATOR, 5))
        w.run(0.1)
        a = last_alert(w)
        self.assertEqual((a.code, a.params["subsystem"], a.params["allow_skip"]),
                         ("CAMERA_FEED_LOST", "CAMERA", False))
        self.assertEqual(len(w.locomotion.aborts), 1)

    def test_dead_feed_stops_the_robot(self):
        w = make_world()
        w.start_run()
        w.run(0.05)
        w.camera.silent = True
        self.assertTrue(w.run_until_state(State.WAIT_OPERATOR, 5))

    def test_resolved_is_refused_until_the_feed_is_back(self):
        w = make_world()
        w.start_run()
        w.run(0.05)
        w.camera.ok = False
        w.run_until_state(State.WAIT_OPERATOR, 5)
        w.run(0.5)
        w.operator(MsgType.RESOLVED)
        self.assertEqual(w.supervisor.state, State.WAIT_OPERATOR)
        w.camera.ok = True
        w.run(0.5)
        w.operator(MsgType.RESOLVED)
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 120))

    def test_skip_is_refused_for_camera_faults(self):
        w = make_world()
        w.start_run()
        w.run(0.05)
        w.camera.ok = False
        w.run_until_state(State.WAIT_OPERATOR, 5)
        w.operator(MsgType.SKIP_SPOT)
        self.assertEqual(w.supervisor.state, State.WAIT_OPERATOR)


class EmergencyStop(unittest.TestCase):
    def test_estop_aborts_everything_and_needs_a_reset(self):
        w = make_world()
        w.start_run()
        w.run(0.5)
        w.operator(MsgType.ESTOP)
        w.run(0.1)
        self.assertEqual(w.supervisor.state, State.ESTOP)
        for stub in (w.locomotion, w.plate, w.screw, w.fastening):
            self.assertEqual(len(stub.aborts), 1)
        w.operator(MsgType.START)
        w.operator(MsgType.RESOLVED)
        self.assertEqual(w.supervisor.state, State.ESTOP)
        w.operator(MsgType.RESET)
        self.assertEqual(w.supervisor.state, State.IDLE)

    def test_estop_works_while_waiting_for_the_operator(self):
        w = make_world()
        w.plate.queue(Step.PLATE, *[fault(FaultCode.PLACEMENT_REJECTED)] * 3)
        w.start_run()
        w.run_until_state(State.WAIT_OPERATOR, 60)
        w.operator(MsgType.ESTOP)
        self.assertEqual(w.supervisor.state, State.ESTOP)
        self.assertEqual(w.supervisor.fault_log[0].action, "ESTOP")

    def test_run_restarts_from_the_beginning_after_estop(self):
        w = make_world()
        w.start_run()
        w.run(1.0)
        w.operator(MsgType.ESTOP)
        w.operator(MsgType.RESET)
        w.operator(MsgType.START)
        self.assertEqual((w.supervisor.row, w.supervisor.spot), (1, 1))
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 120))

    def test_a_late_reply_after_estop_does_nothing(self):
        w = make_world()
        w.start_run()
        w.run(0.1)
        w.operator(MsgType.ESTOP)
        w.run(1.0)
        self.assertEqual(w.supervisor.state, State.ESTOP)

    def test_run_complete_returns_to_idle_on_reset(self):
        w = make_world(rows=((1, 300.0, 0.0),))
        w.start_run()
        w.run_until_state(State.RUN_COMPLETE, 60)
        w.operator(MsgType.RESET)
        self.assertEqual(w.supervisor.state, State.IDLE)


class StackLight(unittest.TestCase):
    """The stack light follows the Supervisor state (section 3.8 of the system guide)."""

    def test_idle_then_running_then_complete(self):
        w = make_world(rows=((1, 300.0, 100.0),))
        w.run(0.1)
        self.assertEqual(w.light, ("GREEN", "FLASH"))
        w.operator(MsgType.START)
        w.run(0.1)
        self.assertEqual(w.light, ("GREEN", "STEADY"))
        w.run_until_state(State.RUN_COMPLETE, 60)
        w.run(0.1)
        self.assertEqual(w.light, ("GREEN", "FLASH"))

    def test_waiting_for_the_operator_is_amber_flashing(self):
        w = make_world()
        w.plate.queue(Step.PLATE, *[fault(FaultCode.PLATE_NOT_ARRIVED)] * 3)
        w.start_run()
        w.run_until_state(State.WAIT_OPERATOR, 60)
        w.run(0.1)
        self.assertEqual(w.light, ("AMBER", "FLASH"))
        w.operator(MsgType.RESOLVED)
        w.run(0.1)
        self.assertEqual(w.light, ("GREEN", "STEADY"))

    def test_estop_is_red_and_reset_returns_to_idle_pattern(self):
        w = make_world()
        w.start_run()
        w.run(0.1)
        w.operator(MsgType.ESTOP)
        w.run(0.1)
        self.assertEqual(w.light, ("RED", "STEADY"))
        w.operator(MsgType.RESET)
        w.run(0.1)
        self.assertEqual(w.light, ("GREEN", "FLASH"))

    def test_light_is_sent_only_when_it_changes(self):
        w = make_world(rows=((2, 300.0, 100.0),))
        w.start_run()
        w.run_until_state(State.RUN_COMPLETE, 60)
        sent = [(m.params["color"], m.params["mode"]) for _, m in w.trace if m.type is MsgType.LIGHT]
        self.assertEqual(sent, [("GREEN", "FLASH"), ("GREEN", "STEADY"), ("GREEN", "FLASH")])

    def test_light_is_resent_when_the_board_reboots(self):
        w = make_world()
        w.run(0.1)  # stays in IDLE, so the READY below does not also change the state
        before = len([1 for _, m in w.trace if m.type is MsgType.LIGHT])
        w.supervisor.on_message(Message(MsgType.READY, Node.LOCOMOTION, Node.SUPERVISOR), w.now)
        w.run(0.1)
        after = len([1 for _, m in w.trace if m.type is MsgType.LIGHT])
        self.assertEqual(after, before + 1)


if __name__ == "__main__":
    unittest.main()
