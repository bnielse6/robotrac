import unittest

from roofbot.planner import (BOARD_LENGTH_MM, BOARD_WIDTH_MM, IN, PatternVariant,
                             RoofSpec, board_pattern_mm, plan)

ONE_BOARD = dict(width_mm=BOARD_WIDTH_MM, length_mm=BOARD_LENGTH_MM)


class Pattern(unittest.TestCase):
    def test_five_has_five_and_eight_has_eight(self):
        self.assertEqual(len(board_pattern_mm(PatternVariant.FIVE)), 5)
        self.assertEqual(len(board_pattern_mm(PatternVariant.EIGHT)), 8)

    def test_five_matches_the_spec_sheet(self):
        got = {(round(x / IN), round(y / IN)) for x, y in board_pattern_mm(PatternVariant.FIVE)}
        self.assertEqual(got, {(12, 12), (36, 12), (24, 48), (12, 84), (36, 84)})


class OneBoard(unittest.TestCase):
    def test_five_variant_gives_three_rows_and_five_spots(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.FIVE))
        self.assertEqual(lay.total_spots, 5)
        self.assertEqual([len(r.spots) for r in lay.rows], [2, 1, 2])

    def test_eight_variant_gives_two_rows_of_four(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.EIGHT))
        self.assertEqual([len(r.spots) for r in lay.rows], [4, 4])

    def test_rows_alternate_direction(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.EIGHT))
        self.assertEqual([r.heading_deg for r in lay.rows], [90.0, 270.0])
        ys0 = [s.y_mm for s in lay.rows[0].spots]
        ys1 = [s.y_mm for s in lay.rows[1].spots]
        self.assertEqual(ys0, sorted(ys0))
        self.assertEqual(ys1, sorted(ys1, reverse=True))

    def test_distances_start_from_the_entry_edge(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.EIGHT))
        d0 = lay.rows[0].distances_mm()
        self.assertAlmostEqual(d0[0], 12 * IN)
        self.assertAlmostEqual(d0[1], 24 * IN)
        d1 = lay.rows[1].distances_mm()   # enters from the far edge
        self.assertAlmostEqual(d1[0], 12 * IN)


class Tiling(unittest.TestCase):
    def test_whole_boards_only(self):
        lay = plan(RoofSpec(width_mm=BOARD_WIDTH_MM * 2.5, length_mm=BOARD_LENGTH_MM * 3.9,
                            variant=PatternVariant.EIGHT))
        self.assertEqual((lay.boards_across, lay.boards_along), (2, 3))
        self.assertEqual(lay.total_spots, 2 * 3 * 8)

    def test_setback_can_remove_a_board(self):
        spec = RoofSpec(width_mm=BOARD_WIDTH_MM, length_mm=BOARD_LENGTH_MM, setback_mm=1.0)
        with self.assertRaises(ValueError):
            plan(spec)

    def test_spots_stay_inside_the_roof(self):
        spec = RoofSpec(width_mm=5000, length_mm=9000, setback_mm=100)
        for w in plan(spec).waypoints:
            self.assertTrue(100 <= w.x_mm <= 4900 and 100 <= w.y_mm <= 8900)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            plan(RoofSpec(width_mm=0, length_mm=100))
        with self.assertRaises(ValueError):
            plan(RoofSpec(**ONE_BOARD, flute_pitch_mm=0))


class CrestSnap(unittest.TestCase):
    def test_six_inch_pitch_lands_on_every_spot(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.FIVE, flute_pitch_mm=6 * IN))
        self.assertTrue(all(abs(w.crest_offset_mm) < 1e-6 for w in lay.waypoints))

    def test_odd_pitch_reports_an_offset(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.EIGHT, flute_pitch_mm=7.5 * IN))
        self.assertTrue(any(abs(w.crest_offset_mm) > 1 for w in lay.waypoints))
        for w in lay.waypoints:
            self.assertLessEqual(abs(w.crest_offset_mm), 7.5 * IN / 2 + 1e-6)

    def test_crests_to_next_row(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.FIVE, flute_pitch_mm=6 * IN))
        self.assertEqual([r.crests_to_next for r in lay.rows], [2, 2, None])

    def test_default_phase_puts_a_crest_under_the_board_edges(self):
        spec = RoofSpec(width_mm=BOARD_WIDTH_MM * 2 + 50, length_mm=BOARD_LENGTH_MM,
                        variant=PatternVariant.FIVE, flute_pitch_mm=6 * IN)
        lay = plan(spec)   # boards are centred, so their edge is 25 mm in, not on a multiple of 6 in
        self.assertTrue(all(abs(w.crest_offset_mm) < 1e-6 for w in lay.waypoints))
        edge = lay.board_origin_mm[0]
        self.assertAlmostEqual((edge - lay.crest_phase_mm) % (6 * IN), 0.0, places=6)

    def test_explicit_phase_is_respected(self):
        lay = plan(RoofSpec(**ONE_BOARD, flute_pitch_mm=6 * IN, crest_phase_mm=10.0))
        self.assertEqual(lay.crest_phase_mm, 10.0)
        self.assertTrue(any(abs(w.crest_offset_mm) > 1 for w in lay.waypoints))

    def test_no_pitch_means_no_snap(self):
        lay = plan(RoofSpec(**ONE_BOARD))
        self.assertTrue(all(w.crest_offset_mm == 0.0 for w in lay.waypoints))
        self.assertTrue(all(r.crests_to_next is None for r in lay.rows))


if __name__ == "__main__":
    unittest.main()
