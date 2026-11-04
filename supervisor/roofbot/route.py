"""The route map: rows, spots per row, and distances."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class RowPlan:
    spots: int
    spacing_mm: float
    start_offset_mm: float = 0.0  # distance from where the robot arrives to spot 1


class Route:
    """Rows and spots are numbered from 1."""

    def __init__(self, rows: Sequence[RowPlan]):
        if not rows:
            raise ValueError("route needs at least one row")
        for i, row in enumerate(rows, start=1):
            if row.spots < 1:
                raise ValueError(f"row {i} needs at least one spot")
        self.rows = list(rows)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def spots_in_row(self, row: int) -> int:
        return self.rows[row - 1].spots

    def distance_to_spot_mm(self, row: int, spot: int) -> float:
        plan = self.rows[row - 1]
        return plan.start_offset_mm if spot == 1 else plan.spacing_mm

    def turn_direction(self, row: int) -> str:
        """Right twice at the end of row 1, left twice at the end of row 2, and so on."""
        return "RIGHT" if row % 2 == 1 else "LEFT"

    @property
    def total_spots(self) -> int:
        return sum(r.spots for r in self.rows)
