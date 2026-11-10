import unittest
import xml.etree.ElementTree as ET

from roofbot.planner import BOARD_LENGTH_MM, BOARD_WIDTH_MM, IN, PatternVariant, RoofSpec, plan
from roofbot.planner_svg import layout_to_svg

NS = "{http://www.w3.org/2000/svg}"


def render(spec):
    return ET.fromstring(layout_to_svg(spec, plan(spec)))


def group(root, gid):
    return next(g for g in root.iter(NS + "g") if g.get("id") == gid)


class Svg(unittest.TestCase):
    def setUp(self):
        self.spec = RoofSpec(BOARD_WIDTH_MM * 2, BOARD_LENGTH_MM * 2, PatternVariant.EIGHT,
                             flute_pitch_mm=6 * IN)
        self.root = render(self.spec)

    def test_is_valid_xml_with_the_named_layers(self):
        ids = {g.get("id") for g in self.root.iter(NS + "g")}
        self.assertEqual(ids, {"deck", "flutes", "boards", "outline", "rows", "spots", "labels"})

    def test_one_circle_per_spot(self):
        circles = [c for c in group(self.root, "spots").iter(NS + "circle") if c.get("id")]
        self.assertEqual(len(circles), plan(self.spec).total_spots)

    def test_one_row_line_per_row_and_one_rect_per_board(self):
        rows = [ln for ln in group(self.root, "rows").iter(NS + "line") if ln.get("id")]
        self.assertEqual(len(rows), len(plan(self.spec).rows))
        self.assertEqual(len(list(group(self.root, "boards").iter(NS + "rect"))), 4)

    def test_flutes_only_when_a_pitch_is_given(self):
        self.assertGreater(len(list(group(self.root, "flutes").iter(NS + "line"))), 10)
        bare = render(RoofSpec(BOARD_WIDTH_MM, BOARD_LENGTH_MM))
        self.assertEqual(len(list(group(bare, "flutes").iter(NS + "line"))), 0)

    def test_off_crest_spots_are_marked(self):
        spec = RoofSpec(BOARD_WIDTH_MM, BOARD_LENGTH_MM, PatternVariant.EIGHT, flute_pitch_mm=7.5 * IN)
        root = render(spec)
        marked = [c for c in group(root, "spots").iter(NS + "circle") if "off-crest" in (c.get("class") or "")]
        self.assertTrue(marked)

    def test_styling_lives_in_one_style_block(self):
        styles = list(self.root.iter(NS + "style"))
        self.assertEqual(len(styles), 1)
        self.assertNotIn("fill=", ET.tostring(group(self.root, "spots"), encoding="unicode"))


if __name__ == "__main__":
    unittest.main()


class Turns(unittest.TestCase):
    def test_turn_lines_run_across_beside_the_last_spot_and_never_along_the_edge(self):
        spec = RoofSpec(BOARD_WIDTH_MM, BOARD_LENGTH_MM, PatternVariant.EIGHT)
        lay = plan(spec)
        root = render(spec)
        turns = [ln for ln in group(root, "rows").iter(NS + "line") if ln.get("class") == "turn"]
        self.assertEqual(len(turns), len(lay.rows) - 1)   # none for row 1: no line from a corner
        for ln, row in zip(turns, lay.rows[1:]):
            self.assertEqual(ln.get("y1"), ln.get("y2"))           # straight across the roof
            self.assertAlmostEqual(float(ln.get("x2")) - float(ln.get("x1")), 0.0, delta=BOARD_WIDTH_MM)


class ReverseLegs(unittest.TestCase):
    """A first spot that is behind the robot after a turn must be reached by a drawn reverse leg."""

    def lines(self, spec):
        root = render(spec)
        return {ln.get("id"): ln for ln in group(root, "rows").iter(NS + "line") if ln.get("id")}

    def test_turning_at_the_last_spot_draws_a_reverse_leg_to_the_first_spot_of_row_three(self):
        spec = RoofSpec(BOARD_WIDTH_MM, BOARD_LENGTH_MM, PatternVariant.FIVE, turn_style="last-spot")
        lines = self.lines(spec)
        self.assertEqual(sorted(k for k in lines if k.startswith("reverse")), ["reverse-3"])
        spot = next(c for c in group(render(spec), "spots").iter(NS + "circle") if c.get("id") == "spot-3-1")
        rev = lines["reverse-3"]
        self.assertAlmostEqual(float(rev.get("y2")), float(spot.get("cy")), places=1)    # ends on spot 1
        self.assertAlmostEqual(float(lines["row-3"].get("y1")), float(spot.get("cy")), places=1)  # the forward run starts there

    def test_by_default_the_middle_strip_is_drawn_running_on_to_the_turn_level(self):
        spec = RoofSpec(BOARD_WIDTH_MM, BOARD_LENGTH_MM, PatternVariant.FIVE)
        lines = self.lines(spec)
        self.assertEqual([k for k in lines if k.startswith("reverse")], [])
        # row 2's line ends where row 3 starts: both at the 12 in level
        self.assertEqual(lines["row-2"].get("y2"), lines["row-3"].get("y1"))
        self.assertGreater(abs(float(lines["row-2"].get("y2")) - float(lines["row-2"].get("y1"))), 0)

    def test_every_spot_lies_on_a_drawn_leg(self):
        for variant, style in [(v, s) for v in PatternVariant for s in ("run-out", "last-spot")]:
            with self.subTest(variant=variant.value, style=style):
                spec = RoofSpec(BOARD_WIDTH_MM, BOARD_LENGTH_MM * 2, variant, turn_style=style)
                root = render(spec)
                legs = [ln for ln in group(root, "rows").iter(NS + "line") if ln.get("id")]
                for c in group(root, "spots").iter(NS + "circle"):
                    if not c.get("id"):
                        continue
                    cx, cy = float(c.get("cx")), float(c.get("cy"))
                    self.assertTrue(any(abs(float(ln.get("x1")) - cx) < 0.5 and
                                        min(float(ln.get("y1")), float(ln.get("y2"))) - 0.5 <= cy <=
                                        max(float(ln.get("y1")), float(ln.get("y2"))) + 0.5 for ln in legs), c.get("id"))

    def test_patterns_that_never_reverse_draw_no_reverse_legs(self):
        spec = RoofSpec(BOARD_WIDTH_MM, BOARD_LENGTH_MM, PatternVariant.EIGHT)
        self.assertEqual([k for k in self.lines(spec) if k.startswith("reverse")], [])
