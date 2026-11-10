"""The localization model: how accurately Locomotion's cross-track control stops at each spot."""
import math
import random
import re
import unittest
from dataclasses import replace
from pathlib import Path

from roofbot.localization import (LocalizationParams, analyse, lateral_variance_after, settling, simulate_drive,
                                  start_covariance)
from roofbot.planner import IN, PatternVariant, RoofSpec, plan

CONFIG_H = Path(__file__).resolve().parents[2] / "firmware" / "esp32" / "include" / "config.h"


def firmware_constant(name: str) -> float:
    text = CONFIG_H.read_text(encoding="utf-8")
    m = re.search(rf"#define\s+{name}\s+([-\d.]+)f?\b", text)
    assert m, f"{name} not found in config.h"
    return float(m.group(1))


class KeptEqualToTheFirmware(unittest.TestCase):
    """The model analyses the loop the firmware runs. If someone retunes one and not the other, this fails."""

    def test_the_control_gains_match_config_h(self):
        p = LocalizationParams()
        self.assertAlmostEqual(p.kp, firmware_constant("CROSS_TRACK_KP"))
        self.assertAlmostEqual(p.kd, firmware_constant("CROSS_TRACK_KD"))
        self.assertAlmostEqual(p.filter_alpha, firmware_constant("CROSS_TRACK_FILTER"))
        self.assertAlmostEqual(p.steer_max, firmware_constant("STEER_MAX"))
        self.assertAlmostEqual(p.control_dt_s * 1000.0, firmware_constant("STEER_PERIOD_MS"))
        self.assertAlmostEqual(p.lateral_tolerance_mm, firmware_constant("LATERAL_TOLERANCE_MM"))

    def test_the_fine_positioning_settings_match_config_h(self):
        p = LocalizationParams()
        self.assertAlmostEqual(p.align_accept_mm, firmware_constant("ALIGN_ACCEPT_MM"))
        self.assertEqual(p.max_align_attempts, int(firmware_constant("ALIGN_MAX_ATTEMPTS")))
        self.assertEqual(p.align_samples, int(firmware_constant("ALIGN_SAMPLES")))


class LateralLoop(unittest.TestCase):
    def test_the_loop_is_stable_and_settles_below_the_starting_error(self):
        p = LocalizationParams()
        steady, distance = settling(p)
        self.assertLess(steady, p.start_lateral_sigma_mm)
        self.assertTrue(0 < distance < 5000)

    def test_the_covariance_recursion_agrees_with_a_random_simulation(self):
        p = replace(LocalizationParams(), start_lateral_sigma_mm=0.5, start_heading_sigma_deg=0.2)
        steps = int(1800 / p.speed_mm_s / p.control_dt_s)
        analytic = math.sqrt(lateral_variance_after(p, steps, start_covariance(p))[0][0])
        rng = random.Random(7)
        ys = [simulate_drive(p, 1800, rng)[0] for _ in range(250)]
        mean = sum(ys) / len(ys)
        sd = math.sqrt(sum((y - mean) ** 2 for y in ys) / (len(ys) - 1))
        self.assertAlmostEqual(sd / analytic, 1.0, delta=0.2)

    def test_more_sensor_noise_or_heading_drift_means_a_worse_residual(self):
        base = settling(LocalizationParams())[0]
        self.assertGreater(settling(replace(LocalizationParams(), array_noise_mm=0.5))[0], base)
        self.assertGreater(settling(replace(LocalizationParams(), heading_walk_deg_per_sqrt_s=0.3))[0], base)

    def test_without_noise_or_drift_the_loop_pulls_the_error_to_nothing(self):
        p = replace(LocalizationParams(), array_noise_mm=0.0, heading_walk_deg_per_sqrt_s=0.0)
        self.assertLess(settling(p)[0], 1e-3)   # under a micrometre

    def test_holding_the_steering_straight_lets_the_error_grow_with_the_heading(self):
        p = LocalizationParams()
        steps = int(1000 / p.speed_mm_s / p.control_dt_s)
        controlled = lateral_variance_after(p, steps, start_covariance(p), controlled=True)[0][0]
        straight = lateral_variance_after(p, steps, start_covariance(p), controlled=False)[0][0]
        self.assertGreater(straight, controlled)


class OverALayout(unittest.TestCase):
    def setUp(self):
        self.layout = plan(RoofSpec(1219.2, 7315.2, PatternVariant.DEMO))     # 4 x 24 ft, 12 spots

    def test_every_spot_has_an_entry_in_driving_order(self):
        r = analyse(self.layout)
        self.assertEqual(len(r.spots), self.layout.total_spots)
        self.assertEqual([(s.row, s.spot) for s in r.spots], [(w.row, w.spot) for w in self.layout.waypoints])

    def test_without_fine_positioning_a_spot_with_no_distance_to_settle_keeps_the_turns_sideways_error(self):
        r = analyse(self.layout, replace(LocalizationParams(), fine_positioning=False))
        first_of_row_two = next(s for s in r.spots if (s.row, s.spot) == (2, 1))   # a zero-length drive
        self.assertGreater(first_of_row_two.lateral_sigma_mm, 4.0)
        self.assertTrue(any("settle after a turn" in n for n in r.notes))
        self.assertFalse(r.achievable)

    def test_with_a_small_turn_error_the_placeholders_meet_the_tolerance(self):
        r = analyse(self.layout, replace(LocalizationParams(), start_lateral_sigma_mm=0.01, fine_positioning=False))
        self.assertTrue(r.achievable)
        self.assertEqual(r.dominant_lateral_term, "array to drill offset")

    def test_along_errors_pile_up_unless_the_firmware_carries_them_over(self):
        as_built = analyse(self.layout, LocalizationParams(along_compensates=False))
        carried = analyse(self.layout, LocalizationParams(along_compensates=True))
        row1 = lambda rep: [s.along_mean_mm for s in rep.spots if s.row == 1]    # noqa: E731
        self.assertGreater(row1(as_built)[-1], row1(as_built)[0] * 3)
        self.assertAlmostEqual(row1(carried)[-1], row1(carried)[0])

    def test_reversing_is_mentioned(self):
        lay = plan(RoofSpec(1219.2, 2438.4, PatternVariant.FIVE, turn_style="last-spot"))   # reverses there
        self.assertTrue(any("reverse" in n for n in analyse(lay).notes))

    def test_crest_miscounts_are_listed_per_row_change(self):
        lay = plan(RoofSpec(1219.2, 2438.4, PatternVariant.EIGHT, flute_pitch_mm=6 * IN))
        r = analyse(lay)
        self.assertEqual(len(r.turns), len(lay.rows) - 1)
        self.assertAlmostEqual(r.turns[0].miscount_probability, 1 - (1 - 0.001) ** r.turns[0].crests)


class FinePositioning(unittest.TestCase):
    def setUp(self):
        self.layout = plan(RoofSpec(1219.2, 7315.2, PatternVariant.DEMO))

    def test_nudging_brings_the_spot_after_a_turn_inside_the_tolerance(self):
        off = analyse(self.layout, replace(LocalizationParams(), fine_positioning=False))
        on = analyse(self.layout)
        after_turn = lambda rep: next(s for s in rep.spots if (s.row, s.spot) == (2, 1))   # noqa: E731
        self.assertGreater(after_turn(off).lateral_sigma_mm, 4.0)
        self.assertLess(after_turn(on).lateral_sigma_mm, 0.5)
        self.assertGreater(after_turn(on).lateral_within_tol, 0.95)
        self.assertFalse(off.achievable)
        self.assertTrue(on.achievable)

    def test_the_spot_after_a_turn_expects_about_a_nudge_and_a_settled_spot_hardly_any(self):
        r = analyse(self.layout)
        after_turn = next(s for s in r.spots if (s.row, s.spot) == (2, 1))
        settled = next(s for s in r.spots if (s.row, s.spot) == (1, 3))
        self.assertGreater(after_turn.nudges_expected, 0.5)
        self.assertLess(settled.nudges_expected, 0.3)
        self.assertGreater(r.nudge_time_s, 0)

    def test_averaging_readings_makes_running_out_of_tries_rarer(self):
        one = analyse(self.layout, replace(LocalizationParams(), align_samples=1)).worst_p_not_aligned
        eight = analyse(self.layout).worst_p_not_aligned
        self.assertGreater(one, eight * 5)

    def test_too_few_tries_makes_not_aligned_likely_and_the_plan_not_achievable(self):
        r = analyse(self.layout, replace(LocalizationParams(), max_align_attempts=0))
        self.assertGreater(r.worst_p_not_aligned, 0.5)
        self.assertFalse(r.achievable)

    def test_the_result_does_not_change_between_runs(self):
        a = analyse(self.layout).worst.lateral_sigma_mm
        b = analyse(self.layout).worst.lateral_sigma_mm
        self.assertEqual(a, b)

    def test_the_note_explains_where_it_nudges(self):
        self.assertTrue(any("fine positioning nudges" in n for n in analyse(self.layout).notes))


if __name__ == "__main__":
    unittest.main()
