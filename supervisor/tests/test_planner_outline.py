"""The planner on a drawn roof outline (L, U, staircase and so on), not just a rectangle."""
import unittest

from roofbot.planner import IN, PatternVariant, RoofSpec, board_size_mm, plan

FT = 12 * IN
RECT = [(0, 0), (8, 0), (8, 24), (0, 24)]
L_SHAPE = [(0, 0), (8, 0), (8, 8), (4, 8), (4, 24), (0, 24)]
SHAPE_T = [(8, 0), (16, 0), (16, 16), (24, 16), (24, 24), (0, 24), (0, 16), (8, 16)]
U_SHAPE = [(0, 0), (12, 0), (12, 24), (8, 24), (8, 8), (4, 8), (4, 24), (0, 24)]


def spec(points_ft, variant=PatternVariant.DEMO, **kw):
    return RoofSpec.from_outline([(x * FT, y * FT) for x, y in points_ft], variant, **kw)


class Outline(unittest.TestCase):
    def test_a_rectangle_outline_matches_the_rectangle_planner(self):
        a = plan(RoofSpec(8 * FT, 24 * FT, PatternVariant.DEMO))
        b = plan(spec(RECT))
        self.assertEqual([(w.x_mm, w.y_mm, w.heading_deg) for w in a.waypoints],
                         [(w.x_mm, w.y_mm, w.heading_deg) for w in b.waypoints])
        self.assertEqual([r.entry_y_mm for r in a.rows], [r.entry_y_mm for r in b.rows])
        self.assertEqual(b.warnings, ())

    def test_from_outline_moves_the_shape_to_the_origin(self):
        s = RoofSpec.from_outline([(100, 50), (900, 50), (900, 700), (100, 700)])
        self.assertEqual(s.outline[0], (0.0, 0.0))
        self.assertEqual((s.width_mm, s.length_mm), (800.0, 650.0))

    def test_l_shape_keeps_four_boards_and_drops_the_notch(self):
        lay = plan(spec(L_SHAPE))
        self.assertEqual(len(lay.boards), 4)
        self.assertEqual([len(r.spots) for r in lay.rows], [6, 6, 2, 2])
        self.assertEqual(lay.warnings, ())

    def test_u_shape_leaves_the_gap_between_the_arms_empty(self):
        lay = plan(spec(U_SHAPE))
        self.assertEqual(len(lay.boards), 7)
        # the cavity is x 4..8 ft, y 8..24 ft: no board may start there
        self.assertFalse([b for b in lay.boards if 4 * FT - 1 <= b[0] < 8 * FT - 1 and b[1] >= 8 * FT - 1])
        self.assertEqual([len(r.spots) for r in lay.rows], [6, 6, 2, 2, 6, 6])

    def test_every_row_stays_inside_its_stretch_of_the_roof(self):
        lay = plan(spec(U_SHAPE))
        for r in lay.rows:
            lo, hi = sorted((r.spots[0].y_mm, r.exit_y_mm))
            self.assertTrue(all(lo <= s.y_mm <= hi for s in r.spots))
            self.assertAlmostEqual(abs(r.distances_mm()[0]), abs(r.spots[0].y_mm - r.entry_y_mm))

    def test_setback_keeps_boards_away_from_the_edge(self):
        lay = plan(spec(RECT, setback_mm=FT))
        self.assertEqual(len(lay.boards), 2)
        for bx, by in lay.boards:
            bw, bl = board_size_mm(PatternVariant.DEMO)
            self.assertGreaterEqual(bx, FT - 1e-6)
            self.assertLessEqual(bx + bw, 8 * FT - FT + 1e-6)
            self.assertGreaterEqual(by, FT - 1e-6)
            self.assertLessEqual(by + bl, 24 * FT - FT + 1e-6)

    def test_a_turn_that_leaves_the_roof_is_warned_about(self):
        # the T: going from the bar to the stem, the turn level is not on the stem
        lay = plan(spec(SHAPE_T))
        self.assertTrue(any("does not stay on the roof" in w for w in lay.warnings))

    def test_turns_happen_beside_the_last_spot_even_on_a_drawn_shape(self):
        lay = plan(spec(L_SHAPE))
        for a, b in zip(lay.rows, lay.rows[1:]):
            self.assertEqual(b.entry_y_mm, a.spots[-1].y_mm)

    def test_pitch_snapping_still_works_on_an_outline(self):
        lay = plan(spec(L_SHAPE, flute_pitch_mm=6 * IN))
        self.assertTrue(all(abs(w.crest_offset_mm) < 1e-6 for w in lay.waypoints))
        self.assertIsNotNone(lay.rows[0].crests_to_next)


class BadOutlines(unittest.TestCase):
    def test_fewer_than_three_corners(self):
        with self.assertRaisesRegex(ValueError, "at least 3"):
            RoofSpec.from_outline([(0, 0), (5, 5)])

    def test_a_shape_with_no_area(self):
        with self.assertRaisesRegex(ValueError, "no area"):
            RoofSpec.from_outline([(0, 0), (5, 0), (10, 0)])

    def test_a_shape_that_crosses_itself(self):
        with self.assertRaisesRegex(ValueError, "crosses itself"):
            RoofSpec.from_outline([(0, 0), (8, 0), (0, 8), (8, 8)])

    def test_repeating_the_first_corner_to_close_the_shape_is_fine(self):
        s = RoofSpec.from_outline(RECT + [RECT[0]])
        self.assertEqual(len(s.outline), 4)

    def test_roof_too_small_for_a_board(self):
        with self.assertRaisesRegex(ValueError, "too small"):
            plan(spec([(0, 0), (2, 0), (2, 2), (0, 2)]))

    def test_no_whole_board_fits_in_a_diamond(self):
        with self.assertRaisesRegex(ValueError, "no whole board"):
            plan(spec([(8, 0), (16, 8), (8, 16), (0, 8)]))

    def test_an_outline_not_at_the_origin_is_refused_by_plan(self):
        s = RoofSpec(8 * FT, 24 * FT, PatternVariant.DEMO, outline=((FT, FT), (8 * FT, FT), (8 * FT, 24 * FT)))
        with self.assertRaises(ValueError):
            plan(s)


if __name__ == "__main__":
    unittest.main()
