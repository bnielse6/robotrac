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

from .planner import Layout, RoofSpec, board_size_mm

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
  .reverse { fill: none; stroke: #d97706; stroke-width: var(--line-medium); stroke-dasharray: var(--dash); }
  .arrow-reverse { fill: #d97706; }
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

    # at least wide enough for the legend text, so it is not cut off on a narrow roof
    vb_w = max(W + 2 * margin, text * 62)
    vb_h = L + 2 * margin + text * (4 + 1.3 * len(layout.warnings))
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

    poly = spec.outline
    shape = " ".join(f"{_f(X(x))},{_f(Y(y))}" for x, y in poly) if poly else ""
    if poly:
        out.append(f'<defs><clipPath id="roofshape"><polygon points="{shape}"/></clipPath></defs>')
        out.append(f'<g id="deck"><polygon class="deck" points="{shape}"/></g>')
    else:
        out.append(f'<g id="deck"><rect class="deck" x="{_f(X(0))}" y="{_f(Y(L))}" '
                   f'width="{_f(W)}" height="{_f(L)}"/></g>')

    out.append('<g id="flutes" clip-path="url(#roofshape)">' if poly else '<g id="flutes">')
    if spec.crest_xs_mm:        # the real crest lines from a schematic
        crest_lines = list(spec.crest_xs_mm)
    elif spec.flute_pitch_mm:   # an even pitch
        crest_lines, x = [], layout.crest_phase_mm % spec.flute_pitch_mm
        while x <= W + 1e-6:
            crest_lines.append(x)
            x += spec.flute_pitch_mm
    else:
        crest_lines = []
    for x in crest_lines:
        out.append(f'<line class="flute" x1="{_f(X(x))}" y1="{_f(Y(0))}" '
                   f'x2="{_f(X(x))}" y2="{_f(Y(L))}"/>')
    out.append("</g>")

    out.append('<g id="boards">')
    bw, bl = board_size_mm(spec.variant)
    for bx, by in layout.boards:
        out.append(f'<rect class="board" x="{_f(X(bx))}" y="{_f(Y(by + bl))}" '
                   f'width="{_f(bw)}" height="{_f(bl)}"/>')
    out.append("</g>")

    if poly:
        out.append(f'<g id="outline"><polygon class="outline" points="{shape}"/></g>')
    else:
        out.append(f'<g id="outline"><rect class="outline" x="{_f(X(0))}" y="{_f(Y(L))}" '
                   f'width="{_f(W)}" height="{_f(L)}"/></g>')

    out.append('<g id="rows">')
    prev = None
    for row in layout.rows:
        exit_y = row.exit_y_mm if row.exit_y_mm is not None else (L if row.heading_deg == 90.0 else 0.0)
        if prev is not None:   # the turn: straight across to the next row, level with the last spot
            out.append(f'<line class="turn" x1="{_f(X(prev.x_mm))}" y1="{_f(Y(row.entry_y_mm))}" '
                       f'x2="{_f(X(row.x_mm))}" y2="{_f(Y(row.entry_y_mm))}"/>')
        sign = 1 if row.heading_deg == 90.0 else -1
        y0 = row.spots[0].y_mm
        reversing = row.distances_mm()[0] < -1e-6
        start_y = y0 if reversing else row.entry_y_mm    # the forward run starts at the first spot
        if reversing:
            # The first spot is behind the robot after the turn (the middle column of the 5-screw
            # pattern), so it backs up to it: an orange dashed leg from the turn level to spot 1,
            # with an arrowhead pointing the way it reverses (against the row's heading).
            rx = X(row.x_mm) + r_spot * 1.6      # drawn just beside the row, because it is the same track
            out.append(f'<line class="reverse" id="reverse-{row.row}" x1="{_f(rx)}" '
                       f'y1="{_f(Y(row.entry_y_mm))}" x2="{_f(rx)}" y2="{_f(Y(y0))}"/>')
            ry = (row.entry_y_mm + y0) / 2
            rd = r_spot * 2.2 * -sign
            out.append(f'<polygon class="arrow-reverse" points="{_f(rx - r_spot * 1.3)},{_f(Y(ry))} '
                       f'{_f(rx + r_spot * 1.3)},{_f(Y(ry))} {_f(rx)},{_f(Y(ry + rd))}"/>')
        end_y = exit_y + sign * row.run_out_mm    # the strip runs on to the turn level after its last spot
        out.append(f'<line class="row" id="row-{row.row}" x1="{_f(X(row.x_mm))}" y1="{_f(Y(start_y))}" '
                   f'x2="{_f(X(row.x_mm))}" y2="{_f(Y(end_y))}"/>')
        # an arrowhead pointing the way the robot travels: between the first two spots, or just past
        # the only spot of a one-spot row
        ay = (y0 + row.spots[1].y_mm) / 2 if len(row.spots) > 1 else y0 + sign * r_spot * 4
        d = r_spot * 2.2 * sign
        out.append(f'<polygon class="arrow" points="{_f(X(row.x_mm) - r_spot * 1.3)},{_f(Y(ay))} '
                   f'{_f(X(row.x_mm) + r_spot * 1.3)},{_f(Y(ay))} {_f(X(row.x_mm))},{_f(Y(ay + d))}"/>')
        prev = row
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
    first = layout.rows[0]   # the robot is put down at the start of row 1
    out.append(f'<circle class="start" cx="{_f(X(first.x_mm))}" cy="{_f(Y(first.entry_y_mm))}" r="{_f(r_spot * 1.4)}"/>')
    out.append(f'<text class="small" x="{_f(X(first.x_mm) + r_spot * 2)}" y="{_f(Y(first.entry_y_mm) + text)}">start</text>')
    for row in layout.rows:
        up = row.heading_deg == 90.0          # the row ends at its upper end, so label above it
        top = row.exit_y_mm if row.exit_y_mm is not None else (L if up else 0.0)
        top += row.run_out_mm if up else -row.run_out_mm     # label the end of the strip, where it turns
        ty = Y(top) + (-(r_spot * 1.8 + text * 0.3) if up else r_spot * 1.8 + text * 1.0)
        out.append(f'<text class="label" text-anchor="middle" x="{_f(X(row.x_mm))}" y="{_f(ty)}">R{row.row}</text>')
        if row.crests_to_next is not None:
            mid_x = X(row.x_mm) + (X(layout.rows[row.row].x_mm) - X(row.x_mm)) / 2
            out.append(f'<text class="small" text-anchor="middle" x="{_f(mid_x)}" '
                       f'y="{_f(Y(top) + (-(r_spot * 1.8 + text * 1.5) if up else r_spot * 1.8 + text * 2.2))}">'
                       f'{row.crests_to_next} crests</text>')
    for row in layout.rows:
        for s in row.spots:
            out.append(f'<text class="small" x="{_f(X(s.x_mm) + r_spot * 1.4)}" y="{_f(Y(s.y_mm) - r_spot * 0.8)}">'
                       f'{s.spot}</text>')
    if spec.crest_xs_mm:
        pitch = f"{len(spec.crest_xs_mm)} crest lines from the schematic"
    else:
        pitch = f"{spec.flute_pitch_mm / 25.4:.2f} in" if spec.flute_pitch_mm else "not set"
    shape_name = "custom shape, bounding box " if poly else ""
    legend = (f"{shape_name}{W / 1000:.2f} x {L / 1000:.2f} m, {spec.variant.value} variant, crests: {pitch}, "
              f"{len(layout.boards)} boards")
    out.append(f'<text class="label" x="{_f(margin)}" y="{_f(vb_h - text * 1.2)}">{escape(legend)}</text>')
    out.append(f'<text class="small" x="{_f(margin)}" y="{_f(vb_h - text * 0.2)}">'
               f'red = on crest, amber = offset from crest (grey ring = spec position), '
               f'dashed = board, arrows = travel, orange dashed = reverse</text>')
    for i, w in enumerate(layout.warnings):
        out.append(f'<text class="small" style="fill:#b45309" x="{_f(margin)}" '
                   f'y="{_f(vb_h - text * 2.4 - text * 1.3 * (len(layout.warnings) - 1 - i))}">'
                   f'Warning: {escape(w)}</text>')
    out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)
