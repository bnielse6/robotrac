"""A library of common roof outlines, ready to hand to `RoofSpec.from_outline`.

Pure data, no I/O. Every outline is a list of (x, y) corners in FEET, going round the shape, with
x across the flutes and y along them, the same frame as the planner. Sizes are multiples of 4 ft so
whole 4 x 8 ft boards tile them cleanly. Scale or edit them as you like: the dashboard drops them on
the drawing canvas, where every corner can be dragged.

`shape_outline_mm(key)` converts one to millimetres.
"""
from __future__ import annotations

FT_MM = 304.8

# key -> (label, corners in feet)
SHAPES: dict[str, tuple[str, list[tuple[float, float]]]] = {
    "rect": ("Rectangle 8 x 24 ft", [(0, 0), (8, 0), (8, 24), (0, 24)]),
    "square": ("Square 16 x 16 ft", [(0, 0), (16, 0), (16, 16), (0, 16)]),
    "L": ("L shape", [(0, 0), (8, 0), (8, 8), (4, 8), (4, 24), (0, 24)]),
    "L-wide": ("L shape, wide", [(0, 0), (16, 0), (16, 8), (8, 8), (8, 24), (0, 24)]),
    "T": ("T shape", [(8, 0), (16, 0), (16, 16), (24, 16), (24, 24), (0, 24), (0, 16), (8, 16)]),
    "U": ("U shape", [(0, 0), (12, 0), (12, 24), (8, 24), (8, 8), (4, 8), (4, 24), (0, 24)]),
    "H": ("H shape", [(0, 0), (8, 0), (8, 8), (16, 8), (16, 0), (24, 0), (24, 24), (16, 24),
                      (16, 16), (8, 16), (8, 24), (0, 24)]),
    "plus": ("Plus / cross", [(8, 0), (16, 0), (16, 8), (24, 8), (24, 16), (16, 16), (16, 24),
                              (8, 24), (8, 16), (0, 16), (0, 8), (8, 8)]),
    "Z": ("Z / S shape", [(0, 0), (16, 0), (16, 8), (24, 8), (24, 24), (8, 24), (8, 16), (0, 16)]),
    "stair": ("Staircase", [(0, 0), (12, 0), (12, 8), (8, 8), (8, 16), (4, 16), (4, 24), (0, 24)]),
    "notch": ("Rectangle with a notch", [(0, 0), (24, 0), (24, 24), (16, 24), (16, 16), (8, 16),
                                         (8, 24), (0, 24)]),
    "chamfer": ("Rectangle, one corner cut", [(0, 0), (24, 0), (24, 16), (16, 24), (0, 24)]),
    "trapezoid": ("Trapezoid", [(0, 0), (24, 0), (20, 24), (4, 24)]),
}


def shape_outline_mm(key: str) -> list[tuple[float, float]]:
    """The named outline in millimetres."""
    return [(x * FT_MM, y * FT_MM) for x, y in SHAPES[key][1]]
