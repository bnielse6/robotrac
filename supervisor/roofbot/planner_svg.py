"""Draw a planner `Layout` as an SVG, to check the plan by eye and to restyle by hand.

Pure: `layout_to_svg(spec, layout)` returns the SVG text and does no I/O. `plan_preview.py`
writes it to a file.

Editing the picture. The drawing is to scale, 1 SVG unit = 1 mm, with the start corner at the
bottom left and the flutes running up the page. Each kind of thing sits in its own named group, so
Inkscape or a browser's dev tools can select, hide or restyle a whole layer:

    outline  deck  flutes  boards  rows  spots  labels

All the colours and line widths are in one <style> block at the top, as CSS classes. To make it look
more like a roof, change that block. The edits are one way: nothing reads an edited SVG back.
"""
from __future__ import annotations

from xml.sax.saxutils import escape

from .planner import BOARD_LENGTH_MM, BOARD_WIDTH_MM, Layout, RoofSpec

_CSS = """
  .outline { fill: none; stroke: #2b2b2b; stroke-width: var(--line-heavy); }
  .deck { fill: #e9ecef; }
  .flute { stroke: #9aa3ad; stroke-width: var(--line-light); }
  .board { fill: none; stroke: #5b7fa6; stroke-width: var(--line-medium); stroke-dasharray: var(--dash); }
  .row { fill: none; stroke: #1b6ca8; stroke-width: var(--line-medium); }
  .turn { fill: none; stroke: #1b6ca8; stroke-width: var(--line-medium); stroke-dasharray: var(--dash); }
  .spot { fill: #d1495b; stroke: #ffffff; stroke-width: var(--line-light); }
  .spot.off-crest { fill: #edae49; }
  .nominal { fill: none; stroke: #7a7a7a; stroke-width: var(--line-light); }
  .offset { stroke: #7a7a7a; stroke-width: var(--line-light); }
  .start { fill: #2e933c; }
  .label { font-family: sans-serif; font-size: var(--text); fill: #1f1f1f; }
  .small { font-family: sans-serif; font-size: calc(var(--text) * 0.7); fill: #444444; }
  .arrow { fill: #1b6ca8; }
"""


def _f(v: float) -> str:
    return f"{v:.1f}"


def layout_to_svg(spec: RoofSpec, layout: Layout, max_px: int = 900) -> str:
    W, L = spec.width_mm, spec.length_mm
    unit = max(W, L)
    text = unit / 70           # base text size in mm
    r_spot = unit / 160
    margin = unit / 12

    def X(x: float) -> float:
        return x + margin

    def Y(y: float) -> float:   # flip so y grows up the page
        return margin + (L - y)

    vb_w, vb_h = W + 2 * margin, L + 2 * margin + text * 4
    scale = max_px / max(vb_w, vb_h)
    out: list[str] = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_f(vb_w)} {_f(vb_h)}" '
        f'width="{_f(vb_w * scale)}" height="{_f(vb_h * scale)}">'
    )
    out.append(f"<title>Roof plan, {layout.total_spots} spots, {len(layout.rows)} rows</title>")
    out.append(
        f"<style>:root {{ --line-heavy: {_f(unit / 250)}; --line-medium: {_f(unit / 450)}; "
        f"--line-light: {_f(unit / 900)}; --dash: {_f(unit / 120)} {_f(unit / 200)}; "
        f"--text: {_f(text)}px; }}{_CSS}</style>"
    )

    out.append(f'<g id="deck"><rect class="deck" x="{_f(X(0))}" y="{_f(Y(L))}" '
               f'width="{_f(W)}" height="{_f(L)}"/></g>')

    out.append('<g id="flutes">')
    if spec.flute_pitch_mm:
        p, k = spec.flute_pitch_mm, 0
        x = layout.crest_phase_mm % p
        while x <= W + 1e-6:
            out.append(f'<line class="flute" x1="{_f(X(x))}" y1="{_f(Y(0))}" '
                       f'x2="{_f(X(x))}" y2="{_f(Y(L))}"/>')
            x += p
            k += 1
    out.append("</g>")

    out.append('<g id="boards">')
    if layout.boards_across and layout.boards_along:
        x0, y0 = layout.board_origin_mm
        for bi in range(layout.boards_across):
            for bj in range(layout.boards_along):
                bx, by = x0 + bi * BOARD_WIDTH_MM, y0 + bj * BOARD_LENGTH_MM
                out.append(f'<rect class="board" x="{_f(X(bx))}" y="{_f(Y(by + BOARD_LENGTH_MM))}" '
                           f'width="{_f(BOARD_WIDTH_MM)}" height="{_f(BOARD_LENGTH_MM)}"/>')
    out.append("</g>")

    out.append(f'<g id="outline"><rect class="outline" x="{_f(X(0))}" y="{_f(Y(L))}" '
               f'width="{_f(W)}" height="{_f(L)}"/></g>')

    out.append('<g id="rows">')
    prev_exit = (0.0, 0.0)  # the robot starts at the corner
    for row in layout.rows:
        exit_y = L if row.heading_deg == 90.0 else 0.0
        out.append(f'<line class="turn" x1="{_f(X(prev_exit[0]))}" y1="{_f(Y(prev_exit[1]))}" '
                   f'x2="{_f(X(row.x_mm))}" y2="{_f(Y(row.entry_y_mm))}"/>')
        out.append(f'<line class="row" id="row-{row.row}" x1="{_f(X(row.x_mm))}" y1="{_f(Y(row.entry_y_mm))}" '
                   f'x2="{_f(X(row.x_mm))}" y2="{_f(Y(exit_y))}"/>')
        # an arrowhead midway between the entry edge and the first spot, pointing the way it travels
        ay = (row.entry_y_mm + row.spots[0].y_mm) / 2
        d = r_spot * 2.2 * (1 if row.heading_deg == 90.0 else -1)
        out.append(f'<polygon class="arrow" points="{_f(X(row.x_mm) - r_spot * 1.3)},{_f(Y(ay))} '
                   f'{_f(X(row.x_mm) + r_spot * 1.3)},{_f(Y(ay))} {_f(X(row.x_mm))},{_f(Y(ay + d))}"/>')
        prev_exit = (row.x_mm, exit_y)
    out.append("</g>")

    out.append('<g id="spots">')
    for row in layout.rows:
        for s in row.spots:
            off = abs(s.crest_offset_mm) > 0.5
            if off:
                nx = s.x_mm - s.crest_offset_mm
                out.append(f'<line class="offset" x1="{_f(X(nx))}" y1="{_f(Y(s.y_mm))}" '
                           f'x2="{_f(X(s.x_mm))}" y2="{_f(Y(s.y_mm))}"/>')
                out.append(f'<circle class="nominal" cx="{_f(X(nx))}" cy="{_f(Y(s.y_mm))}" r="{_f(r_spot * 0.7)}"/>')
            cls = "spot off-crest" if off else "spot"
            out.append(f'<circle class="{cls}" id="spot-{s.row}-{s.spot}" cx="{_f(X(s.x_mm))}" '
                       f'cy="{_f(Y(s.y_mm))}" r="{_f(r_spot)}"/>')
    out.append("</g>")

    out.append('<g id="labels">')
    out.append(f'<circle class="start" cx="{_f(X(0))}" cy="{_f(Y(0))}" r="{_f(r_spot * 1.4)}"/>')
    out.append(f'<text class="small" x="{_f(X(0) + r_spot * 2)}" y="{_f(Y(0) + text)}">start corner</text>')
    for row in layout.rows:
        top = L if row.heading_deg == 90.0 else 0.0
        ty = Y(top) + (-text * 0.5 if top == L else text * 1.2)
        out.append(f'<text class="label" text-anchor="middle" x="{_f(X(row.x_mm))}" y="{_f(ty)}">R{row.row}</text>')
        if row.crests_to_next is not None:
            mid_x = X(row.x_mm) + (X(layout.rows[row.row].x_mm) - X(row.x_mm)) / 2
            out.append(f'<text class="small" text-anchor="middle" x="{_f(mid_x)}" '
                       f'y="{_f(Y(top) + (-text * 1.6 if top == L else text * 2.4))}">'
                       f'{row.crests_to_next} crests</text>')
    for row in layout.rows:
        for s in row.spots:
            out.append(f'<text class="small" x="{_f(X(s.x_mm) + r_spot * 1.4)}" y="{_f(Y(s.y_mm) - r_spot * 0.8)}">'
                       f'{s.spot}</text>')
    pitch = f"{spec.flute_pitch_mm / 25.4:.2f} in" if spec.flute_pitch_mm else "not set"
    legend = (f"{W / 1000:.2f} x {L / 1000:.2f} m, {spec.variant.value} variant, flute pitch {pitch}, "
              f"{layout.boards_across} x {layout.boards_along} boards")
    out.append(f'<text class="label" x="{_f(margin)}" y="{_f(vb_h - text * 1.2)}">{escape(legend)}</text>')
    out.append(f'<text class="small" x="{_f(margin)}" y="{_f(vb_h - text * 0.2)}">'
               f'red = on crest, amber = offset from crest (grey ring = spec position), '
               f'dashed = board, arrows = travel</text>')
    out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)
