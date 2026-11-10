"""Read a roof schematic file (SVG or DXF) into a roof outline and the real crest positions.

Pure functions, no I/O: `parse_schematic(text)` takes the file's text. The result feeds
`RoofSpec.from_outline(outline, crest_xs_mm=crest_xs)`.

What the file must contain
  * the roof outline: one closed shape (polygon, closed polyline, rectangle, or a closed path of
    straight sides);
  * the crest lines: straight lines that run along the flutes, one per crest (or, with
    crest_lines="pairs", two per crest, one on each edge of the crest).

How shapes are told apart
  1. By name. In SVG the element id, class, `inkscape:label` or `data-name` (and those of its
     groups); in DXF the layer name. A name containing outline, roof, perimeter, boundary or edge
     marks the roof outline. A name containing flute, crest, ridge, rib or corrugation marks a crest line.
  2. If nothing is named: the largest closed shape is the outline, and every straight line that is
     parallel to the most common line direction and at least half as long as the roof is a crest line.

Directions and units. Crest lines are rotated to run up the page (+y), whatever angle they were drawn
at. SVG's y axis points down, so it is flipped. Units come from the file when it says (SVG
width/height or viewBox, DXF $INSUNITS); otherwise pass `unit_mm`, the size of one drawing unit.
Curves are not supported: draw the outline with straight sides.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

Point = tuple[float, float]
Segment = tuple[Point, Point]

OUTLINE_WORDS = ("outline", "roof", "perimeter", "boundary", "edge")
CREST_WORDS = ("flute", "crest", "ridge", "rib", "corrugation")
_SVG_UNITS_MM = {"": 25.4 / 96, "px": 25.4 / 96, "pt": 25.4 / 72, "pc": 25.4 / 6, "mm": 1.0, "cm": 10.0, "in": 25.4}
_DXF_UNITS_MM = {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0}   # $INSUNITS codes


class SchematicError(ValueError):
    """The file could not be understood. The message says what to change."""


@dataclass
class Schematic:
    outline_mm: list[Point]                  # roof corners, moved so the lowest-left corner is (0, 0)
    crest_xs_mm: list[float]                 # x of each crest in the same frame. Empty if none were found
    pitch_mm: Optional[float] = None         # median crest spacing, for information
    angle_deg: float = 0.0                   # how far the drawing was turned to put the crests along +y
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- small geometry helpers

def _area2(pts: list[Point]) -> float:
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts)))


def _angle180(seg: Segment) -> float:
    """Direction of a segment in degrees, 0 to 180."""
    return math.degrees(math.atan2(seg[1][1] - seg[0][1], seg[1][0] - seg[0][0])) % 180.0


def _length(seg: Segment) -> float:
    return math.hypot(seg[1][0] - seg[0][0], seg[1][1] - seg[0][1])


def _dedupe(points: list[Point]) -> list[Point]:
    out: list[Point] = []
    for p in points:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= 1e-6:
        out.pop()
    return out


# ---------------------------------------------------------------- shapes found in a file

@dataclass
class _Shape:
    points: list[Point]
    closed: bool
    label: str = ""


def _is_crest_name(label: str) -> bool:
    return any(w in label for w in CREST_WORDS)


def _is_outline_name(label: str) -> bool:
    # "edge" also appears in names like "flute-edges", so a crest name never counts as the outline
    return any(w in label for w in OUTLINE_WORDS) and not _is_crest_name(label)


# ---------------------------------------------------------------- SVG

def _num(s: str) -> float:
    return float(s)


def _parse_transform(text: Optional[str]) -> tuple[float, float, float, float, float, float]:
    """An SVG transform attribute as a matrix (a, b, c, d, e, f)."""
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not text:
        return m

    def mul(p, q):
        return (p[0] * q[0] + p[2] * q[1], p[1] * q[0] + p[3] * q[1],
                p[0] * q[2] + p[2] * q[3], p[1] * q[2] + p[3] * q[3],
                p[0] * q[4] + p[2] * q[5] + p[4], p[1] * q[4] + p[3] * q[5] + p[5])

    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", text):
        a = [_num(x) for x in re.split(r"[\s,]+", args.strip()) if x]
        if name == "translate":
            t = (1, 0, 0, 1, a[0], a[1] if len(a) > 1 else 0.0)
        elif name == "scale":
            t = (a[0], 0, 0, a[1] if len(a) > 1 else a[0], 0, 0)
        elif name == "rotate":
            c, s = math.cos(math.radians(a[0])), math.sin(math.radians(a[0]))
            t = (c, s, -s, c, 0, 0)
            if len(a) == 3:
                t = mul(mul((1, 0, 0, 1, a[1], a[2]), t), (1, 0, 0, 1, -a[1], -a[2]))
        elif name == "matrix" and len(a) == 6:
            t = tuple(a)
        else:
            raise SchematicError(f"the SVG transform '{name}' is not supported; "
                                 "use translate, scale, rotate or matrix, or flatten the drawing")
        m = mul(m, t)
    return m


def _apply(m, p: Point) -> Point:
    return (m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5])


def _parse_path(d: str) -> list[tuple[list[Point], bool]]:
    """Subpaths of straight sides from an SVG path. Curves raise SchematicError."""
    tokens = re.findall(r"[MmLlHhVvZzCcSsQqTtAa]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
    out: list[tuple[list[Point], bool]] = []
    pts: list[Point] = []
    cur = start = (0.0, 0.0)
    cmd, i = "", 0

    def take(n: int) -> list[float]:
        nonlocal i
        vals = [_num(t) for t in tokens[i:i + n]]
        if len(vals) < n:
            raise SchematicError("an SVG path ends in the middle of a command")
        i += n
        return vals

    while i < len(tokens):
        if re.fullmatch(r"[A-Za-z]", tokens[i]):
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                if pts:
                    out.append((pts, True))
                    pts = []
                cur = start
                continue
        if cmd in "CcSsQqTtAa":
            raise SchematicError("the SVG contains curves, which are not supported. "
                                 "Draw the roof outline and crest lines with straight sides")
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            x, y = take(2)
            cur = (cur[0] + x, cur[1] + y) if rel else (x, y)
            if pts:
                out.append((pts, False))
            pts, start = [cur], cur
            cmd = "l" if rel else "L"          # further pairs after a move are line-tos
        elif c == "L":
            x, y = take(2)
            cur = (cur[0] + x, cur[1] + y) if rel else (x, y)
            pts.append(cur)
        elif c == "H":
            (x,) = take(1)
            cur = (cur[0] + x, cur[1]) if rel else (x, cur[1])
            pts.append(cur)
        elif c == "V":
            (y,) = take(1)
            cur = (cur[0], cur[1] + y) if rel else (cur[0], y)
            pts.append(cur)
        else:
            raise SchematicError(f"unexpected '{tokens[i]}' in an SVG path")
    if pts:
        out.append((pts, False))
    return out


def _svg_scale_mm(root: ET.Element, unit_mm: Optional[float], notes: list[str]) -> float:
    """Millimetres per SVG user unit."""
    if unit_mm is not None:
        return unit_mm
    w, vb = root.get("width"), root.get("viewBox")
    if w and vb:
        m = re.fullmatch(r"\s*([\d.]+)\s*([a-z%]*)\s*", w)
        parts = re.split(r"[\s,]+", vb.strip())
        if m and m.group(2) in _SVG_UNITS_MM and len(parts) == 4 and float(parts[2]) > 0:
            scale = float(m.group(1)) * _SVG_UNITS_MM[m.group(2)] / float(parts[2])
            notes.append(f"Drawing units taken from the file: 1 unit = {scale:.4g} mm.")
            return scale
    notes.append("The file gives no real-world size, so 1 drawing unit is taken as 1 mm. "
                 "Set the drawing units if that is wrong.")
    return 1.0


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _svg_shapes(text: str, unit_mm: Optional[float], notes: list[str]) -> list[_Shape]:
    if re.search(r"<!ENTITY", text, re.IGNORECASE):
        raise SchematicError("this SVG declares entities, which are not accepted")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SchematicError(f"the file is not valid SVG: {exc}") from exc
    if _local(root.tag) != "svg":
        raise SchematicError("the file is XML but not an SVG")
    scale = _svg_scale_mm(root, unit_mm, notes)
    shapes: list[_Shape] = []

    def label_of(el: ET.Element) -> str:
        parts = [el.get("id", ""), el.get("class", ""), el.get("data-name", "")]
        parts += [v for k, v in el.attrib.items() if k.endswith("}label")]
        return " ".join(parts).lower()

    def walk(el: ET.Element, matrix, inherited: str) -> None:
        tag = _local(el.tag)
        if tag in ("defs", "clipPath", "mask", "symbol", "marker", "pattern", "metadata", "style", "title", "desc"):
            return
        m = _mul_matrix(matrix, _parse_transform(el.get("transform")))
        label = (inherited + " " + label_of(el)).strip()
        pts_sets: list[tuple[list[Point], bool]] = []
        if tag == "line":
            pts_sets = [([(float(el.get("x1", 0)), float(el.get("y1", 0))),
                          (float(el.get("x2", 0)), float(el.get("y2", 0)))], False)]
        elif tag in ("polyline", "polygon"):
            nums = [_num(x) for x in re.split(r"[\s,]+", (el.get("points") or "").strip()) if x]
            pts_sets = [(list(zip(nums[0::2], nums[1::2])), tag == "polygon")]
        elif tag == "rect":
            x, y, w, h = (float(el.get(k, 0)) for k in ("x", "y", "width", "height"))
            if w > 0 and h > 0:
                pts_sets = [([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)]
        elif tag == "path":
            pts_sets = _parse_path(el.get("d") or "")
        for pts, closed in pts_sets:
            if len(pts) >= 2:
                shapes.append(_Shape([(_apply(m, p)[0] * scale, -_apply(m, p)[1] * scale) for p in pts], closed, label))
        for child in el:
            walk(child, m, label)

    walk(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), "")
    return shapes


def _mul_matrix(p, q):
    return (p[0] * q[0] + p[2] * q[1], p[1] * q[0] + p[3] * q[1],
            p[0] * q[2] + p[2] * q[3], p[1] * q[2] + p[3] * q[3],
            p[0] * q[4] + p[2] * q[5] + p[4], p[1] * q[4] + p[3] * q[5] + p[5])


# ---------------------------------------------------------------- DXF

def _dxf_pairs(text: str) -> list[tuple[int, str]]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if len(lines) < 4:
        raise SchematicError("the file is too short to be a DXF")
    pairs = []
    for i in range(0, len(lines) - 1, 2):
        try:
            pairs.append((int(lines[i].strip()), lines[i + 1].strip()))
        except ValueError as exc:
            raise SchematicError("the file is not an ASCII DXF (save it as ASCII DXF, not binary)") from exc
    return pairs


def _dxf_shapes(text: str, unit_mm: Optional[float], notes: list[str]) -> list[_Shape]:
    pairs = _dxf_pairs(text)
    scale = unit_mm
    for k, (code, val) in enumerate(pairs):                      # the header says what the units are
        if code == 9 and val == "$INSUNITS" and k + 1 < len(pairs):
            try:
                scale_file = _DXF_UNITS_MM.get(int(pairs[k + 1][1]))
            except ValueError:
                scale_file = None
            if scale is None and scale_file:
                scale = scale_file
                notes.append(f"Drawing units taken from the file: 1 unit = {scale:g} mm.")
    if scale is None:
        scale = 1.0
        notes.append("The DXF gives no units, so 1 drawing unit is taken as 1 mm. Set the drawing units if that is wrong.")

    shapes: list[_Shape] = []
    in_entities, i = False, 0
    while i < len(pairs):
        code, val = pairs[i]
        if code == 2 and val == "ENTITIES":
            in_entities = True
        elif code == 0 and val == "ENDSEC":
            in_entities = False
        if in_entities and code == 0 and val in ("LINE", "LWPOLYLINE", "POLYLINE"):
            kind, j = val, i + 1
            layer, closed, bulge = "", False, False
            xs: list[float] = []
            pts: list[Point] = []
            x1 = y1 = x2 = y2 = 0.0
            if kind == "POLYLINE":
                # old style: the vertices are separate VERTEX entities up to SEQEND
                flags = 0
                while j < len(pairs) and not (pairs[j][0] == 0 and pairs[j][1] != "VERTEX"):
                    c, v = pairs[j]
                    if c == 8 and not pts:
                        layer = v
                    elif c == 70 and not pts:
                        flags = int(v)
                    elif c == 0 and v == "VERTEX":
                        vx = vy = 0.0
                        j += 1
                        while j < len(pairs) and pairs[j][0] != 0:
                            if pairs[j][0] == 10:
                                vx = float(pairs[j][1])
                            elif pairs[j][0] == 20:
                                vy = float(pairs[j][1])
                            j += 1
                        pts.append((vx, vy))
                        continue
                    j += 1
                closed = bool(flags & 1)
            else:
                while j < len(pairs) and pairs[j][0] != 0:
                    c, v = pairs[j]
                    if c == 8:
                        layer = v
                    elif c == 70:
                        closed = bool(int(v) & 1)
                    elif kind == "LINE":
                        if c == 10: x1 = float(v)
                        elif c == 20: y1 = float(v)
                        elif c == 11: x2 = float(v)
                        elif c == 21: y2 = float(v)
                    else:  # LWPOLYLINE: x then y, repeated
                        if c == 10: xs.append(float(v))
                        elif c == 20 and xs: pts.append((xs.pop(), float(v)))
                        elif c == 42 and abs(float(v)) > 1e-9: bulge = True
                    j += 1
            if kind == "LINE":
                pts = [(x1, y1), (x2, y2)]
            if bulge:
                raise SchematicError("the DXF has curved polyline sides (bulges), which are not supported")
            if len(pts) >= 2:
                shapes.append(_Shape([(x * scale, y * scale) for x, y in pts], closed, layer.lower()))
            i = j
            continue
        i += 1
    return shapes


# ---------------------------------------------------------------- picking the outline and crests

def _segments(shape: _Shape) -> list[Segment]:
    pts = shape.points
    segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    if shape.closed and len(pts) > 2:
        segs.append((pts[-1], pts[0]))
    return segs


def _pick(shapes: list[_Shape], notes: list[str]) -> tuple[list[Point], list[Segment]]:
    # closed shapes with more than two corners can be outlines; two-point shapes are lines
    closed = [s for s in shapes if len(_dedupe(s.points)) >= 3 and not _is_crest_name(s.label) and
              (s.closed or _is_outline_name(s.label) or
               math.hypot(s.points[0][0] - s.points[-1][0], s.points[0][1] - s.points[-1][1]) < 1e-6)]
    lines = [s for s in shapes if not any(s is c for c in closed)]

    named = [s for s in closed if _is_outline_name(s.label)]
    pool = named or closed
    if not pool:
        raise SchematicError("no roof outline found. Draw it as one closed shape, and name it "
                             "(for example id=\"roof-outline\", or a DXF layer called OUTLINE)")
    outline_shape = max(pool, key=lambda s: abs(_area2(_dedupe(s.points))))
    if not named and len(closed) > 1:
        notes.append("Several closed shapes and none named as the outline: the largest was used.")
    outline = _dedupe(outline_shape.points)

    # other closed shapes can still carry crest lines when they are named as crests
    crest_shapes = [s for s in shapes if s is not outline_shape and _is_crest_name(s.label)]
    segs: list[Segment] = []
    for s in crest_shapes:
        segs += _segments(s)
    if segs:
        return outline, [sg for sg in segs if _length(sg) > 1e-6]

    # nothing named as a crest: straight lines parallel to the commonest direction, long enough
    cands = [sg for s in lines for sg in _segments(s) if _length(sg) > 1e-6]
    if not cands:
        return outline, []
    bbox_len = max(max(p[0] for p in outline) - min(p[0] for p in outline),
                   max(p[1] for p in outline) - min(p[1] for p in outline))
    long_ones = [sg for sg in cands if _length(sg) >= 0.5 * bbox_len]
    if not long_ones:
        return outline, []
    ref = _dominant_angle(long_ones)
    picked = [sg for sg in long_ones if _angle_diff(_angle180(sg), ref) <= 2.0]
    notes.append(f"No lines were named as crests: {len(picked)} long parallel lines were taken as crest lines.")
    return outline, picked


def _angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def _dominant_angle(segs: list[Segment]) -> float:
    """The length-weighted most common direction, in degrees 0 to 180."""
    bins: dict[int, float] = {}
    for sg in segs:
        k = int(round(_angle180(sg))) % 180
        bins[k] = bins.get(k, 0.0) + _length(sg)
    best = max(bins, key=bins.get)
    members = [sg for sg in segs if _angle_diff(_angle180(sg), best) <= 2.0]
    # refine: the length-weighted mean of the members, taken around the best bin
    tot = sum(_length(sg) for sg in members)
    return best + sum(_length(sg) * ((_angle180(sg) - best + 90.0) % 180.0 - 90.0) for sg in members) / tot


def _rotate(p: Point, deg: float) -> Point:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def _cluster(values: list[float], tol: float) -> list[float]:
    out: list[list[float]] = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(g) / len(g) for g in out]


def parse_schematic(text: str, fmt: str = "auto", unit_mm: Optional[float] = None,
                    crest_lines: str = "centres") -> Schematic:
    """Turn the text of an SVG or ASCII DXF file into a `Schematic`.

    fmt: "svg", "dxf" or "auto" (decided from the text).
    unit_mm: the size of one drawing unit in millimetres, when the file does not say.
    crest_lines: "centres" (one line per crest) or "pairs" (two lines per crest, one on each edge).
    """
    if crest_lines not in ("centres", "pairs"):
        raise SchematicError("crest_lines must be 'centres' or 'pairs'")
    if unit_mm is not None and unit_mm <= 0:
        raise SchematicError("the drawing unit must be positive")
    head = text.lstrip()[:300].lower()
    if fmt == "auto":
        fmt = "svg" if ("<svg" in head or head.startswith("<?xml")) else "dxf"
    notes: list[str] = []
    if fmt == "svg":
        shapes = _svg_shapes(text, unit_mm, notes)
    elif fmt == "dxf":
        shapes = _dxf_shapes(text, unit_mm, notes)
    else:
        raise SchematicError("the file format must be svg or dxf")
    if not shapes:
        raise SchematicError("no lines or shapes were found in the file")

    outline, segs = _pick(shapes, notes)

    angle = 0.0
    if segs:
        ref = _dominant_angle(segs)
        angle = 90.0 - ref            # turn the crest lines to vertical
        if abs(angle) > 90.0:
            angle -= math.copysign(180.0, angle)
        if abs(angle) < 0.05:
            angle = 0.0
        if angle:
            notes.append(f"The drawing was turned {angle:.1f} degrees so the crest lines run up the page.")
    outline = [_rotate(p, angle) for p in outline]
    segs = [(_rotate(a, angle), _rotate(b, angle)) for a, b in segs]

    minx, miny = min(p[0] for p in outline), min(p[1] for p in outline)
    maxx = max(p[0] for p in outline)
    outline = [(x - minx, y - miny) for x, y in outline]

    xs: list[float] = []
    if segs:
        if any(_angle_diff(_angle180(sg), 90.0) > 2.0 for sg in segs):
            notes.append("Some crest lines are not parallel to the others (more than 2 degrees off) and were ignored.")
            segs = [sg for sg in segs if _angle_diff(_angle180(sg), 90.0) <= 2.0]
        xs = [((a[0] + b[0]) / 2) - minx for a, b in segs]
        xs = _cluster(xs, tol=1.0)                        # lines within 1 mm are the same line
        if crest_lines == "pairs":
            if len(xs) % 2:
                raise SchematicError(f"{len(xs)} crest lines found, but crest_lines is 'pairs' (two per crest)")
            xs = [(xs[i] + xs[i + 1]) / 2 for i in range(0, len(xs), 2)]
        inside = [x for x in xs if -1.0 <= x <= (maxx - minx) + 1.0]
        if len(inside) < len(xs):
            notes.append(f"{len(xs) - len(inside)} crest lines lie outside the roof and were ignored.")
        xs = inside
    pitch = None
    if len(xs) >= 2:
        gaps = sorted(b - a for a, b in zip(xs, xs[1:]))
        pitch = gaps[len(gaps) // 2]
    if not xs:
        notes.append("No crest lines were found: the planner will use an even flute pitch if you give one.")
    return Schematic(outline, xs, pitch, angle, notes)


# ---------------------------------------------------------------- writing a schematic (samples and tests)

def schematic_to_svg(outline_mm: list[Point], crest_xs_mm: list[float], unit: str = "mm") -> str:
    """An SVG schematic in the format this module reads, with the roof and crest lines named.

    `unit` is "mm" or "in": the file is drawn in that unit with the real size stated, so it reads back exactly.
    """
    per = {"mm": 1.0, "in": 25.4}[unit]
    maxx, maxy = max(p[0] for p in outline_mm), max(p[1] for p in outline_mm)
    f = lambda v: f"{v / per:.4f}".rstrip("0").rstrip(".")  # noqa: E731
    pts = " ".join(f"{f(x)},{f(maxy - y)}" for x, y in outline_mm)       # SVG y points down
    lines = "\n".join(f'    <line id="crest-{i + 1}" x1="{f(x)}" y1="0" x2="{f(x)}" y2="{f(maxy)}"/>'
                      for i, x in enumerate(crest_xs_mm))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{f(maxx)}{unit}" height="{f(maxy)}{unit}" '
            f'viewBox="0 0 {f(maxx)} {f(maxy)}">\n'
            f'  <polygon id="roof-outline" points="{pts}" fill="none" stroke="black"/>\n'
            f'  <g id="flutes" stroke="gray">\n{lines}\n  </g>\n</svg>\n')


def schematic_to_dxf(outline_mm: list[Point], crest_xs_mm: list[float]) -> str:
    """A minimal ASCII DXF in millimetres: the roof as a closed LWPOLYLINE on layer OUTLINE, crests as LINEs on FLUTES."""
    maxy = max(p[1] for p in outline_mm)
    out = ["0", "SECTION", "2", "HEADER", "9", "$INSUNITS", "70", "4", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES",
           "0", "LWPOLYLINE", "8", "OUTLINE", "90", str(len(outline_mm)), "70", "1"]
    for x, y in outline_mm:
        out += ["10", f"{x:.4f}", "20", f"{y:.4f}"]
    for x in crest_xs_mm:
        out += ["0", "LINE", "8", "FLUTES", "10", f"{x:.4f}", "20", "0.0", "11", f"{x:.4f}", "21", f"{maxy:.4f}"]
    out += ["0", "ENDSEC", "0", "EOF"]
    return "\n".join(out) + "\n"
