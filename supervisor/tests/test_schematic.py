"""Reading a roof schematic (SVG or DXF) into an outline and real crest positions."""
import math
import unittest

from roofbot.planner import IN, PatternVariant, RoofSpec, plan
from roofbot.schematic import (SchematicError, parse_schematic, schematic_to_dxf, schematic_to_svg)
from roofbot.shapes import shape_outline_mm

L_MM = shape_outline_mm("L")                       # 8 x 24 ft L shape
CRESTS = [i * 6 * IN for i in range(0, 17)]        # a crest every 6 in across 8 ft
SVG_NS = 'xmlns="http://www.w3.org/2000/svg"'


def close(a, b, tol=0.05):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


class RoundTrip(unittest.TestCase):
    def test_svg_written_by_us_reads_back_exactly(self):
        for unit in ("mm", "in"):
            with self.subTest(unit=unit):
                s = parse_schematic(schematic_to_svg(L_MM, CRESTS, unit=unit))
                self.assertTrue(close(sorted(s.crest_xs_mm), CRESTS, 0.5))
                self.assertEqual(len(s.outline_mm), len(L_MM))
                self.assertAlmostEqual(max(p[0] for p in s.outline_mm), 8 * 12 * IN, delta=0.5)
                self.assertAlmostEqual(max(p[1] for p in s.outline_mm), 24 * 12 * IN, delta=0.5)
                self.assertAlmostEqual(s.pitch_mm, 6 * IN, delta=0.5)

    def test_dxf_written_by_us_reads_back_exactly(self):
        s = parse_schematic(schematic_to_dxf(L_MM, CRESTS))
        self.assertTrue(close(sorted(s.crest_xs_mm), CRESTS, 0.5))
        self.assertEqual(len(s.outline_mm), len(L_MM))
        self.assertAlmostEqual(max(p[1] for p in s.outline_mm), 24 * 12 * IN, delta=0.5)

    def test_the_result_feeds_the_planner(self):
        s = parse_schematic(schematic_to_svg(L_MM, CRESTS))
        spec = RoofSpec.from_outline(s.outline_mm, PatternVariant.DEMO, crest_xs_mm=s.crest_xs_mm)
        lay = plan(spec)
        self.assertEqual(len(lay.boards), 4)
        self.assertTrue(all(any(abs(r.x_mm - c) < 1e-6 for c in s.crest_xs_mm) for r in lay.rows))


class Orientation(unittest.TestCase):
    def test_a_drawing_turned_on_its_side_is_turned_back(self):
        # crests drawn running left to right instead of up the page
        svg = (f'<svg {SVG_NS} viewBox="0 0 1000 400" width="1000mm" height="400mm">'
               '<polygon id="roof" points="0,0 1000,0 1000,400 0,400"/>'
               + "".join(f'<line id="flute-{i}" x1="0" y1="{y}" x2="1000" y2="{y}"/>'
                         for i, y in enumerate((50, 150, 250, 350)))
               + '</svg>')
        s = parse_schematic(svg)
        self.assertAlmostEqual(abs(s.angle_deg), 90.0, delta=0.1)
        self.assertEqual(len(s.crest_xs_mm), 4)
        self.assertAlmostEqual(max(p[1] for p in s.outline_mm), 1000.0, delta=0.5)   # the long side is now vertical
        self.assertAlmostEqual(s.pitch_mm, 100.0, delta=0.5)

    def test_a_slightly_skewed_drawing_is_straightened(self):
        a = math.radians(5)

        def rot(x, y):
            return (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a))

        outline = [rot(0, 0), rot(800, 0), rot(800, 2400), rot(0, 2400)]
        lines = [(rot(x, 0), rot(x, 2400)) for x in (100, 300, 500, 700)]
        pts = " ".join(f"{x:.3f},{-y:.3f}" for x, y in outline)
        svg = (f'<svg {SVG_NS}><polygon id="roof-outline" points="{pts}"/>'
               + "".join(f'<line id="crest" x1="{p[0]:.3f}" y1="{-p[1]:.3f}" x2="{q[0]:.3f}" y2="{-q[1]:.3f}"/>'
                         for p, q in lines)
               + '</svg>')
        s = parse_schematic(svg)
        self.assertAlmostEqual(abs(s.angle_deg), 5.0, delta=0.2)
        self.assertTrue(close(sorted(s.crest_xs_mm), [100, 300, 500, 700], 0.5))


class FindingThings(unittest.TestCase):
    def test_unnamed_shapes_the_largest_closed_shape_and_long_parallel_lines_are_used(self):
        svg = (f'<svg {SVG_NS}>'
               '<rect x="0" y="0" width="600" height="1800"/>'
               '<rect x="10" y="10" width="20" height="20"/>'               # a small closed shape: ignored
               '<line x1="100" y1="0" x2="100" y2="1800"/><line x1="300" y1="0" x2="300" y2="1800"/>'
               '<line x1="500" y1="0" x2="500" y2="1800"/>'
               '<line x1="0" y1="900" x2="600" y2="900"/>'                    # across the flutes: not a crest line
               '</svg>')
        s = parse_schematic(svg)
        self.assertEqual([round(x) for x in s.crest_xs_mm], [100, 300, 500])
        self.assertTrue(any("largest" in n for n in s.notes))

    def test_transforms_on_groups_are_applied(self):
        svg = (f'<svg {SVG_NS}><g transform="translate(500,500) scale(2)">'
               '<polygon id="roof" points="0,0 100,0 100,300 0,300"/>'
               '<line id="crest" x1="25" y1="0" x2="25" y2="300"/>'
               '<line id="crest" x1="75" y1="0" x2="75" y2="300"/></g></svg>')
        s = parse_schematic(svg)
        self.assertAlmostEqual(max(p[0] for p in s.outline_mm), 200.0, delta=0.1)
        self.assertEqual([round(x) for x in s.crest_xs_mm], [50, 150])

    def test_paths_with_straight_sides_work_and_curves_are_refused(self):
        ok = parse_schematic(f'<svg {SVG_NS}><path id="roof" d="M0 0 H400 V1000 H0 Z"/></svg>')
        self.assertEqual(len(ok.outline_mm), 4)
        with self.assertRaisesRegex(SchematicError, "curves"):
            parse_schematic(f'<svg {SVG_NS}><path id="roof" d="M0 0 C 10 10 20 20 30 0 Z"/></svg>')

    def test_pairs_mode_takes_the_middle_of_two_edge_lines(self):
        svg = schematic_to_svg(L_MM, [100, 140, 300, 340])   # two edge lines per crest, 40 mm wide
        s = parse_schematic(svg, crest_lines="pairs")
        self.assertEqual([round(x) for x in s.crest_xs_mm], [120, 320])
        with self.assertRaisesRegex(SchematicError, "pairs"):
            parse_schematic(schematic_to_svg(L_MM, [100, 140, 300]), crest_lines="pairs")

    def test_crest_lines_outside_the_roof_are_ignored_and_duplicates_merged(self):
        s = parse_schematic(schematic_to_svg(L_MM, [100, 100.4, 300, 99999]))
        self.assertEqual([round(x) for x in s.crest_xs_mm], [100, 300])
        self.assertTrue(any("outside" in n for n in s.notes))

    def test_a_roof_with_no_crest_lines_still_gives_the_outline(self):
        s = parse_schematic(schematic_to_svg(L_MM, []))
        self.assertEqual(s.crest_xs_mm, [])
        self.assertEqual(len(s.outline_mm), 6)

    def test_units_can_be_given_when_the_file_does_not_say(self):
        svg = f'<svg {SVG_NS}><polygon id="roof" points="0,0 8,0 8,24 0,24"/></svg>'
        s = parse_schematic(svg, unit_mm=304.8)    # drawn in feet
        self.assertAlmostEqual(max(p[1] for p in s.outline_mm), 24 * 304.8, delta=0.1)


class Refusals(unittest.TestCase):
    def test_garbage_is_refused_with_a_reason(self):
        for text, fmt, word in [("hello", "svg", "valid SVG"), ("hello world\nfoo\nbar\nbaz", "dxf", "DXF"),
                                (f"<svg {SVG_NS}/>", "svg", "no lines"),
                                ("<html/>", "svg", "not an SVG")]:
            with self.subTest(text=text), self.assertRaisesRegex(SchematicError, word):
                parse_schematic(text, fmt=fmt)

    def test_no_closed_shape_means_no_outline(self):
        with self.assertRaisesRegex(SchematicError, "outline"):
            parse_schematic(f'<svg {SVG_NS}><line x1="0" y1="0" x2="0" y2="100"/></svg>')

    def test_entity_declarations_are_refused(self):
        with self.assertRaisesRegex(SchematicError, "entities"):
            parse_schematic(f'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "y">]><svg {SVG_NS}/>')

    def test_bad_arguments(self):
        with self.assertRaises(SchematicError):
            parse_schematic(schematic_to_svg(L_MM, CRESTS), crest_lines="bogus")
        with self.assertRaises(SchematicError):
            parse_schematic(schematic_to_svg(L_MM, CRESTS), unit_mm=-1)
        with self.assertRaises(SchematicError):
            parse_schematic(schematic_to_svg(L_MM, CRESTS), fmt="pdf")


class Dxf(unittest.TestCase):
    def test_layers_pick_the_outline_and_the_crests(self):
        s = parse_schematic(schematic_to_dxf(shape_outline_mm("U"), [200.0, 400.0, 600.0]))
        self.assertEqual(len(s.outline_mm), 8)
        self.assertEqual([round(x) for x in s.crest_xs_mm], [200, 400, 600])

    def test_units_come_from_the_header(self):
        feet = schematic_to_dxf([(0, 0), (8, 0), (8, 24), (0, 24)], [2.0, 6.0])
        feet = feet.replace("$INSUNITS\n70\n4", "$INSUNITS\n70\n2")
        s = parse_schematic(feet)
        self.assertAlmostEqual(max(p[1] for p in s.outline_mm), 24 * 304.8, delta=0.1)
        self.assertEqual([round(x, 1) for x in s.crest_xs_mm], [round(2 * 304.8, 1), round(6 * 304.8, 1)])

    def test_curved_polylines_are_refused(self):
        dxf = "\n".join(["0", "SECTION", "2", "ENTITIES", "0", "LWPOLYLINE", "8", "OUTLINE", "70", "1",
                          "10", "0", "20", "0", "42", "0.5", "10", "5", "20", "0", "10", "5", "20", "5",
                          "0", "ENDSEC", "0", "EOF"])
        with self.assertRaisesRegex(SchematicError, "curved"):
            parse_schematic(dxf, fmt="dxf")


if __name__ == "__main__":
    unittest.main()
