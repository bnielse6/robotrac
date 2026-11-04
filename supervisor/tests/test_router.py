"""CameraService, the QUERY and ANSWER messages, and the Router that connects everything on the Pi."""
import unittest

from roofbot.camera_service import CameraService
from roofbot.messages import Message, MessageError, MsgType, Node, decode, encode
from roofbot.route import Route, RowPlan
from roofbot.router import Router
from roofbot.supervisor import State


def query(question="PLATE_ARRIVED", qid=1, src=Node.PLATE):
    return Message(MsgType.QUERY, src, Node.CAMERA, id=qid, row=1, spot=1, params={"question": question})


class QueryAnswerMessages(unittest.TestCase):
    def test_query_round_trip(self):
        back = decode(encode(query()))
        self.assertEqual((back.type, back.id, back.params["question"]), (MsgType.QUERY, 1, "PLATE_ARRIVED"))

    def test_query_needs_a_known_question(self):
        with self.assertRaises(MessageError):
            encode(query("IS_IT_RAINING"))

    def test_answer_needs_a_boolean(self):
        with self.assertRaises(MessageError):
            encode(Message(MsgType.ANSWER, Node.CAMERA, Node.PLATE, ref=1, params={"ok": "yes"}))
        line = encode(Message(MsgType.ANSWER, Node.CAMERA, Node.PLATE, ref=1, params={"ok": True}))
        self.assertTrue(decode(line).params["ok"])


class Camera(unittest.TestCase):
    def test_default_answers_yes_and_echoes_the_query_id(self):
        ans = CameraService().handle(query(qid=7))
        self.assertEqual((ans.type, ans.ref, ans.dst, ans.params["ok"]), (MsgType.ANSWER, 7, "PLATE", True))

    def test_scripted_answers_are_used_first(self):
        cam = CameraService().queue("PLATE_ARRIVED", False, False)
        got = [cam.handle(query(qid=i)).params["ok"] for i in range(3)]
        self.assertEqual(got, [False, False, True])

    def test_decide_function_is_used_when_nothing_is_scripted(self):
        cam = CameraService(decide=lambda question, q: question == "PHOTO_OK")
        self.assertFalse(cam.handle(query("PLATE_ARRIVED")).params["ok"])
        self.assertTrue(cam.handle(query("PHOTO_OK")).params["ok"])


class RouterBehaviour(unittest.TestCase):
    def setUp(self):
        self.to_link = []
        self.alerts = []
        self.camera_ok = True
        self.router = Router(Route([RowPlan(1, 300.0, 100.0)]), send_to_link=self.to_link.append,
                             on_alert=self.alerts.append, camera_ok=lambda: self.camera_ok)
        self.now = 0.0

    def tick(self, seconds):
        end = self.now + seconds
        while self.now < end:
            self.now += 0.05
            self.router.tick(self.now)

    def commands(self):
        return [m for m in self.to_link if m.type is MsgType.CMD_START]

    def test_start_sends_a_command_to_the_link(self):
        self.tick(0.3)
        self.router.on_operator(MsgType.START, self.now)
        cmds = self.commands()
        self.assertEqual([(c.dst, c.step) for c in cmds], [("LOCOMOTION", "DRIVE")])

    def test_done_from_the_link_moves_on(self):
        self.tick(0.3)
        self.router.on_operator(MsgType.START, self.now)
        first = self.commands()[0]
        self.router.on_link_message(Message(MsgType.DONE, Node.LOCOMOTION, Node.SUPERVISOR, ref=first.id), self.now)
        self.assertEqual(self.router.supervisor.state, State.PLATE)
        self.assertEqual(self.commands()[-1].dst, "PLATE")

    def test_query_from_the_link_is_answered_and_not_given_to_the_supervisor(self):
        self.router.on_link_message(query(), self.now)
        answers = [m for m in self.to_link if m.type is MsgType.ANSWER]
        self.assertEqual(len(answers), 1)
        self.assertEqual(self.router.supervisor.events, [])

    def test_alerts_go_to_the_operator_not_the_link(self):
        self.tick(0.3)
        self.router.on_operator(MsgType.START, self.now)
        self.router.on_operator(MsgType.ESTOP, self.now)
        self.router.on_operator(MsgType.START, self.now)  # refused in ESTOP, no alert
        self.camera_ok = False
        self.router.on_operator(MsgType.RESET, self.now)
        self.tick(1.5)
        self.router.on_operator(MsgType.START, self.now)
        self.assertEqual(self.alerts[-1].code, "CAMERA_FEED_LOST")
        self.assertNotIn(MsgType.ALERT, [m.type for m in self.to_link])

    def test_heartbeats_reach_the_link(self):
        self.tick(1.2)
        beats = [m for m in self.to_link if m.type is MsgType.HEARTBEAT]
        self.assertGreaterEqual(len(beats), 2)

    def test_estop_aborts_all_four_subsystems_on_the_link(self):
        self.tick(0.3)
        self.router.on_operator(MsgType.START, self.now)
        self.router.on_operator(MsgType.ESTOP, self.now)
        aborted = {m.dst for m in self.to_link if m.type is MsgType.CMD_ABORT}
        self.assertEqual(aborted, {"LOCOMOTION", "PLATE", "SCREW", "FASTENING"})


if __name__ == "__main__":
    unittest.main()
