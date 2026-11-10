import unittest

from roofbot.messages import Step
from roofbot.planner import (BOARD_LENGTH_MM, BOARD_WIDTH_MM, IN, PatternVariant,
                             RoofSpec, board_pattern_mm, board_size_mm, layout_to_route, plan)
from roofbot.route import Route, RowPlan
from roofbot.sim import SimWorld
from roofbot.supervisor import State

ONE_BOARD = dict(width_mm=BOARD_WIDTH_MM, length_mm=BOARD_LENGTH_MM)


class Pattern(unittest.TestCase):
    def test_five_has_five_and_eight_has_eight(self):
        self.assertEqual(len(board_pattern_mm(PatternVariant.FIVE)), 5)
        self.assertEqual(len(board_pattern_mm(PatternVariant.EIGHT)), 8)

    def test_five_matches_the_spec_sheet(self):
        got = {(round(x / IN), round(y / IN)) for x, y in board_pattern_mm(PatternVariant.FIVE)}
        self.assertEqual(got, {(12, 12), (36, 12), (24, 48), (12, 84), (36, 84)})


class DemoBoards(unittest.TestCase):
    """The demo: 4 x 8 ft boards, 4 screws each (the outer corners of the eight pattern)."""

    def test_board_size_and_pattern(self):
        self.assertEqual(board_size_mm(PatternVariant.DEMO), (48 * IN, 96 * IN))
        got = {(round(x / IN), round(y / IN)) for x, y in board_pattern_mm(PatternVariant.DEMO)}
        self.assertEqual(got, {(12, 12), (36, 12), (12, 84), (36, 84)})

    def test_three_boards_in_a_line(self):
        lay = plan(RoofSpec(width_mm=48 * IN, length_mm=288 * IN, variant=PatternVariant.DEMO))
        self.assertEqual((lay.boards_across, lay.boards_along), (1, 3))
        self.assertEqual([len(r.spots) for r in lay.rows], [6, 6])
        self.assertEqual([round(s.y_mm / IN) for s in lay.rows[0].spots], [12, 84, 108, 180, 204, 276])


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

    def test_later_rows_start_level_with_the_last_spot_of_the_row_before(self):
        # The robot turns beside the last spot, not out at the roof edge.
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.EIGHT))
        self.assertEqual(lay.rows[1].entry_y_mm, lay.rows[0].spots[-1].y_mm)
        self.assertEqual(lay.rows[1].distances_mm()[0], 0.0)
        self.assertEqual(lay.rows[0].exit_y_mm, lay.rows[0].spots[-1].y_mm)

    def test_the_first_row_starts_at_the_roof_edge(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.EIGHT))
        self.assertEqual(lay.rows[0].entry_y_mm, 0.0)

    def test_turning_at_the_last_spot_reverses_at_the_start_of_the_third_row(self):
        # the middle column has a single spot at 48 in, so the next column's first spot (12 in) is
        # behind the robot after the turn. With turn_style last-spot the robot reverses: a negative distance.
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.FIVE, turn_style="last-spot"))
        self.assertEqual(lay.warnings, ())
        self.assertAlmostEqual(lay.rows[2].distances_mm()[0], -36 * IN)
        self.assertAlmostEqual(lay.rows[2].distances_mm()[1], 72 * IN)   # then forward again
        self.assertAlmostEqual(lay.rows[1].distances_mm()[0], 36 * IN)   # row 2: 84 in down to 48 in

    def test_only_the_first_distance_of_a_row_can_be_a_reverse(self):
        for variant in PatternVariant:
            lay = plan(RoofSpec(width_mm=BOARD_WIDTH_MM * 2, length_mm=BOARD_LENGTH_MM * 2, variant=variant))
            for r in lay.rows:
                self.assertTrue(all(d > 0 for d in r.distances_mm()[1:]))

    def test_the_eight_pattern_never_reverses(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.EIGHT))
        self.assertTrue(all(d >= 0 for r in lay.rows for d in r.distances_mm()))

    def test_distances_start_from_the_entry_edge(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.EIGHT))
        d0 = lay.rows[0].distances_mm()
        self.assertAlmostEqual(d0[0], 12 * IN)
        self.assertAlmostEqual(d0[1], 24 * IN)
        d1 = lay.rows[1].distances_mm()   # turns beside row 1's last spot (84 in), so no drive to spot 1
        self.assertAlmostEqual(d1[0], 0.0)
        self.assertAlmostEqual(d1[1], 24 * IN)


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


class LayoutToRoute(unittest.TestCase):
    """The adapter that lets the Supervisor and simulator run a planned layout."""

    def test_row_and_spot_counts_carry_over(self):
        route = layout_to_route(plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.FIVE)))
        self.assertEqual([r.spots for r in route.rows], [2, 1, 2])
        self.assertEqual(route.total_spots, 5)

    def test_distances_are_the_planners_uneven_spacing(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.FIVE))
        route = layout_to_route(lay)
        # row 1 of the five pattern: 12 in from the edge, then 72 in to the far spot
        self.assertAlmostEqual(route.distance_to_spot_mm(1, 1), 12 * IN)
        self.assertAlmostEqual(route.distance_to_spot_mm(1, 2), 72 * IN)
        for n, row in enumerate(lay.rows, start=1):
            got = [route.distance_to_spot_mm(n, s) for s in range(1, row.spots.__len__() + 1)]
            self.assertEqual(got, row.distances_mm())

    def test_distances_must_match_spot_count(self):
        with self.assertRaises(ValueError):
            Route([RowPlan(3, 300.0, 0.0, (1.0, 2.0))])

    def test_plain_rowplan_still_uses_even_spacing(self):
        route = Route([RowPlan(3, 250.0, 80.0)])
        self.assertEqual([route.distance_to_spot_mm(1, s) for s in (1, 2, 3)], [80.0, 250.0, 250.0])

    def test_simulator_drives_the_planned_distances(self):
        route = layout_to_route(plan(RoofSpec(width_mm=48 * IN, length_mm=288 * IN,
                                              variant=PatternVariant.DEMO)))
        w = SimWorld(route)
        w.start_run()
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 600))
        driven = [m.params["distance_mm"] for m in w.locomotion.commands_for(Step.DRIVE)]
        expected = [d for r in route.rows for d in r.distances_mm]
        self.assertEqual(driven, expected)
        self.assertEqual(len(w.fastening.commands), 12)
        self.assertEqual(w.alerts, [])

    def test_a_reverse_survives_the_route_and_the_simulator_runs_it(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.FIVE, turn_style="last-spot"))
        route = layout_to_route(lay)
        self.assertAlmostEqual(route.distance_to_spot_mm(3, 1), -36 * IN)   # reverse
        w = SimWorld(route, detailed=True)
        for node in (w.plate, w.screw):
            node.refill(20)
        w.start_run()
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 900))
        driven = [m.params["distance_mm"] for m in w.locomotion.commands_for(Step.DRIVE)]
        self.assertIn(-36 * IN, [round(d, 6) for d in driven])
        self.assertEqual(w.alerts, [])


class RunOut(unittest.TestCase):
    """Every strip is driven forwards: it runs on past its last screw to where the next strip starts."""

    def test_the_middle_strip_of_the_five_pattern_runs_on_to_the_same_end_as_the_others(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.FIVE))
        r1, r2, r3 = lay.rows
        self.assertAlmostEqual(r2.run_out_mm, 36 * IN)               # 48 in on down to 12 in
        self.assertAlmostEqual(r3.entry_y_mm, 12 * IN)               # the next strip starts level with its first screw
        self.assertAlmostEqual(r3.distances_mm()[0], 0.0)
        self.assertAlmostEqual(r1.run_out_mm, 0.0)
        self.assertEqual(lay.warnings, ())

    def test_nothing_reverses_by_default(self):
        for variant in PatternVariant:
            lay = plan(RoofSpec(width_mm=BOARD_WIDTH_MM * 3, length_mm=BOARD_LENGTH_MM * 2, variant=variant))
            self.assertTrue(all(d >= 0 for r in lay.rows for d in r.distances_mm()), variant.value)

    def test_patterns_whose_strips_line_up_need_no_run_out(self):
        for variant in (PatternVariant.EIGHT, PatternVariant.DEMO):
            lay = plan(RoofSpec(**ONE_BOARD, variant=variant))
            self.assertTrue(all(r.run_out_mm == 0 for r in lay.rows), variant.value)

    def test_a_drawn_shape_also_runs_on_without_reversing_where_the_roof_allows(self):
        from roofbot.shapes import shape_outline_mm
        lay = plan(RoofSpec.from_outline(shape_outline_mm("U"), PatternVariant.FIVE))
        self.assertTrue(any(r.run_out_mm > 0 for r in lay.rows))
        self.assertTrue(all(d >= 0 for r in lay.rows for d in r.distances_mm()))

    def test_the_route_carries_the_run_out_on_the_turn_after_that_strip(self):
        route = layout_to_route(plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.FIVE, flute_pitch_mm=6 * IN)))
        self.assertNotIn("run_out_mm", route.turn_params(1))
        self.assertAlmostEqual(route.turn_params(2)["run_out_mm"], 36 * IN)

    def test_the_simulator_runs_it_and_the_turn_command_carries_the_run_out(self):
        route = layout_to_route(plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.FIVE)))
        w = SimWorld(route, detailed=True)
        for node in (w.plate, w.screw):
            node.refill(20)
        w.start_run()
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 900))
        self.assertEqual(w.alerts, [])
        driven = [m.params["distance_mm"] for m in w.locomotion.commands_for(Step.DRIVE)]
        self.assertTrue(all(d >= 0 for d in driven))
        turns = w.locomotion.commands_for(Step.TURN)
        self.assertEqual([round(m.params.get("run_out_mm", 0) / IN) for m in turns], [0, 36])

    def test_an_unknown_turn_style_is_an_error(self):
        with self.assertRaises(ValueError):
            plan(RoofSpec(**ONE_BOARD, turn_style="sideways"))


class CrestPositions(unittest.TestCase):
    """Real crest positions (from a schematic) instead of an even pitch."""

    def test_spots_snap_to_the_nearest_listed_crest(self):
        # eight pattern: columns at 12 in and 36 in. Crests at 10 in, 40 in and 70 in (uneven).
        crests = (10 * IN, 40 * IN, 70 * IN)
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.EIGHT, crest_xs_mm=crests))
        self.assertAlmostEqual(lay.rows[0].x_mm, 10 * IN)
        self.assertAlmostEqual(lay.rows[1].x_mm, 40 * IN)
        self.assertAlmostEqual(lay.rows[0].spots[0].crest_offset_mm, -2 * IN)
        self.assertAlmostEqual(lay.rows[1].spots[0].crest_offset_mm, 4 * IN)

    def test_crests_crossed_is_the_difference_in_crest_numbers(self):
        crests = tuple(i * 6 * IN for i in range(9))   # 0, 6, 12 ... 48 in
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.EIGHT, crest_xs_mm=crests))
        self.assertEqual(lay.rows[0].crests_to_next, 4)   # 12 in to 36 in
        self.assertAlmostEqual(lay.rows[0].shift_to_next_mm, 24 * IN)

    def test_a_missing_crest_in_the_list_shows_up_as_a_bigger_count(self):
        crests = (12 * IN, 24 * IN, 36 * IN)   # nothing at 18 or 30
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.EIGHT, crest_xs_mm=crests))
        self.assertEqual(lay.rows[0].crests_to_next, 2)

    def test_an_empty_crest_list_is_an_error(self):
        with self.assertRaises(ValueError):
            plan(RoofSpec(**ONE_BOARD, crest_xs_mm=()))

    def test_from_outline_moves_the_crests_with_the_shape(self):
        s = RoofSpec.from_outline([(100, 50), (900, 50), (900, 700), (100, 700)], crest_xs_mm=[100, 300, 500])
        self.assertEqual(s.crest_xs_mm, (0.0, 200.0, 400.0))


class TurnData(unittest.TestCase):
    """What the robot is told about each row change."""

    def test_every_row_but_the_last_has_a_sideways_shift(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.FIVE))
        self.assertEqual([r.shift_to_next_mm is None for r in lay.rows], [False, False, True])
        self.assertAlmostEqual(lay.rows[0].shift_to_next_mm, 12 * IN)   # 12 in to 24 in
        self.assertAlmostEqual(lay.rows[1].shift_to_next_mm, 12 * IN)   # 24 in to 36 in

    def test_the_shift_is_known_even_without_a_pitch_but_the_crest_count_is_not(self):
        lay = plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.EIGHT))
        self.assertIsNone(lay.rows[0].crests_to_next)
        self.assertAlmostEqual(lay.rows[0].shift_to_next_mm, 24 * IN)

    def test_the_route_carries_the_turn_data(self):
        route = layout_to_route(plan(RoofSpec(**ONE_BOARD, variant=PatternVariant.EIGHT, flute_pitch_mm=6 * IN)))
        self.assertEqual(route.turn_params(1), {"crests": 4, "distance_mm": 24 * IN})
        self.assertEqual(route.turn_params(2), {})   # the last row has no turn

    def test_a_plain_route_has_no_turn_data(self):
        self.assertEqual(Route([RowPlan(2, 300.0, 0.0), RowPlan(2, 300.0, 0.0)]).turn_params(1), {})

    def test_the_turn_command_carries_it_and_the_simulator_completes(self):
        lay = plan(RoofSpec(width_mm=BOARD_WIDTH_MM * 2, length_mm=BOARD_LENGTH_MM, variant=PatternVariant.EIGHT,
                            flute_pitch_mm=6 * IN))
        w = SimWorld(layout_to_route(lay), detailed=True)
        for node in (w.plate, w.screw):
            node.refill(40)
        w.start_run()
        self.assertTrue(w.run_until_state(State.RUN_COMPLETE, 1500))
        turns = w.locomotion.commands_for(Step.TURN)
        self.assertEqual(len(turns), len(lay.rows) - 1)   # one TURN command per row change
        self.assertEqual(turns[0].params["crests"], lay.rows[0].crests_to_next)
        self.assertAlmostEqual(turns[0].params["distance_mm"], lay.rows[0].shift_to_next_mm)
        self.assertEqual(w.alerts, [])
