import json
import unittest

from roofbot.messages import (FaultCode, MAX_LINE_BYTES, Message, MessageError, MsgType, Node, Step,
                              decode, encode)
from roofbot.serial_link import LineFramer


class RoundTrip(unittest.TestCase):
    def test_cmd_start_round_trip(self):
        msg = Message(MsgType.CMD_START, Node.SUPERVISOR, Node.PLATE, id=7, row=2, spot=3, attempt=1,
                      step=Step.PLATE, params={"distance_mm": 300.0})
        line = encode(msg)
        self.assertTrue(line.endswith(b"\n"))
        back = decode(line.strip())
        self.assertEqual(back.type, MsgType.CMD_START)
        self.assertEqual((back.id, back.row, back.spot, back.attempt), (7, 2, 3, 1))
        self.assertEqual(back.step, "PLATE")
        self.assertEqual(back.params, {"distance_mm": 300.0})

    def test_fault_round_trip(self):
        msg = Message(MsgType.FAULT, Node.PLATE, Node.SUPERVISOR, ref=4, code=FaultCode.PLATE_NOT_ARRIVED)
        back = decode(encode(msg))
        self.assertEqual(back.code, "PLATE_NOT_ARRIVED")
        self.assertEqual(back.ref, 4)

    def test_null_fields_are_left_out(self):
        line = encode(Message(MsgType.HEARTBEAT, Node.SUPERVISOR, Node.ALL))
        self.assertEqual(set(json.loads(line)), {"v", "type", "src", "dst"})


class Rejects(unittest.TestCase):
    def test_not_json(self):
        with self.assertRaises(MessageError):
            decode(b"hello")

    def test_not_an_object(self):
        with self.assertRaises(MessageError):
            decode(b"[1,2]")

    def test_wrong_version(self):
        with self.assertRaises(MessageError):
            decode(b'{"v":2,"type":"START","src":"OPERATOR","dst":"SUP"}')

    def test_unknown_type(self):
        with self.assertRaises(MessageError):
            decode(b'{"v":1,"type":"DANCE","src":"A","dst":"B"}')

    def test_missing_required_field(self):
        with self.assertRaises(MessageError):
            decode(b'{"v":1,"type":"DONE","src":"PLATE","dst":"SUP"}')  # no ref

    def test_unknown_fault_code(self):
        with self.assertRaises(MessageError):
            decode(b'{"v":1,"type":"FAULT","src":"PLATE","dst":"SUP","ref":1,"code":"BOOM"}')

    def test_refill_needs_item(self):
        with self.assertRaises(MessageError):
            decode(b'{"v":1,"type":"NEED_REFILL","src":"PLATE","dst":"SUP","ref":1}')

    def test_integer_fields_must_be_integers(self):
        with self.assertRaises(MessageError):
            decode(b'{"v":1,"type":"DONE","src":"PLATE","dst":"SUP","ref":"1"}')

    def test_line_too_long(self):
        with self.assertRaises(MessageError):
            decode(b" " * (MAX_LINE_BYTES + 1))

    def test_encode_refuses_oversize(self):
        with self.assertRaises(MessageError):
            encode(Message(MsgType.ALERT, Node.SUPERVISOR, Node.OPERATOR, code="X",
                           params={"detail": "x" * MAX_LINE_BYTES}))


class LightMessage(unittest.TestCase):
    def test_round_trip(self):
        msg = Message(MsgType.LIGHT, Node.SUPERVISOR, Node.LIGHT, params={"color": "AMBER", "mode": "FLASH"})
        back = decode(encode(msg))
        self.assertEqual(back.params, {"color": "AMBER", "mode": "FLASH"})
        self.assertEqual(back.dst, "LIGHT")

    def test_needs_a_known_color_and_mode(self):
        for params in ({}, {"color": "BLUE", "mode": "STEADY"}, {"color": "RED"}, {"color": "RED", "mode": "FAST"}):
            with self.assertRaises(MessageError):
                encode(Message(MsgType.LIGHT, Node.SUPERVISOR, Node.LIGHT, params=params))


class Framer(unittest.TestCase):
    def test_partial_chunks(self):
        f = LineFramer()
        self.assertEqual(f.feed(b'{"a":'), [])
        self.assertEqual(f.feed(b'1}\n{"b"'), [b'{"a":1}'])
        self.assertEqual(f.feed(b':2}\n'), [b'{"b":2}'])

    def test_crlf_and_blank_lines(self):
        f = LineFramer()
        self.assertEqual(f.feed(b"one\r\n\r\ntwo\n"), [b"one", b"two"])

    def test_overlong_line_is_dropped_and_framing_recovers(self):
        f = LineFramer(max_line=10)
        lines = f.feed(b"x" * 50 + b"\nok\n")
        self.assertEqual(lines, [b"ok"])
        self.assertEqual(f.dropped, 1)


if __name__ == "__main__":
    unittest.main()
