"""The library of common roof outlines."""
import unittest

from roofbot.planner import PatternVariant, RoofSpec, plan
from roofbot.shapes import FT_MM, SHAPES, shape_outline_mm


class ShapeLibrary(unittest.TestCase):
    def test_the_basic_shapes_are_there(self):
        for key in ("rect", "L", "T", "U", "H", "plus", "Z", "stair", "notch", "chamfer", "trapezoid"):
            self.assertIn(key, SHAPES)

    def test_every_shape_is_a_valid_outline(self):
        for key in SHAPES:
            with self.subTest(shape=key):
                spec = RoofSpec.from_outline(shape_outline_mm(key))   # checks corners, area, self-crossing
                self.assertGreater(spec.width_mm, 0)
                self.assertGreater(spec.length_mm, 0)

    def test_every_shape_plans_with_every_pattern(self):
        for key in SHAPES:
            for variant in (PatternVariant.DEMO, PatternVariant.FIVE, PatternVariant.EIGHT):
                with self.subTest(shape=key, variant=variant.value):
                    lay = plan(RoofSpec.from_outline(shape_outline_mm(key), variant))
                    self.assertGreaterEqual(len(lay.boards), 1)
                    self.assertGreaterEqual(lay.total_spots, 4)

    def test_rectangles_and_the_l_shape_plan_without_warnings(self):
        for key in ("rect", "square", "L", "L-wide", "U", "stair", "notch", "chamfer", "trapezoid"):
            with self.subTest(shape=key):
                lay = plan(RoofSpec.from_outline(shape_outline_mm(key), PatternVariant.DEMO))
                self.assertEqual(lay.warnings, ())

    def test_conversion_to_millimetres(self):
        self.assertEqual(shape_outline_mm("rect")[1], (8 * FT_MM, 0.0))


if __name__ == "__main__":
    unittest.main()
