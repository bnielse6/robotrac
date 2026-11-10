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
