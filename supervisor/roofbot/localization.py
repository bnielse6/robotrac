"""How accurately will the robot stop at each spot? A model of Locomotion's cross-track control.

Pure functions and data, no I/O, standard library only. This answers the navigation plan's open
question (N4): is a lateral tolerance of +/-0.5 mm of the screw line against the crest centre
achievable, given a noisy crest sensor array, a drifting heading, an encoder with slip, and a
residual offset between the sensor array and the drill?

What is modelled
  Lateral (across the flutes). While driving, Locomotion runs the PD loop in
  firmware/esp32/src/locomotion.cpp: low-pass the sensor reading, steer against the error. The plant
  is: lateral position y moves at speed * heading, the heading turns at `steer_rate` times the
  steering command, and a random walk disturbs the heading (wheel slip, gyro drift). The loop is
  linear apart from the steering limit, so the variance of y is propagated step by step with a
  covariance recursion (fast and deterministic, no random numbers). `simulate_drive` runs the same
  loop with random numbers and the steering limit, to cross-check it.
  Along the row. The encoder resets at every drive, so stopping errors accumulate spot to spot: a
  scale error (wheel diameter), random slip, and the robot stopping somewhere inside the stretch it
  covers between two encoder checks. They can be reset at each row start.
  Fine positioning (stop and nudge). A turn leaves the robot a few mm off the new crest and the
  steering loop needs a few hundred mm to pull that in, so a spot right after a turn is stopped at
  with the error still there. At each spot Locomotion therefore reads the crest array (averaging
  several readings, since it is standing still) and, if the error is outside an accept limit,
  nudges sideways by the measured error and reads again, up to a few tries, else NOT_ALIGNED. The
  nudge itself is imperfect (`nudge_sigma_mm`), and what limits the result is the reading noise,
  the array calibration and the array-to-drill offset. `fine_position_stats` runs this with random
  numbers (a fixed seed, so the answer does not change between runs).
  Row changes. Counting crests can miss one; the encoder check against the planned row gap catches
  that, so a miscount shows up as a failed turn (TURN_FAILED), not a wrong row.

What is NOT known. Every number in `LocalizationParams` is a placeholder, except the control gains,
which are the firmware's and are kept equal to firmware/esp32/include/config.h by a test. The real
sensor noise, heading drift and slip come from the bench test and the first drives on hardware.
Replace them then. Until then read the output as "what would have to be true", not a prediction.

Sign convention: lateral error is positive when the robot is to the right of the crest centre.
Along error is positive when the robot has gone past the spot.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from typing import Optional

from .planner import Layout


@dataclass(frozen=True)
class LocalizationParams:
    # ---- the control loop. These are the firmware's gains (config.h) and are kept equal by a test.
    kp: float = 0.08                    # CROSS_TRACK_KP, steering command per mm
    kd: float = 0.04                    # CROSS_TRACK_KD, steering command per mm/s
    filter_alpha: float = 0.3           # CROSS_TRACK_FILTER
    steer_max: float = 1.0              # STEER_MAX
    control_dt_s: float = 0.010         # STEER_PERIOD_MS

    # ---- the robot and its disturbances. PLACEHOLDERS until measured.
    speed_mm_s: float = 200.0
    steer_rate_rad_s: float = 1.0       # heading rate at full steering command
    heading_walk_deg_per_sqrt_s: float = 0.05   # random walk of the heading from slip and gyro drift
    start_lateral_sigma_mm: float = 5.0         # where it stands after being placed, and after each turn
    start_heading_sigma_deg: float = 1.0

    # ---- the crest sensor array and the drill. PLACEHOLDERS.
    array_noise_mm: float = 0.15        # random error of one array reading
    array_bias_sigma_mm: float = 0.10   # calibration error of the array, fixed for a run
    drill_offset_sigma_mm: float = 0.20 # residual offset between the array centre and the drill

    # ---- the encoder and stopping. PLACEHOLDERS.
    encoder_scale_sigma: float = 0.002  # wheel diameter error, as a fraction of the distance
    slip_sigma_mm_per_sqrt_m: float = 0.5
    stop_window_mm: float = 24.0        # the robot stops somewhere in the stretch it covers between two
                                        # encoder checks plus its stopping distance: uniform 0 to this
    along_resets_each_row: bool = True  # an absolute along-row reference at each row start (edge sensor)
    row_start_along_sigma_mm: float = 2.0
    # False is how the firmware works today: every drive starts from wherever the robot stopped, so each
    # stopping error is carried into the next spot. True is the proposed change: Locomotion remembers how
    # far past (or short of) the last spot it stopped and takes it off the next drive.
    along_compensates: bool = False

    # ---- fine positioning at the spot (stop and nudge). The accept limit, tries and number of readings
    # are the firmware's (ALIGN_ACCEPT_MM, ALIGN_MAX_ATTEMPTS, ALIGN_SAMPLES), kept equal by a test.
    fine_positioning: bool = True
    align_accept_mm: float = 0.2        # stop nudging once the averaged reading is within this
    max_align_attempts: int = 3         # nudges before NOT_ALIGNED
    align_samples: int = 8              # readings averaged at standstill before deciding
    nudge_sigma_mm: float = 0.1         # PLACEHOLDER: sideways error left by one nudge
    nudge_time_s: float = 1.5           # PLACEHOLDER: time for one nudge
    mc_samples: int = 4000              # random trials per fine-positioning estimate

    # ---- row changes
    crest_miss_probability: float = 0.001   # per crest passed, before the encoder check

    # ---- what counts as good enough
    lateral_tolerance_mm: float = 0.5   # N4, may change
    along_tolerance_mm: float = 5.0     # placeholder: not specified yet
    required_fraction: float = 0.95     # a spot "meets" the tolerance when this fraction of runs are inside


# ---------------------------------------------------------------- the lateral loop

def _matrices(p: LocalizationParams):
    """A, B (noise gain), E (heading disturbance gain) of x = [y, heading, filtered reading]."""
    dt, a, g, v = p.control_dt_s, p.filter_alpha, p.steer_rate_rad_s, p.speed_mm_s
    c = p.kp + p.kd / dt
    d = p.kd / dt
    A = [[1.0, v * dt, 0.0],
         [-g * dt * c * a, 1.0, g * dt * (d - c * (1.0 - a))],
         [a, 0.0, 1.0 - a]]
    B = [0.0, -g * dt * c * a, a]
    return A, B


def _propagate(P, A, Bn, qw):
    """P' = A P A^T + B B^T sigma_n^2 + E E^T q dt, for the 3-state loop."""
    AP = [[sum(A[i][k] * P[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    out = [[sum(AP[i][k] * A[j][k] for k in range(3)) + Bn[i] * Bn[j] for j in range(3)] for i in range(3)]
    out[1][1] += qw
    return out


def lateral_variance_after(p: LocalizationParams, steps: int, P0, controlled: bool = True):
    """The covariance of [y, heading, filtered reading] after `steps` control steps from P0.

    Stops early when the covariance stops changing (the loop has settled). With controlled=False the
    steering is held straight (as firmware does while reversing), so y drifts with the heading.
    """
    A, B = _matrices(p if controlled else replace(p, kp=0.0, kd=0.0))
    sn2 = p.array_noise_mm ** 2
    Bn = [b * math.sqrt(sn2) for b in B]
    qw = (math.radians(p.heading_walk_deg_per_sqrt_s) ** 2) * p.control_dt_s
    P = [row[:] for row in P0]
    for _ in range(steps):
        new = _propagate(P, A, Bn, qw)
        if controlled and max(abs(new[i][j] - P[i][j]) for i in range(3) for j in range(3)) < 1e-12:
            return new
        P = new
    return P


def start_covariance(p: LocalizationParams):
    s0 = p.start_lateral_sigma_mm ** 2
    sh = math.radians(p.start_heading_sigma_deg) ** 2
    return [[s0, 0.0, s0], [0.0, sh, 0.0], [s0, 0.0, s0]]    # the filter starts on the first reading: f = y


def settling(p: LocalizationParams, within: float = 1.05) -> tuple[float, float]:
    """(steady-state lateral sigma in mm, driving distance in mm until the loop is within `within` of it).

    The distance is how far the robot must drive after a turn before the turn's lateral error has been
    pulled in. A spot that comes sooner than this is stopped at before the loop has settled.
    """
    A, B = _matrices(p)
    Bn = [b * p.array_noise_mm for b in B]
    qw = (math.radians(p.heading_walk_deg_per_sqrt_s) ** 2) * p.control_dt_s
    P = start_covariance(p)
    for _ in range(200000):                                  # the steady state
        new = _propagate(P, A, Bn, qw)
        if max(abs(new[i][j] - P[i][j]) for i in range(3) for j in range(3)) < 1e-12:
            P = new
            break
        P = new
    steady = math.sqrt(max(P[0][0], 0.0))
    P = start_covariance(p)
    for k in range(200000):
        if math.sqrt(max(P[0][0], 0.0)) <= within * steady:
            return steady, k * p.control_dt_s * p.speed_mm_s
        P = _propagate(P, A, Bn, qw)
    return steady, float("inf")


def simulate_drive(p: LocalizationParams, distance_mm: float, rng: random.Random,
                   y0: Optional[float] = None, heading0: Optional[float] = None) -> tuple[float, float]:
    """One drive with random numbers and the steering limit. Returns (lateral mm, heading rad) at the end."""
    dt = p.control_dt_s
    y = rng.gauss(0.0, p.start_lateral_sigma_mm) if y0 is None else y0
    psi = rng.gauss(0.0, math.radians(p.start_heading_sigma_deg)) if heading0 is None else heading0
    f = y + rng.gauss(0.0, p.array_noise_mm)
    c, d = p.kp + p.kd / dt, p.kd / dt
    walk = math.radians(p.heading_walk_deg_per_sqrt_s) * math.sqrt(dt)
    for _ in range(int(abs(distance_mm) / p.speed_mm_s / dt)):
        f_new = (1 - p.filter_alpha) * f + p.filter_alpha * (y + rng.gauss(0.0, p.array_noise_mm))
        u = -c * f_new + d * f
        u = max(-p.steer_max, min(p.steer_max, u))
        psi_old = psi
        psi += p.steer_rate_rad_s * dt * u + rng.gauss(0.0, walk)
        y += p.speed_mm_s * dt * psi_old
        f = f_new
    return y, psi


# ---------------------------------------------------------------- along the row

def _uniform_var(w: float) -> float:
    return w * w / 12.0


# ---------------------------------------------------------------- the report

@dataclass
class SpotAccuracy:
    row: int
    spot: int
    lateral_sigma_mm: float          # of the screw line against the crest centre, everything included
    lateral_p95_mm: float            # 1.96 sigma: 95 % of spots land inside this
    lateral_within_tol: float        # fraction of runs inside the tolerance
    control_sigma_mm: float          # just the control loop's residual
    along_mean_mm: float
    along_sigma_mm: float
    along_within_tol: float
    nudges_expected: float = 0.0     # nudges expected here (0 when the steering has already pulled it in)
    p_not_aligned: float = 0.0       # chance of running out of tries (NOT_ALIGNED)


@dataclass
class TurnAccuracy:
    row: int                         # the turn after this row
    crests: int
    miscount_probability: float      # caught by the encoder check as TURN_FAILED


@dataclass
class AccuracyReport:
    params: LocalizationParams
    spots: list[SpotAccuracy]
    turns: list[TurnAccuracy]
    worst: Optional[SpotAccuracy] = None
    fraction_meeting_lateral: float = 0.0
    fraction_meeting_along: float = 0.0
    dominant_lateral_term: str = ""
    lateral_budget_mm: dict = field(default_factory=dict)   # sigma of each contribution at the worst spot
    notes: list[str] = field(default_factory=list)
    expected_nudges: float = 0.0                 # per run of the whole plan
    nudge_time_s: float = 0.0                    # the time those nudges add
    worst_p_not_aligned: float = 0.0
    steady_state_control_sigma_mm: float = 0.0   # the loop's residual once it has settled
    settle_distance_mm: float = 0.0              # driving needed after a turn before it has settled

    @property
    def achievable(self) -> bool:
        """True when at least `required_fraction` of the spots meet the lateral tolerance (and, with fine
        positioning, no spot is likely to run out of nudges)."""
        ok = self.fraction_meeting_lateral >= self.params.required_fraction
        if self.params.fine_positioning:
            ok = ok and self.worst_p_not_aligned <= 0.05
        return ok


def _within(mean: float, sigma: float, tol: float) -> float:
    """P(|X| <= tol) for X ~ Normal(mean, sigma)."""
    if sigma <= 0:
        return 1.0 if abs(mean) <= tol else 0.0
    cdf = lambda x: 0.5 * (1.0 + math.erf((x - mean) / (sigma * math.sqrt(2.0))))  # noqa: E731
    return cdf(tol) - cdf(-tol)


_FINE_CACHE: dict = {}


def fine_position_stats(p: LocalizationParams, pre_sigma_mm: float, seed: int = 12345) -> dict:
    """Stop-and-nudge at one spot, by random trials.

    The robot stops with a sideways error of spread `pre_sigma_mm`. It averages `align_samples` array
    readings; if the average is within `align_accept_mm` it is done, otherwise it nudges by the
    measured error (leaving `nudge_sigma_mm`) and reads again, up to `max_align_attempts` nudges.
    Returns the spread of the screw error among the runs that finished (`sigma_mm`), the fraction of
    those inside the tolerance (`within_tol`), the mean number of nudges, and the chance of running
    out of tries (`p_not_aligned`).
    """
    key = (round(pre_sigma_mm, 3), p.array_noise_mm, p.array_bias_sigma_mm, p.drill_offset_sigma_mm, p.align_accept_mm,
           p.max_align_attempts, p.align_samples, p.nudge_sigma_mm, p.lateral_tolerance_mm, p.mc_samples, seed)
    if key in _FINE_CACHE:
        return _FINE_CACHE[key]
    rng = random.Random(seed)
    noise = p.array_noise_mm / math.sqrt(max(p.align_samples, 1))
    done, within, nudges, sq = 0, 0, 0, 0.0
    for _ in range(p.mc_samples):
        y = rng.gauss(0.0, pre_sigma_mm)              # the array's true offset from the crest centre
        bias = rng.gauss(0.0, p.array_bias_sigma_mm)  # what the array adds to every reading
        drill = rng.gauss(0.0, p.drill_offset_sigma_mm)   # the screw sits this far from the array centre
        tries = 0
        while True:
            m = y + bias + rng.gauss(0.0, noise)      # the averaged reading
            if abs(m) <= p.align_accept_mm:
                done += 1
                err = y + drill                       # where the screw goes, against the crest centre
                within += abs(err) <= p.lateral_tolerance_mm
                sq += err * err
                break
            if tries >= p.max_align_attempts:
                break
            y = y - m + rng.gauss(0.0, p.nudge_sigma_mm)
            tries += 1
        nudges += tries
    n = p.mc_samples
    out = {"sigma_mm": math.sqrt(sq / done) if done else float("inf"),
           "within_tol": within / done if done else 0.0,
           "mean_nudges": nudges / n, "p_not_aligned": 1.0 - done / n}
    _FINE_CACHE[key] = out
    return out


def analyse(layout: Layout, p: Optional[LocalizationParams] = None) -> AccuracyReport:
    """Accuracy at every spot of a planned layout, row by row, in driving order."""
    p = p or LocalizationParams()
    dt = p.control_dt_s
    spots: list[SpotAccuracy] = []
    turns: list[TurnAccuracy] = []
    fixed = math.hypot(p.array_bias_sigma_mm, p.drill_offset_sigma_mm)
    mean_stop = p.stop_window_mm / 2.0
    var_stop = _uniform_var(p.stop_window_mm)
    along_mean = 0.0
    along_var = 0.0
    travelled = 0.0

    for r in layout.rows:
        P = start_covariance(p)                       # after the turn (or the placement, for row 1)
        if p.along_resets_each_row or r.row == 1:
            along_mean, along_var, travelled = 0.0, p.row_start_along_sigma_mm ** 2, 0.0
        for k, dist in enumerate(r.distances_mm(), start=1):
            steps = int(abs(dist) / p.speed_mm_s / dt)
            P = lateral_variance_after(p, steps, P, controlled=dist >= 0)
            control = math.sqrt(max(P[0][0], 0.0))
            total = math.hypot(control, fixed)
            nudges = p_fail = 0.0
            within = _within(0.0, total, p.lateral_tolerance_mm)
            if p.fine_positioning:
                fp = fine_position_stats(p, control)
                total, within, nudges, p_fail = fp["sigma_mm"], fp["within_tol"], fp["mean_nudges"], fp["p_not_aligned"]
            travelled += abs(dist)
            if p.along_compensates:      # only the latest stop is left, plus what the distance itself adds
                along_mean = mean_stop
                along_var = (p.row_start_along_sigma_mm ** 2 + var_stop
                             + (p.slip_sigma_mm_per_sqrt_m ** 2) * travelled / 1000.0)
            else:                        # every stop is carried into the next spot
                along_mean += mean_stop
                along_var += var_stop + (p.slip_sigma_mm_per_sqrt_m ** 2) * abs(dist) / 1000.0
            along_sigma = math.sqrt(along_var + (travelled * p.encoder_scale_sigma) ** 2)
            spots.append(SpotAccuracy(
                r.row, k, total, 1.96 * total, within, control,
                along_mean, along_sigma, _within(along_mean, along_sigma, p.along_tolerance_mm), nudges, p_fail))
        if r.crests_to_next is not None:
            turns.append(TurnAccuracy(r.row, r.crests_to_next,
                                      1.0 - (1.0 - p.crest_miss_probability) ** r.crests_to_next))

    report = AccuracyReport(p, spots, turns)
    report.steady_state_control_sigma_mm, report.settle_distance_mm = settling(p)
    if spots:
        report.worst = max(spots, key=lambda s: s.lateral_sigma_mm)
        report.expected_nudges = sum(s.nudges_expected for s in spots)
        report.nudge_time_s = report.expected_nudges * p.nudge_time_s
        report.worst_p_not_aligned = max(s.p_not_aligned for s in spots)
        n = len(spots)
        report.fraction_meeting_lateral = sum(s.lateral_within_tol >= p.required_fraction for s in spots) / n
        report.fraction_meeting_along = sum(s.along_within_tol >= p.required_fraction for s in spots) / n
        w = report.worst
        if p.fine_positioning:   # what limits the result once the nudge has run
            report.lateral_budget_mm = {
                "nudge and reading noise": math.hypot(p.nudge_sigma_mm, p.array_noise_mm / math.sqrt(max(p.align_samples, 1))),
                "array calibration": p.array_bias_sigma_mm,
                "array to drill offset": p.drill_offset_sigma_mm}
        else:
            report.lateral_budget_mm = {"control loop residual": w.control_sigma_mm,
                                        "array calibration": p.array_bias_sigma_mm,
                                        "array to drill offset": p.drill_offset_sigma_mm}
        report.dominant_lateral_term = max(report.lateral_budget_mm, key=report.lateral_budget_mm.get)
    early = [(r.row, 1) for r in layout.rows if 0 <= r.distances_mm()[0] < report.settle_distance_mm]
    if early and p.fine_positioning:
        report.notes.append(
            f"{len(early)} row{'s' if len(early) > 1 else ''} start with a spot sooner than the {report.settle_distance_mm:.0f} mm "
            f"the steering needs to settle after a turn, so fine positioning nudges there: about {report.expected_nudges:.1f} nudges "
            f"over the run, adding about {report.nudge_time_s:.0f} s.")
    elif early:
        report.notes.append(
            f"The loop needs about {report.settle_distance_mm:.0f} mm of driving to settle after a turn, but the first "
            f"spot of {len(early)} row{'s' if len(early) > 1 else ''} comes sooner than that, so the turn's sideways "
            "error is still there when the robot stops. A fine-positioning step at the spot (stop and nudge) "
            "or a longer run-in would fix it.")
    if any(r.distances_mm()[0] < 0 for r in layout.rows):
        report.notes.append("Some drives reverse. The firmware holds the steering straight while reversing, "
                            "so the lateral error is not corrected on those drives.")
    return report
