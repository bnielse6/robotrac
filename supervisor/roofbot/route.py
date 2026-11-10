"""The route map: rows, spots per row, and distances."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class RowPlan:
    spots: int
    spacing_mm: float
    start_offset_mm: float = 0.0  # distance from where the robot arrives to spot 1
    # Optional explicit travel to each spot, one per spot: to spot 1 from where the robot arrives,
    # then spot to spot. Used for planned layouts, where the spacing is uneven. When given it
    # replaces spacing_mm and start_offset_mm. Signed: negative means reverse (the robot can back
    # up, which the 5-screw pattern needs at the start of its middle column).
    distances_mm: Optional[tuple[float, ...]] = None
    # The row change AFTER this row (None for the last row, or when not known): how many crests the
    # robot crosses and how far sideways it goes, so Locomotion can check its crest count against its
    # encoder.
    turn_crests: Optional[int] = None
    turn_shift_mm: Optional[float] = None
    # Before turning, drive on this far past the last spot (0 = turn at the spot). It is how the next
    # row's first spot ends up ahead of the robot, so it need not reverse.
    turn_run_out_mm: float = 0.0


class Route:
    """Rows and spots are numbered from 1."""

    def __init__(self, rows: Sequence[RowPlan]):
        if not rows:
            raise ValueError("route needs at least one row")
        for i, row in enumerate(rows, start=1):
            if row.spots < 1:
                raise ValueError(f"row {i} needs at least one spot")
            if row.distances_mm is not None and len(row.distances_mm) != row.spots:
                raise ValueError(f"row {i} has {row.spots} spots but {len(row.distances_mm)} distances")
        self.rows = list(rows)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def spots_in_row(self, row: int) -> int:
        return self.rows[row - 1].spots

    def distance_to_spot_mm(self, row: int, spot: int) -> float:
        plan = self.rows[row - 1]
        if plan.distances_mm is not None:
            return plan.distances_mm[spot - 1]
        return plan.start_offset_mm if spot == 1 else plan.spacing_mm

    def turn_params(self, row: int) -> dict:
        """What the TURN command after `row` carries besides the direction (empty when not known)."""
        plan = self.rows[row - 1]
        out: dict = {}
        if plan.turn_crests is not None:
            out["crests"] = plan.turn_crests
        if plan.turn_shift_mm is not None:
            out["distance_mm"] = plan.turn_shift_mm
        if plan.turn_run_out_mm > 1e-6:
            out["run_out_mm"] = plan.turn_run_out_mm
        return out

    def turn_direction(self, row: int) -> str:
        """Right twice at the end of row 1, left twice at the end of row 2, and so on."""
        return "RIGHT" if row % 2 == 1 else "LEFT"

    @property
    def total_spots(self) -> int:
        return sum(r.spots for r in self.rows)
