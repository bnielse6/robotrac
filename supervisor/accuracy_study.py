"""How accurately would the robot stop at each spot of a plan? Prints the localization model's answer.

    python accuracy_study.py                                  # the 4 x 24 ft demo roof
    python accuracy_study.py --shape L --variant eight
    python accuracy_study.py --shape U --noise 0.3 --turn-error 1 --compensate

The numbers behind it are placeholders (roofbot/localization.py explains each one). Pass measured
values with the options below once you have them. Sizes come from the shape library (roofbot/shapes.py)
or --width/--length in millimetres.
"""
import argparse
from dataclasses import replace

from roofbot.localization import LocalizationParams, analyse
from roofbot.planner import PatternVariant, RoofSpec, plan
from roofbot.shapes import SHAPES, shape_outline_mm


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shape", choices=sorted(SHAPES), help="a roof from the shape library")
    ap.add_argument("--width", type=float, default=1219.2, help="roof width across the flutes, mm")
    ap.add_argument("--length", type=float, default=7315.2, help="roof length along the flutes, mm")
    ap.add_argument("--variant", choices=[v.value for v in PatternVariant], default="demo")
    ap.add_argument("--noise", type=float, help="crest array noise, mm")
    ap.add_argument("--drift", type=float, help="heading drift, deg per root-second")
    ap.add_argument("--turn-error", type=float, help="sideways error after a turn, mm")
    ap.add_argument("--drill-offset", type=float, help="array to drill offset, mm")
    ap.add_argument("--tolerance", type=float, help="lateral tolerance, mm")
    ap.add_argument("--no-nudge", action="store_true", help="switch fine positioning (stop and nudge at each spot) off")
    ap.add_argument("--accept", type=float, help="nudge accept limit, mm")
    ap.add_argument("--samples", type=int, help="readings averaged before deciding")
    ap.add_argument("--compensate", action="store_true", help="assume the firmware carries each stop's overshoot into the next drive")
    ap.add_argument("--spots", action="store_true", help="list every spot")
    a = ap.parse_args()

    if a.shape:
        spec = RoofSpec.from_outline(shape_outline_mm(a.shape), PatternVariant(a.variant))
    else:
        spec = RoofSpec(a.width, a.length, PatternVariant(a.variant))
    layout = plan(spec)

    p = LocalizationParams(along_compensates=a.compensate, fine_positioning=not a.no_nudge)
    if a.accept is not None:
        p = replace(p, align_accept_mm=a.accept)
    if a.samples is not None:
        p = replace(p, align_samples=a.samples)
    for opt, name in ((a.noise, "array_noise_mm"), (a.drift, "heading_walk_deg_per_sqrt_s"),
                      (a.turn_error, "start_lateral_sigma_mm"), (a.drill_offset, "drill_offset_sigma_mm"),
                      (a.tolerance, "lateral_tolerance_mm")):
        if opt is not None:
            p = replace(p, **{name: opt})
    r = analyse(layout, p)

    print(f"{len(r.spots)} spots in {len(layout.rows)} rows ({spec.variant.value} pattern)")
    print(f"Sideways, target +/-{p.lateral_tolerance_mm} mm: {100 * r.fraction_meeting_lateral:.0f}% of spots meet it "
          f"(need {100 * p.required_fraction:.0f}%) -> {'ACHIEVABLE' if r.achievable else 'NOT achievable'}")
    if r.worst:
        print(f"  worst: row {r.worst.row} spot {r.worst.spot}, spread {r.worst.lateral_sigma_mm:.3f} mm, "
              f"95% inside +/-{r.worst.lateral_p95_mm:.3f} mm")
        print("  budget at the worst spot (mm): " + ", ".join(f"{k} {v:.3f}" for k, v in r.lateral_budget_mm.items()))
    if p.fine_positioning:
        print(f"  fine positioning: {r.expected_nudges:.1f} nudges expected over the run (+{r.nudge_time_s:.0f} s), "
              f"worst chance of NOT_ALIGNED {100 * r.worst_p_not_aligned:.2f}%")
    else:
        print("  fine positioning is off")
    print(f"  the loop settles to {r.steady_state_control_sigma_mm:.3f} mm after {r.settle_distance_mm:.0f} mm of driving")
    print(f"Along the row, target +/-{p.along_tolerance_mm} mm: {100 * r.fraction_meeting_along:.0f}% of spots meet it"
          + (" (overshoot carried into the next drive)" if p.along_compensates else " (as built: each stop is carried into the next spot)"))
    if r.turns:
        print(f"Row changes: worst chance of miscounting a crest {100 * max(t.miscount_probability for t in r.turns):.2f}% "
              "(the encoder check turns a miscount into a failed turn)")
    for n in r.notes:
        print("Note:", n)
    if a.spots:
        print("\nrow spot  sideways(sigma)  within  along(mean +/- sigma)")
        for s in r.spots:
            print(f"{s.row:3d} {s.spot:4d}  {s.lateral_sigma_mm:8.3f} mm   {100 * s.lateral_within_tol:4.0f}%   "
                  f"{s.along_mean_mm:6.1f} +/- {s.along_sigma_mm:.1f} mm")


if __name__ == "__main__":
    main()
