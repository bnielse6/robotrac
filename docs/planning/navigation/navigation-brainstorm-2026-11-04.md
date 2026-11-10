# Navigation brainstorm

Notes from a brainstorm on 2026-11-04, following `navigation-notes.md`. This is the record of the discussion. Decisions made since are in sections 6 to 10 and in `navigation-plan-2026-11-04.md`, and the long-term design is in `../../design/design_concept.md`. No code or other docs were changed. The terms "beam" and `OFF_BEAM` elsewhere in the docs come from an earlier joist assumption and have not been updated (see the open questions).

## 1. Facts established

| Topic | Answer |
|---|---|
| Surface | The robot drives on **densdeck**, on top of **corrugated steel decking**, on top of steel beams. The beams and the deck are hidden. |
| Roof | Flat. The outline shape varies per job and is **given by the company**. |
| Spot accuracy | As accurate as possible. The screw should land in the **middle of the top of a flute** (the crest). |
| Target | The screw only needs to go **through the flute crest**. It does **not** need to hit the joist. |
| Beam spacing | Known, but **must not be relied on** as the source of position. |
| Beam width | "About 3 ft", to be confirmed by measurement. It is unclear what this refers to (see open questions). |
| Start pose | The **operator places the robot at one of the roof corners**. |
| Radio | GPS and Wi-Fi are likely poor on a roof. Navigation does not need either: the Supervisor, ESP32 and sensors are all on the robot. Only the operator screen depends on Wi-Fi, and the robot stops safely if it drops. |
| Sensor idea | A **ring of magnetic sensors** that reads the steel through the densdeck and produces a vector pointing the way the robot should move, to align it. |

## 2. Ideas from the original notes

- Wheel encoders, an IMU, and some absolute reference (rare earth magnets or a localization camera, never used one before).
- Possibly ROS 2 Nav2, for its waypoint following. The thinking was that the pattern and the space are known, so compute the best path mathematically.
- A **waypoint generator** that turns an uploaded pattern into fastening coordinates `(x, y)`.
- References: OpenMower (lawn mower code) and a coverage path planning paper (links in `navigation-notes.md`).

## 3. Conclusions so far

**Nav2 is probably overkill.** The path is fixed by the roof layout and the robot never leaves it, so there is little to plan. Nav2 would add ROS 2 to the Pi next to a Supervisor that is deliberately pure and clock-injected. Revisit it only if the robot turns out to need real 2D free driving.

**Two separate jobs need two signals:**

| Job | Question | Source |
|---|---|---|
| Along-track | How far down the row am I, and is this the right spot? | Encoders and IMU heading, with absolute fixes to cancel drift (counting flutes may serve as a ruler) |
| Cross-track | Is the screw line over the flute crest? | The magnetic sensor array, giving a lateral error |

**Control shape:** follow the planned line by dead reckoning, and correct sideways from the sensor array. That is a line follower with feed-forward, and a PID on the lateral error or pure pursuit should be enough.

**The deck dominates the magnetic signal.** The steel deck is directly under the densdeck, so it will swamp anything below it. Implications:

- Use **differential or gradient** readings across the ring, so the part of the deck that looks the same to every sensor cancels. This matches the ring idea.
- Expect a **periodic ripple** as the sensors pass crests and valleys. That ripple is the signal when the target is the crest, and it can also act as a flute-counting ruler.
- **Active sensing** (inductive or eddy current, or a magnetometer plus a drive coil) is probably better than passive field sensing, which is weak and will pick up noise from the drill and motors. This needs a bench test, not an argument.

**Start pose:** treat the operator-placed corner as a **coarse prior** only. A small placement error becomes a systematic offset for every row. The first sensor detection should snap the lateral position. The operator should choose the corner and start heading on the UI so the generator knows which way the serpentine runs.

**Waypoint generator** (a pure Python function beside the Supervisor, with unit tests, feeding the route map). It must handle non-rectangular outlines, edge setbacks, row starts and ends, and the serpentine turn sequence, and output `(row, spot, x, y, heading)` in roof coordinates. Today the route map is hand-programmed (rows, spots per row, distances).

## 4. Open questions

1. **ANSWERED: rows run along the flutes** (lawnmower pattern up and down the roof, crossing flutes only at row changes). Original question: do rows run *along* a flute (the robot holds one crest) or *across* flutes (it crosses a crest every pitch and stops at one per fastener)? These are very different control problems. This is the biggest open question.
2. **ANSWERED: "beam" means the flute being screwed into.** Original question: what does "beam" mean now? The joist no longer matters, so what is the "3 ft wide beam" in the notes, and what should the rows and the docs' "beam" terms (`OFF_BEAM`, beam sensors, route map) actually refer to? The docs may need renaming.
3. **PARTLY ANSWERED: lateral tolerance is +/-0.5 mm (subject to change), see section 8.** Still open, the deck dimensions: flute pitch, crest width, depth, and the densdeck thickness. How wide is the target to hit, and what lateral tolerance follows?
4. **Candidate sensors chosen for testing, see section 9.** Original text: none chosen yet. Suggest two or three (for example a Hall/magnetometer breakout and an inductive one) to compare.
5. **Can the sensor resolve a crest through densdeck?** This is the main technical risk and is cheap to test on the bench.

## 5. Proposed next steps

1. **Bench experiment.** Corrugated deck with densdeck on top. Move a candidate sensor or small ring across it and log the readings. Check whether crests are visible through the densdeck and what the ripple looks like. Claude can write the logging and plotting script once a sensor is picked.
2. **Waypoint generator** and a **localization model in the simulator** with injectable drift, flute-count fixes and lateral sensor fixes. This shows how good the sensing must be before parts are bought.
3. **Update the docs and terminology** once questions 1 and 2 are answered, keeping `../../design/complete_system_guide.md`, `../../software/message_schema.md`, the simulator (`detail.py`) and the firmware in step.

## 6. Diamond sensor array (idea added 2026-11-04)

Instead of a ring, use four sensors in a **diamond**: left and right tips, plus front and rear tips. The width is tied to the flute geometry.

**Sizing rule.** Model the deck as a periodic signal with pitch `p`, and let `w` be the left-to-right sensor spacing and `x` the offset from a crest. The left-minus-right difference is proportional to `sin(2*pi*x/p) * sin(pi*w/p)`.

- `w = p` (full pitch) makes the second term zero, so the difference carries **no signal**. Do not make the diamond one full pitch wide.
- Best signal is at about `w = p/2`: one sensor on a crest while the other is on a valley, and the difference crosses zero when centered on the crest. That is where the screw has to land, and the slope is steepest there.
- `w` should also be at least about the **standoff height** (densdeck thickness plus clearance). Each sensor reads a blurred patch of deck roughly as wide as its height above the metal, so a diamond much narrower than that sees nearly the same value on all four sensors.
- Too small also means a weak signal and a narrow capture range (the reading saturates and does not say which way to steer).
- If the standoff is bigger than `p/2`, no layout works with that sensor. The fix is a different sensor or mounting lower.

**Roles.**

- Left and right tips: cross-track error, from the difference.
- Front and rear: heading, from comparing the cross-track error at two points along the track. A single sensor on the centerline gives magnitude but not sign, so each of the front and rear needs a partner, or is compared against the left/right pair. The minimum useful version is two left/right pairs, one forward and one aft.

**Risks.**

- Every crest looks the same, so the array can lock onto the wrong crest. Encoders and the known layout choose the crest, and the array only holds the lock.
- If rows run *across* the flutes (open question 1), the front/rear sensors become a direction-of-travel and crest-counting ruler, and the diamond's purpose changes.
- Everything assumes a crest is visible through the densdeck (open question 5), which is untested.

## 7. Measurements to take in person (pending)

The user will measure these and report the values. Fill in the table, then size the diamond (`w` about `p/2`, at least the standoff) and check that a crest is detectable at that standoff.

| Quantity | Value | Notes |
|---|---|---|
| Flute pitch `p` (crest to crest) | _not measured_ | |
| Crest width | _not measured_ | |
| Flute depth | _not measured_ | |
| Densdeck thickness | 15.9 mm (5/8 in, +/-0.8 mm) | From the DensDeck StormX product page, 2026-11-09 |
| Insulation layer between deck and densdeck | _unknown_ | The installation guide's cutaway shows one. If present, add its thickness to the standoff. Waiting on the user (Q8) |
| Densdeck board size | 1219 mm wide by 1219 or 2438 mm long | Tolerances +/-3 mm width, +/-6.4 mm length |
| Densdeck seams | Butted tightly, edge joints on and parallel to the top flutes, running bond | Installation guide. Long seams lie along the rows. Edge profile not stated |
| Sensor mounting height above the densdeck | _not measured_ | Planned or achievable, if known |
| Rows run along or across the flutes | Along (decided, N1) | |

When the values are in: compute the candidate `w`, estimate the blur (standoff versus `p/2`), and optionally write a small simulation sweeping `w/p` to show signal strength and zero-crossing slope.

## 8. Decisions from the user (2026-11-04)

- **Rows run along the flutes.** The robot follows one flute up or down the roof (lawnmower pattern) and crosses flutes only when it changes rows. Cross-track control is the main job while driving a row. At a row change, counting the crests passed is a ruler for the sideways move.
- **"Beam" means the flute being screwed into.** The joist meaning in the old docs is gone. Terms such as `OFF_BEAM` and "beam sensors" should be renamed (for example to flute) once the design settles. Not done yet, and it must stay in step across `../../design/complete_system_guide.md`, `../../software/message_schema.md`, `detail.py` and the firmware.
- **The target is the crest, not the valley.** The sensor must report where the crest is, and the robot steers to keep the screw line on it. Crests are closer to the sensor than valleys, so the signal should peak over a crest.
- **Lateral tolerance: +/-0.5 mm (subject to change).** This is the allowed error between the screw line and the crest center.

**Warning: +/-0.5 mm is very tight.** Points to check early:

- The sensor reads a blurred patch about as wide as its height above the metal, so the crest center is only as sharp as that blur allows. The bench test must show whether the zero crossing can be located to better than 0.5 mm at the real standoff.
- Wheel slip, steering backlash, chassis flex and the mechanical offset between the sensor and the drill all add error. Those add up in the same 0.5 mm.
- Possible ways to relax it: a wider screw target, a final fine-positioning step with the robot stopped (read, nudge, read again), or a mechanically floating drill head. Decide once the crest width and the real tolerance of the screw are known.
- The test rig itself must position the sensor to better than 0.5 mm (see section 10).

## 9. Sensors to buy for testing

Buy one of each, since the aim is to compare before committing. Check the current stock and part numbers before ordering. These are suggestions from memory, not verified listings.

| # | Sensor | What it is | Why test it | Notes |
|---|---|---|---|---|
| 1 | **LDC1612 breakout** (TI inductance-to-digital, e.g. a Seeed Grove LDC1612 board) with its coil | Active eddy-current sensing. The reading changes with distance to metal | Top pick. Crest is closer than valley, so the signal should peak over a crest. Gives a fine analog-like value, and the coil size can be changed | I2C. Coil diameter sets the blur, so try a small and a larger coil if the board allows. Check the sensing range against the standoff |
| 2 | **Magnetometer breakout** (e.g. MMC5983MA or LIS3MDL) | Passive field sensing of the steel's distortion of the Earth field | Cheapest and simplest to wire. Shows whether passive sensing is enough | I2C or SPI. Most exposed to motor and drill noise. Try also with a small fixed magnet beside it as a bias |
| 3 | **Industrial inductive proximity sensor with analog output** (e.g. M12 or M18, 0 to 10 V or 4 to 20 mA) | Rugged off-the-shelf eddy-current sensor | Long range, so a quick baseline: if this cannot see a crest through the densdeck, the smaller sensors probably cannot either. It is also the sort of part that survives a roof | Get an **analog** version. A plain on/off switching version only gives a threshold and is much less useful. Needs 12 to 24 V and a level shifter or ADC to read it |

Also buy for the test rig: M3 shims or spacers in several thicknesses (for the standoff), a dial indicator or good ruler with 0.5 mm marks, and a breadboard or dev board to read the sensors (an ESP32 dev board or a Raspberry Pi will do).

## 10. Bench test plan

**Goal:** find out which sensor, at which standoff, can locate the crest center to better than 0.5 mm, and which array width `w` gives the best signal.

**Setup**

1. A piece of the real corrugated deck with a piece of densdeck on top (same thickness as the roof). At least three flutes wide and about 300 mm long, fixed down so it cannot move.
2. A rail or guide so the sensor moves straight across the flutes (perpendicular), with a ruler or dial indicator giving its position to 0.5 mm or better.
3. Shims so the standoff can be set to several heights above the densdeck.
4. A script that logs sensor reading against position. Claude can write this once a sensor is chosen.

**Measure first (section 7):** flute pitch, crest width, flute depth, densdeck thickness. Write them into the table.

**Tests (do each sensor in turn)**

| Step | What to do | What you learn |
|---|---|---|
| 1. Sanity | Hold the sensor still over a crest, then over a valley. Note the readings. Repeat 20 times | Is there any difference at all, and how noisy is the reading? |
| 2. Sweep | Move across at least two full flutes in 1 mm steps (0.5 mm steps near each crest), logging reading against position | The shape of the signal, the crest location, and whether the crest peak is sharp enough |
| 3. Standoff | Repeat the sweep at 3 to 4 standoffs, from the densdeck surface up to the largest height the robot could have | How fast the signal blurs and weakens with height. The largest standoff that still works |
| 4. Repeatability | Repeat one sweep 10 times without touching the rig | Position error from noise alone, to compare with 0.5 mm |
| 5. Pair test | Take two sensors a distance `w` apart (try `w` of about p/4, p/2 and 3p/4) and compute the left-minus-right difference | Where the zero crossing is, the slope there, and the best `w`. Confirms the diamond sizing rule in section 6 |
| 6. Noise | Repeat step 4 with a drill motor, then a drive motor, running near the sensor | Whether it still works with the robot's own noise |
| 7. Rotation | Rotate the sensor pair by 2 to 5 degrees and repeat step 5 | How much heading error spoils the cross-track reading, which tells us how well the diamond can measure heading |

**Pass criteria (starting suggestions)**

- The crest center is found with repeatability better than 0.5 mm (ideally 0.2 mm) at the working standoff.
- The signal at the crest is clearly above the noise (a ratio of 10 or more is a comfortable start).
- It still works with the motors running.

**Record** each result in a table (sensor, standoff, `w`, noise, crest-location error). Bring the numbers back and Claude can compare them and recommend a sensor and a diamond size.
