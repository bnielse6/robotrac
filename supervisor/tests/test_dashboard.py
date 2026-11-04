"""The dashboard backend, without the web server."""
import json
import unittest

from dashboard import PRESETS, Controller, parse_outcome


class DashboardController(unittest.TestCase):
    def setUp(self):
        self.ctrl = Controller()
        self.ctrl.action({"action": "pause", "value": True})  # we drive the clock by hand

    def tearDown(self):
        self.ctrl.stop()

    def test_snapshot_can_be_turned_into_json(self):
        self.ctrl.action({"action": "reset", "preset": "plate-jam"})
        self.ctrl.action({"action": "step", "seconds": 10})
        json.dumps(self.ctrl.snapshot(include_heartbeats=True))

    def test_happy_preset_runs_to_completion(self):
        self.ctrl.action({"action": "reset", "preset": "happy", "rows": 2, "spots": 2})
        self.ctrl.action({"action": "step", "seconds": 60})
        self.assertEqual(self.ctrl.snapshot()["state"], "RUN_COMPLETE")

    def test_every_preset_loads(self):
        for name in PRESETS:
            self.ctrl.action({"action": "reset", "preset": name})
            self.ctrl.action({"action": "step", "seconds": 5})
            self.ctrl.snapshot()

    def test_plate_jam_preset_stops_and_resolved_finishes(self):
        self.ctrl.action({"action": "reset", "preset": "plate-jam", "rows": 1, "spots": 1})
        self.ctrl.action({"action": "step", "seconds": 20})
        self.assertEqual(self.ctrl.snapshot()["state"], "WAIT_OPERATOR")
        self.ctrl.action({"action": "operator", "type": "RESOLVED"})
        self.ctrl.action({"action": "step", "seconds": 20})
        self.assertEqual(self.ctrl.snapshot()["state"], "RUN_COMPLETE")

    def test_inject_shows_up_in_the_queue(self):
        self.ctrl.action({"action": "inject", "node": "plate", "step": "PLATE",
                          "outcomes": ["FAULT:PLACEMENT_REJECTED", "SILENT"]})
        script = self.ctrl.snapshot()["stubs"]["plate"]["script"]
        self.assertEqual(script, {"PLATE": ["FAULT:PLACEMENT_REJECTED", "SILENT"]})

    def test_bad_input_is_an_error_not_a_crash(self):
        with self.assertRaises(Exception):
            self.ctrl.action({"action": "inject", "node": "plate", "step": "PLATE", "outcomes": ["NOPE"]})
        with self.assertRaises(Exception):
            parse_outcome("FAULT:NOT_A_CODE")


if __name__ == "__main__":
    unittest.main()
