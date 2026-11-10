"""The dashboard's roof-plan tab: plan a roof and run the planned route in the simulator."""
import unittest

from dashboard import Controller
from roofbot.planner import IN
from roofbot.messages import Step
from roofbot.supervisor import State

DEMO = {"variant": "demo", "width_mm": 48 * IN, "length_mm": 288 * IN, "setback_mm": 0, "pitch_mm": None}


class RoofPlanTab(unittest.TestCase):
    def setUp(self):
        self.ctrl = Controller()
        self.ctrl.paused = True            # the test advances the simulation itself
        self.addCleanup(self.ctrl.stop)

    def test_preview_returns_a_drawing_and_leaves_the_simulation_alone(self):
        before = self.ctrl.world
        r = self.ctrl.preview_plan(DEMO)
        self.assertIn("<svg", r["svg"])
        self.assertEqual((r["spots"], r["rows"], r["boards"]), (12, 2, 3))
        self.assertIs(self.ctrl.world, before)
        self.assertIsNone(self.ctrl.snapshot()["plan"])

    def test_run_replaces_the_world_with_the_planned_route(self):
        self.ctrl.run_plan(DEMO)
        snap = self.ctrl.snapshot()
        self.assertEqual(snap["route"], [6, 6])
        self.assertEqual(snap["plan"]["variant"], "demo")
        self.assertTrue(self.ctrl.world.run_until_state(State.RUN_COMPLETE, 900))
        self.assertEqual(self.ctrl.world.alerts, [])

    def test_a_roof_too_small_for_one_board_is_an_error(self):
        with self.assertRaises(ValueError):
            self.ctrl.preview_plan({**DEMO, "width_mm": 10, "length_mm": 10})

    def test_a_normal_scenario_clears_the_plan(self):
        self.ctrl.run_plan(DEMO)
        self.ctrl.action({"action": "reset", "preset": "manual"})
        self.assertIsNone(self.ctrl.snapshot()["plan"])


class DrawnShape(unittest.TestCase):
    L_SHAPE_MM = [[x * 12 * IN, y * 12 * IN] for x, y in [(0, 0), (8, 0), (8, 8), (4, 8), (4, 24), (0, 24)]]

    def setUp(self):
        self.ctrl = Controller()
        self.ctrl.paused = True
        self.addCleanup(self.ctrl.stop)
        self.req = {"variant": "demo", "setback_mm": 0, "pitch_mm": None, "outline_mm": self.L_SHAPE_MM}

    def test_preview_of_a_drawn_shape(self):
        r = self.ctrl.preview_plan(self.req)
        self.assertEqual((r["spots"], r["rows"], r["boards"], r["warnings"]), (16, 4, 4, []))
        self.assertIn("clipPath", r["svg"])

    def test_run_a_drawn_shape_and_report_it_as_the_running_plan(self):
        self.ctrl.run_plan(self.req)
        for node in ("plate", "screw"):     # the simulated hoppers hold 12, and this roof has 16 spots
            self.ctrl.action({"action": "refill", "node": node, "count": 50})
        snap = self.ctrl.snapshot()
        self.assertEqual(snap["route"], [6, 6, 2, 2])
        self.assertEqual(snap["plan"]["outline_mm"], self.L_SHAPE_MM)
        self.assertTrue(self.ctrl.world.run_until_state(State.RUN_COMPLETE, 1500))
        self.assertEqual(self.ctrl.world.alerts, [])

    def test_a_bad_outline_is_an_error(self):
        with self.assertRaises(ValueError):
            self.ctrl.preview_plan({**self.req, "outline_mm": [[0, 0], [1, 1], [2, 2]]})


class ImportedSchematic(unittest.TestCase):
    def setUp(self):
        from roofbot.schematic import schematic_to_svg
        from roofbot.shapes import shape_outline_mm
        self.ctrl = Controller()
        self.ctrl.paused = True
        self.addCleanup(self.ctrl.stop)
        self.crests = [i * 6 * IN for i in range(17)]
        self.svg = schematic_to_svg(shape_outline_mm("L"), self.crests)

    def test_a_file_is_read_into_an_outline_and_crest_positions(self):
        r = self.ctrl.read_schematic({"text": self.svg, "format": "svg"})
        self.assertEqual(len(r["outline_mm"]), 6)
        self.assertEqual(len(r["crest_xs_mm"]), 17)
        self.assertAlmostEqual(r["pitch_mm"], 6 * IN, delta=0.5)

    def test_a_bad_file_is_an_error_with_a_reason(self):
        with self.assertRaisesRegex(ValueError, "valid SVG"):
            self.ctrl.read_schematic({"text": "not a drawing", "format": "svg"})

    def test_the_crest_positions_reach_the_plan_and_the_picture(self):
        r = self.ctrl.read_schematic({"text": self.svg})
        req = {"variant": "demo", "setback_mm": 0, "pitch_mm": None,
               "outline_mm": r["outline_mm"], "crest_xs_mm": r["crest_xs_mm"]}
        out = self.ctrl.preview_plan(req)
        self.assertEqual((out["spots"], out["boards"]), (16, 4))
        self.assertEqual(out["svg"].count('class="flute"'), 17)
        self.ctrl.run_plan(req)
        self.assertEqual(self.ctrl.snapshot()["plan"]["crest_xs_mm"], r["crest_xs_mm"])
        # the robot is told how many crests to cross at each row change
        self.ctrl.action({"action": "refill", "node": "plate", "count": 40})
        self.ctrl.action({"action": "refill", "node": "screw", "count": 40})
        self.assertTrue(self.ctrl.world.run_until_state(State.RUN_COMPLETE, 1500))
        turns = self.ctrl.world.locomotion.commands_for(Step.TURN)
        self.assertTrue(turns and all("crests" in m.params and "distance_mm" in m.params for m in turns))


class AccuracyCard(unittest.TestCase):
    def setUp(self):
        self.ctrl = Controller()
        self.ctrl.paused = True
        self.addCleanup(self.ctrl.stop)
        self.req = {"variant": "demo", "setback_mm": 0, "pitch_mm": None, "width_mm": 48 * IN, "length_mm": 288 * IN}

    def test_the_estimate_comes_back_with_both_directions(self):
        r = self.ctrl.estimate_accuracy(self.req)
        self.assertEqual(r["spots"], 12)
        self.assertIn("fraction_meeting_lateral", r)
        self.assertIn("as_built", r["along"])
        self.assertIn("carried", r["along"])
        self.assertTrue(r["notes"])      # the demo has spots straight after a turn

    def test_the_knobs_change_the_answer(self):
        base = self.ctrl.estimate_accuracy(self.req)
        no_nudge = self.ctrl.estimate_accuracy({**self.req, "params": {"fine_positioning": 0}})
        quiet = self.ctrl.estimate_accuracy({**self.req, "params": {"fine_positioning": 0, "start_lateral_sigma_mm": 0.01}})
        self.assertTrue(base["achievable"])          # stop-and-nudge on
        self.assertFalse(no_nudge["achievable"])     # the turn's sideways error stays
        self.assertTrue(quiet["achievable"])
        self.assertGreater(base["expected_nudges"], 0)
        self.assertEqual(no_nudge["expected_nudges"], 0)

    def test_unknown_knobs_are_ignored(self):
        r = self.ctrl.estimate_accuracy({**self.req, "params": {"kp": 99, "array_noise_mm": 0.3}})
        self.assertEqual(r["params"]["kp"], 0.08)         # the firmware's gain cannot be changed from here
        self.assertEqual(r["params"]["array_noise_mm"], 0.3)


class StripEnds(unittest.TestCase):
    def setUp(self):
        self.ctrl = Controller()
        self.ctrl.paused = True
        self.addCleanup(self.ctrl.stop)
        self.req = {"variant": "five", "setback_mm": 0, "pitch_mm": None, "width_mm": 48 * IN, "length_mm": 96 * IN}

    def test_by_default_strips_run_on_and_nothing_reverses(self):
        r = self.ctrl.preview_plan(self.req)
        self.assertEqual(r["warnings"], [])
        self.assertNotIn('class="reverse"', r["svg"])
        self.ctrl.run_plan(self.req)
        for node in ("plate", "screw"):
            self.ctrl.action({"action": "refill", "node": node, "count": 20})
        self.assertTrue(self.ctrl.world.run_until_state(State.RUN_COMPLETE, 900))
        drives = [m.params["distance_mm"] for m in self.ctrl.world.locomotion.commands_for(Step.DRIVE)]
        self.assertTrue(all(d >= 0 for d in drives))
        self.assertEqual(self.ctrl.snapshot()["plan"]["turn_style"], "run-out")

    def test_turning_at_the_last_screw_is_still_available(self):
        r = self.ctrl.preview_plan({**self.req, "turn_style": "last-spot"})
        self.assertIn('class="reverse"', r["svg"])

    def test_a_bad_style_is_an_error(self):
        with self.assertRaises(ValueError):
            self.ctrl.preview_plan({**self.req, "turn_style": "diagonal"})
