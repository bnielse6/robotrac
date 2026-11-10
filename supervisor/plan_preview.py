"""Write an SVG preview of a planned roof layout.

    python plan_preview.py                                 # default roof, writes plan_preview.svg
    python plan_preview.py --width 5000 --length 9800 --variant eight --pitch 152.4 -o roof.svg

Open the file in a browser or Inkscape. See roofbot/planner_svg.py for how to restyle it.
Sizes are in millimetres. The flute pitch is optional and, until it is measured, a placeholder.
"""
import argparse

from roofbot.planner import PatternVariant, RoofSpec, plan
from roofbot.planner_svg import layout_to_svg


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--width", type=float, default=5000, help="roof width across the flutes, mm")
    ap.add_argument("--length", type=float, default=9800, help="roof length along the flutes, mm")
    ap.add_argument("--variant", choices=[v.value for v in PatternVariant], default="five")
    ap.add_argument("--setback", type=float, default=0, help="gap between the roof edge and the boards, mm")
    ap.add_argument("--pitch", type=float, default=None, help="flute pitch, mm (placeholder until measured)")
    ap.add_argument("--phase", type=float, default=None,
                    help="x of one crest, mm. Default: a crest under the board edges")
    ap.add_argument("-o", "--out", default="plan_preview.svg")
    a = ap.parse_args()

    spec = RoofSpec(a.width, a.length, PatternVariant(a.variant), a.setback, a.pitch, a.phase)
    layout = plan(spec)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(layout_to_svg(spec, layout))
    print(f"wrote {a.out}: {layout.total_spots} spots, {len(layout.rows)} rows, "
          f"{layout.boards_across} x {layout.boards_along} boards")


if __name__ == "__main__":
    main()
