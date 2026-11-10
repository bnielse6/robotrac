"""Roof layout and path planner.

Pure functions and data, no I/O, like the rest of the Supervisor package.

Frame. All coordinates are millimetres in a roof frame whose origin is the
corner where the operator places the robot. x runs ACROSS the flutes and y runs
ALONG them, both increasing away from that corner. Heading is in degrees with
the maths convention: 0 is +x, 90 is +y, 180 is -x, 270 is -y. Rows run along
the flutes, so a row heading is 90 or 270.

Where the spots come from. The Carlisle MF-27 detail (docs/navigation/
Fastning Report.pdf) fixes the fastener positions on each 4 x 8 ft board. This
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

IN = 25.4
BOARD_WIDTH_MM = 48 * IN   # across the flutes
BOARD_LENGTH_MM = 96 * IN  # along the flutes


class PatternVariant(Enum):
    """Which MF-27 pattern applies. One variant per roof."""
    FIVE = "five"    # Dens-Deck over insulation of at least 40 mm: 5 per 4x8 board
    EIGHT = "eight"  # re-roof, polyiso under 40 mm: 8 per 4x8 board


# Fastener positions in inches from the board corner: (across x, along y).
_PATTERN_IN = {
    PatternVariant.FIVE: [(12, 12), (36, 12), (24, 48), (12, 84), (36, 84)],
    PatternVariant.EIGHT: [(x, y) for y in (12, 36, 60, 84) for x in (12, 36)],
}


def board_pattern_mm(variant: PatternVariant) -> list[tuple[float, float]]:
    """Fastener positions on one 4 x 8 ft board, in mm from its corner."""
    return [(x * IN, y * IN) for x, y in _PATTERN_IN[variant]]


@dataclass(frozen=True)
class RoofSpec:
    """The schematic, for a rectangular roof."""
    width_mm: float                         # across the flutes
    length_mm: float                        # along the flutes
    variant: PatternVariant = PatternVariant.FIVE
    setback_mm: float = 0.0                 # gap between the roof edge and the first board
    flute_pitch_mm: Optional[float] = None  # crest to crest. Placeholder until measured
    # x of one crest, so crests sit at phase + k * pitch. None means a crest lies under the board
    # edges, which is what the installation guide asks for (edge joints on a top flute).
    crest_phase_mm: Optional[float] = None


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
    entry_y_mm: float          # the roof edge the robot enters from (0 or the roof length)
    crests_to_next: Optional[int]  # crests crossed to reach the next row, None for the last row

    def distances_mm(self) -> list[float]:
        """Travel to spot 1 from the entry edge, then spot to spot."""
        out, here = [], self.entry_y_mm
        for s in self.spots:
            out.append(abs(s.y_mm - here))
            here = s.y_mm
        return out


@dataclass(frozen=True)
class Layout:
    rows: tuple[PlannedRow, ...]
    boards_across: int
    boards_along: int
    crest_phase_mm: float = 0.0               # the phase actually used
    board_origin_mm: tuple[float, float] = (0.0, 0.0)  # corner of the first whole board

    @property
    def waypoints(self) -> list[Waypoint]:
        return [s for r in self.rows for s in r.spots]

    @property
    def total_spots(self) -> int:
        return sum(len(r.spots) for r in self.rows)


def _snap(x: float, pitch: Optional[float], phase: float) -> float:
    if pitch is None:
        return x
    return phase + round((x - phase) / pitch) * pitch


def plan(spec: RoofSpec) -> Layout:
    """Tile whole boards, stamp the fastener pattern and order the rows."""
    if spec.width_mm <= 0 or spec.length_mm <= 0:
        raise ValueError("roof dimensions must be positive")
    if spec.setback_mm < 0:
        raise ValueError("setback cannot be negative")
    if spec.flute_pitch_mm is not None and spec.flute_pitch_mm <= 0:
        raise ValueError("flute pitch must be positive")

    usable_w = spec.width_mm - 2 * spec.setback_mm
    usable_l = spec.length_mm - 2 * spec.setback_mm
    across = int(math.floor(usable_w / BOARD_WIDTH_MM + 1e-9))
    along = int(math.floor(usable_l / BOARD_LENGTH_MM + 1e-9))
    if across < 1 or along < 1:
        raise ValueError("the roof is too small for one whole board")

    # Centre the whole boards in the usable area, so leftovers split evenly.
    x0 = spec.setback_mm + (usable_w - across * BOARD_WIDTH_MM) / 2
    y0 = spec.setback_mm + (usable_l - along * BOARD_LENGTH_MM) / 2

    phase = spec.crest_phase_mm
    if phase is None:
        phase = x0 % spec.flute_pitch_mm if spec.flute_pitch_mm else 0.0

    # Group by the spec's x so rows stay together, then snap each row once.
    by_line: dict[float, list[float]] = {}
    for bi in range(across):
        for bj in range(along):
            for px, py in board_pattern_mm(spec.variant):
                key = round(x0 + bi * BOARD_WIDTH_MM + px, 3)
                by_line.setdefault(key, []).append(round(y0 + bj * BOARD_LENGTH_MM + py, 3))

    keys = sorted(by_line)
    rows: list[PlannedRow] = []
    for n, key in enumerate(keys, start=1):
        forward = n % 2 == 1
        heading = 90.0 if forward else 270.0
        ys = sorted(by_line[key], reverse=not forward)
        x = _snap(key, spec.flute_pitch_mm, phase)
        offset = x - key if spec.flute_pitch_mm is not None else 0.0
        spots = tuple(Waypoint(n, i, x, y, heading, offset) for i, y in enumerate(ys, start=1))
        crests = None
        if n < len(keys):
            nxt = _snap(keys[n], spec.flute_pitch_mm, phase)
            if spec.flute_pitch_mm is not None:
                crests = round((nxt - x) / spec.flute_pitch_mm)
        rows.append(PlannedRow(n, x, heading, spots, 0.0 if forward else spec.length_mm, crests))
    return Layout(tuple(rows), across, along, phase, (x0, y0))
