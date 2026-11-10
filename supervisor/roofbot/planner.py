"""Roof layout and path planner.

Pure functions and data, no I/O, like the rest of the Supervisor package.

Frame. All coordinates are millimetres in a roof frame whose origin is the
corner where the operator places the robot. x runs ACROSS the flutes and y runs
ALONG them, both increasing away from that corner. Heading is in degrees with
the maths convention: 0 is +x, 90 is +y, 180 is -x, 270 is -y. Rows run along
the flutes, so a row heading is 90 or 270.

Where the spots come from. The Carlisle MF-27 detail (docs/planning/navigation/
../../docs/planning/navigation/Fastning Report.pdf) fixes the fastener positions on each 4 x 8 ft board. This
module tiles whole boards over the roof and stamps that pattern on each one.
Cut boards, the running-bond stagger and the other start corners are not
modelled yet.

Crests. If a flute pitch is given, every spot is snapped to the nearest crest
and the offset is reported, because the spec's positions in inches may not land
on a crest. Without a pitch the spots are left where the spec puts them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .route import Route, RowPlan

IN = 25.4
BOARD_WIDTH_MM = 48 * IN   # across the flutes
BOARD_LENGTH_MM = 96 * IN  # along the flutes


class PatternVariant(Enum):
    """Which MF-27 pattern applies. One variant per roof."""
    FIVE = "five"    # Dens-Deck over insulation of at least 40 mm: 5 per 4x8 board
    EIGHT = "eight"  # re-roof, polyiso under 40 mm: 8 per 4x8 board
    DEMO = "demo"    # demo: 4 x 8 ft boards with 4 screws each (the four outer corners of the eight pattern)


# Fastener positions in inches from the board corner: (across x, along y).
_PATTERN_IN = {
    PatternVariant.FIVE: [(12, 12), (36, 12), (24, 48), (12, 84), (36, 84)],
    PatternVariant.EIGHT: [(x, y) for y in (12, 36, 60, 84) for x in (12, 36)],
    PatternVariant.DEMO: [(x, y) for y in (12, 84) for x in (12, 36)],
}


def board_size_mm(variant: PatternVariant) -> tuple[float, float]:
    """(width across the flutes, length along them) of the board. Every variant uses 4 x 8 ft boards."""
    return BOARD_WIDTH_MM, BOARD_LENGTH_MM


def board_pattern_mm(variant: PatternVariant) -> list[tuple[float, float]]:
    """Fastener positions on one 4 x 8 ft board, in mm from its corner."""
    return [(x * IN, y * IN) for x, y in _PATTERN_IN[variant]]


@dataclass(frozen=True)
class RoofSpec:
    """The schematic: a rectangle (width and length), or a drawn outline.

    For an outline, build the spec with `RoofSpec.from_outline(points, ...)`, which moves the shape
    so its lowest-left corner is the origin and fills in the width and length from its bounding box.
    """
    width_mm: float                         # across the flutes
    length_mm: float                        # along the flutes
    variant: PatternVariant = PatternVariant.FIVE
    setback_mm: float = 0.0                 # gap between the roof edge and the first board
    flute_pitch_mm: Optional[float] = None  # crest to crest. Placeholder until measured
    # x of one crest, so crests sit at phase + k * pitch. None means a crest lies under the board
    # edges, which is what the installation guide asks for (edge joints on a top flute).
    crest_phase_mm: Optional[float] = None
    # Corners of the roof outline in mm, in order round the shape, in the same frame as the
    # width and length. None means the plain rectangle.
    outline: Optional[tuple[tuple[float, float], ...]] = None
    # The x of every crest, when the real positions are known (from the team's schematic). Spots are
    # snapped to the nearest of these, and it replaces the pitch and phase. None means use the pitch.
    crest_xs_mm: Optional[tuple[float, ...]] = None
    # How a strip ends. "run-out" (the default): the robot keeps driving past its last screw to the
    # level where the next strip's first screw is, and turns there, so every strip is driven forwards
    # and nothing reverses. "last-spot": it turns beside its last screw, and reverses if the next
    # strip's first screw is behind it (the middle column of the 5-screw pattern).
    turn_style: str = "run-out"

    @classmethod
    def from_outline(cls, points, variant: PatternVariant = PatternVariant.FIVE, setback_mm: float = 0.0,
                     flute_pitch_mm: Optional[float] = None,
                     crest_phase_mm: Optional[float] = None,
                     crest_xs_mm=None, turn_style: str = "run-out") -> "RoofSpec":
        """`crest_xs_mm`, if given, is in the same frame as `points` (it is shifted with them)."""
        pts = _clean_outline(points)
        minx, miny = min(p[0] for p in pts), min(p[1] for p in pts)
        pts = tuple((x - minx, y - miny) for x, y in pts)
        crests = None if crest_xs_mm is None else tuple(sorted(float(x) - minx for x in crest_xs_mm))
        return cls(max(p[0] for p in pts), max(p[1] for p in pts), variant, setback_mm,
                   flute_pitch_mm, crest_phase_mm, pts, crests, turn_style)


@dataclass(frozen=True)
class Waypoint:
    row: int                   # 1-based, in driving order
    spot: int                  # 1-based, in driving order within the row
    x_mm: float                # snapped to the crest when a pitch is known
    y_mm: float
    heading_deg: float         # direction of travel along the row: 90 or 270
    crest_offset_mm: float     # snapped x minus the spec's x. 0 without a pitch


@dataclass(frozen=True)
class PlannedRow:
    row: int
    x_mm: float
    heading_deg: float
    spots: tuple[Waypoint, ...]
    # Where the row starts. Row 1 starts at the roof edge where the robot is put down. Every later
    # row starts level with the last spot of the row before it: the robot turns beside that spot,
    # so it never drives along the roof edge to change rows.
    entry_y_mm: float
    crests_to_next: Optional[int]  # crests crossed to reach the next row, None for the last row
    exit_y_mm: Optional[float] = None  # the last spot of the row, where the robot turns. None = a roof edge
    shift_to_next_mm: Optional[float] = None  # sideways distance from this row to the next, None for the last
    run_out_mm: float = 0.0    # drive on past the last spot by this much before turning (0 = turn at the spot)

    def distances_mm(self) -> list[float]:
        """Travel to spot 1 from where the row starts, then spot to spot.

        Signed along the row's heading: positive is forward, negative is reverse. Only the first can
        be negative (when spot 1 is behind the robot after the turn, as in the middle column of the
        5-screw pattern); every later spot is further along the row.
        """
        sign = 1.0 if self.heading_deg == 90.0 else -1.0
        out, here = [], self.entry_y_mm
        for s in self.spots:
            out.append((s.y_mm - here) * sign)
            here = s.y_mm
        return out


@dataclass(frozen=True)
class Layout:
    rows: tuple[PlannedRow, ...]
    boards_across: int
    boards_along: int
    crest_phase_mm: float = 0.0               # the phase actually used
    board_origin_mm: tuple[float, float] = (0.0, 0.0)  # corner of the first whole board
    boards: tuple[tuple[float, float], ...] = ()       # lower-left corner of every whole board used
    # Things the operator should look at, e.g. a row change that does not line up with the shape.
    warnings: tuple[str, ...] = ()

    @property
    def waypoints(self) -> list[Waypoint]:
        return [s for r in self.rows for s in r.spots]

    @property
    def total_spots(self) -> int:
        return sum(len(r.spots) for r in self.rows)


def layout_to_route(layout: Layout) -> Route:
    """Turn a planned layout into the `Route` the Supervisor and simulator run.

    Each row keeps its real, uneven distances (entry edge to spot 1, then spot to spot). The
    Supervisor's `Route` has no x/y, heading or crest data, so only the distances and the
    spot counts carry over. Rows alternate direction already, so the Route's right/left turn
    rule matches the planner's lawnmower order.
    """
    rows = []
    for r in layout.rows:
        d = tuple(r.distances_mm())
        nominal = d[1] if len(d) > 1 else 0.0   # only used by tools that ignore distances_mm
        rows.append(RowPlan(len(d), nominal, d[0], d, r.crests_to_next, r.shift_to_next_mm, r.run_out_mm))
    return Route(rows)


def _snap(x: float, pitch: Optional[float], phase: float) -> float:
    if pitch is None:
        return x
    return phase + round((x - phase) / pitch) * pitch


def _nearest(x: float, crests: tuple[float, ...]) -> tuple[int, float]:
    """(index, x) of the crest closest to x."""
    i = min(range(len(crests)), key=lambda k: abs(crests[k] - x))
    return i, crests[i]


# ---- outline geometry. Plain 2-D helpers, all in mm.

_EPS = 1e-6


def _orient(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _proper_cross(p1, p2, q1, q2) -> bool:
    """True when the segments cross at a single point that is inside both of them."""
    d1, d2 = _orient(q1, q2, p1), _orient(q1, q2, p2)
    d3, d4 = _orient(p1, p2, q1), _orient(p1, p2, q2)
    return ((d1 > _EPS and d2 < -_EPS) or (d1 < -_EPS and d2 > _EPS)) and \
           ((d3 > _EPS and d4 < -_EPS) or (d3 < -_EPS and d4 > _EPS))


def _on_segment(p, a, b) -> bool:
    if abs(_orient(a, b, p)) > _EPS * max(1.0, math.hypot(b[0] - a[0], b[1] - a[1])):
        return False
    return (min(a[0], b[0]) - _EPS <= p[0] <= max(a[0], b[0]) + _EPS and
            min(a[1], b[1]) - _EPS <= p[1] <= max(a[1], b[1]) + _EPS)


def _inside(poly, p) -> bool:
    """Point in polygon. A point on the boundary counts as inside."""
    n, hit = len(poly), False
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if _on_segment(p, a, b):
            return True
        if (a[1] > p[1]) != (b[1] > p[1]):
            if p[0] < a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
                hit = not hit
    return hit


def _clean_outline(points) -> tuple[tuple[float, float], ...]:
    """Check an outline and return it as a tuple of (x, y). Raises ValueError when it is not a shape."""
    pts: list[tuple[float, float]] = []
    for p in points:
        q = (float(p[0]), float(p[1]))
        if not pts or math.hypot(q[0] - pts[-1][0], q[1] - pts[-1][1]) > _EPS:
            pts.append(q)
    if len(pts) > 1 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= _EPS:
        pts.pop()                       # the shape was closed by repeating the first corner
    if len(pts) < 3:
        raise ValueError("a roof outline needs at least 3 corners")
    n = len(pts)
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue                # neighbours share a corner
            if _proper_cross(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                raise ValueError(f"the roof outline crosses itself (sides {i + 1} and {j + 1})")
    area2 = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                for i in range(len(pts)))
    if abs(area2) < _EPS:
        raise ValueError("the roof outline has no area")
    return tuple(pts)


def _rect_inside(poly, x0: float, y0: float, x1: float, y1: float) -> bool:
    """True when the whole rectangle lies inside the polygon (touching the edge is allowed)."""
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if not all(_inside(poly, c) for c in corners):
        return False
    # Corners on the edge say nothing about the middle: a board sitting in a notch has all four
    # corners on the roof's edge. So also look at points inside the board.
    w, h = x1 - x0, y1 - y0
    if not all(_inside(poly, (x0 + w * fx, y0 + h * fy))
               for fx in (0.25, 0.5, 0.75) for fy in (0.25, 0.5, 0.75)):
        return False
    if any(x0 + _EPS < vx < x1 - _EPS and y0 + _EPS < vy < y1 - _EPS for vx, vy in poly):
        return False                    # a corner of the roof pokes into the board
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        for k in range(4):
            if _proper_cross(a, b, corners[k], corners[(k + 1) % 4]):
                return False
    return True


def _segment_inside(poly, a, b, step: float = 10.0) -> bool:
    """True when the straight path from a to b stays inside the polygon."""
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    n = max(1, int(length / step))
    return all(_inside(poly, (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n))
               for i in range(n + 1))


def _chords(poly, x: float) -> list[tuple[float, float]]:
    """The stretches of the vertical line at x that lie inside the polygon, as (low y, high y)."""
    ys, n = [], len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if x1 == x2:
            continue
        if min(x1, x2) <= x < max(x1, x2):   # half open, so a corner is counted once
            ys.append(y1 + (x - x1) / (x2 - x1) * (y2 - y1))
    ys.sort()
    return [(ys[i], ys[i + 1]) for i in range(0, len(ys) - 1, 2)]


def _boards_in_outline(spec: RoofSpec, bw: float, bl: float) -> tuple[list[tuple[float, float]], float]:
    """Whole boards that fit inside the outline, and the x of the board grid's first column.

    Boards are laid on a grid over the bounding box. Which way to line the grid up (centred, or
    against the low or high edge, on each axis) is chosen to fit the most boards. Ties keep the
    centred grid, so a plain rectangle comes out the same as the rectangle planner.
    """
    poly, sb = spec.outline, spec.setback_mm
    usable_w, usable_l = spec.width_mm - 2 * sb, spec.length_mm - 2 * sb
    cols, rows = int(math.floor(usable_w / bw + 1e-9)), int(math.floor(usable_l / bl + 1e-9))
    if cols < 1 or rows < 1:
        raise ValueError("the roof is too small for one whole board")

    def starts(extent: float, size: float, count: int) -> list[float]:
        spare = extent - count * size
        return [sb + spare / 2, sb, sb + spare]

    best: tuple[list[tuple[float, float]], float] = ([], 0.0)
    for x0 in starts(usable_w, bw, cols):
        for y0 in starts(usable_l, bl, rows):
            found = [(x0 + i * bw, y0 + j * bl) for i in range(cols) for j in range(rows)
                     if _rect_inside(poly, x0 + i * bw - sb, y0 + j * bl - sb,
                                     x0 + (i + 1) * bw + sb, y0 + (j + 1) * bl + sb)]
            if len(found) > len(best[0]):
                best = (found, x0)
    if not best[0]:
        raise ValueError("no whole board fits inside the roof outline")
    return best


def plan(spec: RoofSpec) -> Layout:
    """Tile whole boards, stamp the fastener pattern and order the rows."""
    if spec.width_mm <= 0 or spec.length_mm <= 0:
        raise ValueError("roof dimensions must be positive")
    if spec.setback_mm < 0:
        raise ValueError("setback cannot be negative")
    if spec.flute_pitch_mm is not None and spec.flute_pitch_mm <= 0:
        raise ValueError("flute pitch must be positive")
    if spec.turn_style not in ("run-out", "last-spot"):
        raise ValueError("turn_style must be 'run-out' or 'last-spot'")
    if spec.crest_xs_mm is not None and len(spec.crest_xs_mm) == 0:
        raise ValueError("the list of crest positions is empty")

    bw, bl = board_size_mm(spec.variant)
    poly = spec.outline
    across = along = 0
    if poly is None:
        usable_w = spec.width_mm - 2 * spec.setback_mm
        usable_l = spec.length_mm - 2 * spec.setback_mm
        across = int(math.floor(usable_w / bw + 1e-9))
        along = int(math.floor(usable_l / bl + 1e-9))
        if across < 1 or along < 1:
            raise ValueError("the roof is too small for one whole board")

        # Centre the whole boards in the usable area, so leftovers split evenly.
        x0 = spec.setback_mm + (usable_w - across * bw) / 2
        y0 = spec.setback_mm + (usable_l - along * bl) / 2
        boards = [(x0 + bi * bw, y0 + bj * bl) for bi in range(across) for bj in range(along)]

        def chords_at(_x: float) -> list[tuple[float, float]]:
            return [(0.0, spec.length_mm)]
    else:
        poly = _clean_outline(poly)
        if (min(p[0] for p in poly) > _EPS or min(p[1] for p in poly) > _EPS
                or abs(max(p[0] for p in poly) - spec.width_mm) > _EPS
                or abs(max(p[1] for p in poly) - spec.length_mm) > _EPS):
            raise ValueError("the outline must start at the origin and match the width and length; "
                             "build the spec with RoofSpec.from_outline")
        boards, x0 = _boards_in_outline(spec, bw, bl)
        y0 = min(b[1] for b in boards)

        def chords_at(x: float) -> list[tuple[float, float]]:
            return _chords(poly, x)

    phase = spec.crest_phase_mm
    if phase is None:
        phase = x0 % spec.flute_pitch_mm if spec.flute_pitch_mm else 0.0

    # Group by the spec's x so rows stay together, then snap each row once.
    by_line: dict[float, list[float]] = {}
    for bx, by in boards:
        for px, py in board_pattern_mm(spec.variant):
            by_line.setdefault(round(bx + px, 3), []).append(round(by + py, 3))

    # One run per stretch of a column that lies inside the roof: (x, low y, high y, spot ys).
    runs: list[tuple[float, float, float, list[float]]] = []
    for key in sorted(by_line):
        left = sorted(by_line[key])
        for lo, hi in sorted(chords_at(key)):
            got = [y for y in left if lo - _EPS <= y <= hi + _EPS]
            if got:
                runs.append((key, lo, hi, got))
                left = [y for y in left if y not in got]
        if left:
            raise ValueError("a fastener position fell outside the roof outline")

    known_crests = spec.crest_xs_mm is not None or spec.flute_pitch_mm is not None

    def snap(x: float) -> tuple[int, float]:
        """(crest number, snapped x). The difference between two crest numbers is the crests crossed."""
        if spec.crest_xs_mm is not None:
            return _nearest(x, spec.crest_xs_mm)
        if spec.flute_pitch_mm is not None:
            k = round((x - phase) / spec.flute_pitch_mm)
            return k, phase + k * spec.flute_pitch_mm
        return 0, x

    # ---- pass 1: each strip's spots, in driving order
    strips = []   # (row number, x, heading, spots, crests to next, shift to next, low y, high y)
    for n, (key, lo, hi, ys) in enumerate(runs, start=1):
        forward = n % 2 == 1
        heading = 90.0 if forward else 270.0
        ys = sorted(ys, reverse=not forward)
        here, x = snap(key)
        offset = x - key if known_crests else 0.0
        spots = tuple(Waypoint(n, i, x, y, heading, offset) for i, y in enumerate(ys, start=1))
        crests = shift = None
        if n < len(runs):
            there, nxt_x = snap(runs[n][0])
            shift = abs(nxt_x - x)
            if known_crests:
                crests = abs(there - here)
        strips.append((n, x, heading, spots, crests, shift, lo, hi))

    # ---- pass 2: where each turn happens. The robot turns level with `t`:
    #   last-spot: beside its last screw (and reverses if the next strip's first screw is behind it);
    #   run-out:   it drives on past its last screw to the level of the next strip's first screw
    #              (when that is further on), so the next strip is entered facing the right way.
    # A run-out that would leave the roof falls back to turning at the last screw.
    levels: list[float] = []
    for a, b in zip(strips, strips[1:]):
        a_last, b_first, a_up = a[3][-1].y_mm, b[3][0].y_mm, a[2] == 90.0
        t = a_last
        if spec.turn_style == "run-out":
            want = max(a_last, b_first) if a_up else min(a_last, b_first)
            if want != a_last and (poly is None or (
                    _segment_inside(poly, (a[1], a_last), (a[1], want))
                    and _segment_inside(poly, (a[1], want), (b[1], want))
                    and _segment_inside(poly, (b[1], want), (b[1], b_first)))):
                t = want
        levels.append(t)

    rows: list[PlannedRow] = []
    for i, (n, x, heading, spots, crests, shift, lo, hi) in enumerate(strips):
        # Row 1 starts at the roof edge where the robot is put down; later rows start at the turn level.
        entry = (lo if heading == 90.0 else hi) if i == 0 else levels[i - 1]
        run_out = abs(levels[i] - spots[-1].y_mm) if i < len(levels) else 0.0
        rows.append(PlannedRow(n, x, heading, spots, entry, crests, spots[-1].y_mm, shift, run_out))

    warnings: list[str] = []
    if poly is not None:
        for a, b in zip(rows, rows[1:]):
            # along the row to the turn level, across to the next row, then along it to its first spot
            end = a.exit_y_mm + (a.run_out_mm if a.heading_deg == 90.0 else -a.run_out_mm)
            on_roof = (_segment_inside(poly, (a.x_mm, a.exit_y_mm), (a.x_mm, end))
                       and _segment_inside(poly, (a.x_mm, end), (b.x_mm, b.entry_y_mm))
                       and _segment_inside(poly, (b.x_mm, b.entry_y_mm), (b.x_mm, b.spots[0].y_mm)))
            if not on_roof:
                warnings.append(f"The turn from row {a.row} to row {b.row} (level with y = "
                                f"{b.entry_y_mm:.0f} mm) does not stay on the roof.")
    return Layout(tuple(rows), across, along, phase, (min(b[0] for b in boards), y0),
                  tuple(boards), tuple(warnings))
