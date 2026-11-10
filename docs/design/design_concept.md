# Design concept

The long-term reference for the roofing robot's design. It is updated whenever a design decision is made or changed, so that at the end of the project it is the one document that describes what was built and why. It summarizes and points to the detailed docs. It does not replace them.

Started 2026-11-04. See the change log at the bottom.

How to read it: every decision has an ID, a date, a status and a reason. **Decided** means the user chose it. **Proposed** is Claude's recommendation awaiting confirmation or test data. **Superseded** means replaced, kept so the history is visible.

## 1. Purpose and scope

A robot that drives over a flat roof and fastens roofing plates down with screws, working in a lawnmower pattern. Control system for the MSE 4499 capstone. A Raspberry Pi 5 runs the Supervisor state machine, vision and the operator UI. An ESP32 runs four subsystems (Locomotion, Plate, Screw, Fastening) over USB serial.

Detailed behavior is in `complete_system_guide.md`. The hardware split is in `hardware_architecture.md`. The messages are in `../software/message_schema.md`.

## 2. Operating environment

| Item | Value | Source |
|---|---|---|
| Roof | Flat. The outline shape varies per job and is supplied by the company. | User |
| Surface | Densdeck over corrugated steel deck over steel beams. The deck and beams are hidden. | User |
| Target | The screw goes through the **crest** of a flute. It does not need to hit a beam or joist. | User |
| Start | The operator places the robot at a roof corner. | User |
| Radio | GPS and Wi-Fi are unreliable. Navigation must not depend on either. | User |

## 3. Requirements

| ID | Requirement | Value | Status |
|---|---|---|---|
| R1 | Lateral position of the screw line against the crest center | +/-0.5 mm (may change) | Decided |
| R2 | Navigation does not depend on GPS or Wi-Fi | Yes | Decided |
| R3 | Rows follow the flutes, up and down the roof | Yes | Decided |
| R4 | Spot positions do not rely on known beam spacing | Yes | Decided |
| R5 | Torque limit on the screw | 10 s (the only non-placeholder number in the control code) | Existing |

All other timeouts, tolerances and speeds in the code are placeholders.

## 4. System architecture (summary)

- **The Supervisor does no I/O.** It is a pure state machine driven by messages and a clock passed in. One implementation runs in the tests, the simulator and on the robot.
- **One subsystem is commanded at a time.** It replies with exactly one `DONE`, `FAULT` or `NEED_REFILL`. Subsystems never talk to each other.
- **Retries are counted by the Supervisor.** After the retries run out it stops and only the operator can move it on.
- **The camera lives on the Pi** and answers questions from the ESP32 subsystems.
- **The ESP32 firmware** is a set of non-blocking state machines with a heartbeat watchdog. All hardware goes through `hal.h`.
- **Simulator** has a fast stub fidelity for tests and a detailed per-flowchart fidelity for the dashboard.

Details: `../software/supervisor_code_guide.md`, `../software/firmware_guide.md`, `../software/simulator_guide.md`.

## 5. Navigation and sensing concept

Working detail is in `../planning/navigation/navigation-plan-2026-11-04.md`. Reasoning is in `../planning/navigation/navigation-brainstorm-2026-11-04.md`.

**Concept.** The robot follows a planned line by dead reckoning (wheel encoders plus IMU heading) and corrects sideways from a small sensor array under the robot that reads the steel deck through the densdeck. The crest is where the sensor signal is strongest and where a differential pair crosses zero. Crossing crests at a row change gives a ruler for the sideways move.

**Sensor array.** A diamond of four sensors: left and right tips for cross-track error, front and rear for heading. The width `w` is about half the flute pitch `p`. A full pitch gives no signal because the signal scales as `sin(pi*w/p)`.

**Candidate sensors, for the bench test:**

1. LDC1612 inductive breakout with coil (active, eddy current).
2. Magnetometer breakout (MMC5983MA or LIS3MDL, passive).
3. Industrial inductive proximity sensor with analog output (long-range baseline).

**Key dimensions (to be filled in):**

| Dimension | Value |
|---|---|
| Flute pitch `p` | _not measured_ |
| Crest width | _not measured_ |
| Flute depth | _not measured_ |
| Densdeck thickness | _not measured_ |
| Sensor height above densdeck | _not measured_ |
| Chosen diamond width `w` | _pending_ |
| Chosen sensor | _pending bench test_ |

## 6. Design decision log

| ID | Date | Decision | Reason | Status |
|---|---|---|---|---|
| D1 | 2026-11-04 | Rows run along the flutes in a lawnmower pattern | The user's intended motion up and down the roof | Decided |
| D2 | 2026-11-04 | "Beam" means the flute being screwed into. Beam terms in the docs and code are renamed to crest terms (done 2026-11-10: `OFF_BEAM` is now `OFF_CREST`, the beam sensors are the crest sensors, `onBeam()` is `onCrest()`). The dated brainstorm and plan records still use the old word. | The old joist meaning no longer applies | Decided, renamed 2026-11-10 |
| D3 | 2026-11-04 | The sensor targets the crest, not the valley | The screw goes into the crest | Decided |
| D4 | 2026-11-04 | Lateral tolerance +/-0.5 mm | The user's target | Decided, may change |
| D5 | 2026-11-04 | Diamond sensor array instead of a ring | Gives cross-track error and heading with fewer sensors | Decided |
| D6 | 2026-11-04 | Diamond width about p/2, and at least the sensor standoff | At w = p the differential signal vanishes. Below the standoff the blur flattens it. | Proposed |
| D7 | 2026-11-04 | No Nav2. Dead reckoning with sensor correction. | Path is fixed by the roof layout. Nav2 would add ROS 2 beside a deliberately pure Supervisor. | Proposed |
| D8 | 2026-11-04 | Line follower with feed-forward (PID or pure pursuit on lateral error) | Simple and fits a fixed path | Proposed |
| D9 | 2026-11-04 | Differential sensing | The deck dominates the signal and the common part cancels | Proposed |
| D10 | 2026-11-04 | Active (inductive) sensing preferred over passive | Passive is weak and noisy near motors | Proposed, bench test decides |
| D11 | 2026-11-04 | Operator-placed corner is a coarse prior. First crest detection snaps the lateral position. | A small placement error would otherwise repeat on every row | Proposed |
| D12 | 2026-11-04 | Encoders and the layout choose the crest. The array only holds the lock. | All crests look alike | Proposed |
| D13 | 2026-11-04 | A waypoint generator outputs `(row, spot, x, y, heading)` | The route map is hand-programmed today | Proposed |
| D14 | 2026-11-09 | Spots come from the Carlisle MF-27 board pattern stamped on a grid of 4x8 ft boards, not from a uniform spacing. The pattern variant (5 or 8 fasteners per 4x8 board) is a roof-dependent parameter. | The spec fixes fastener positions per board. See `../planning/navigation/Fastning Report.pdf` | Decided |
| D15 | 2026-11-09 | The 8 ft board edges run along the flutes, so rows run along the board length. | User, 2026-11-09 | Decided |
| D16 | 2026-11-09 | Each spot is snapped to the nearest crest and its offset is reported. | Spot positions in inches may not land on crests, depending on flute pitch | Proposed, needs flute pitch |
| D17 | 2026-11-09 | Plan for two ESP32 nodes: Locomotion (motors, encoders, IMU, sensor array) and Tool (Plate, Screw, Fastening). Bench work stays on one board. Transport between nodes is open, leaning CAN with a gateway. | Pin count is about 30 and growing, subsystems are spread out, the drill is a noise source. See `pin_map.md` | Proposed direction, transport undecided |
| D18 | 2026-11-09 | Path planning stays out of the Supervisor. `planner.py` runs before the run and hands the Supervisor a `Route`. Cross-track correction runs in Locomotion firmware. | The Supervisor must stay a pure state machine with no I/O | Decided |
| D19 | 2026-11-10 | The roof can be a drawn polygon, not only a rectangle. The planner keeps whole boards that fit inside it and splits columns at gaps. Cut boards are still not planned (the MF-27 sheet has no cut-board pattern). A row change that leaves the roof is warned about, not planned around. | User asked for it | Decided, replaces "rectangle only" from the 2026-11-09 brainstorm |
| D20 | 2026-11-10 | The robot turns beside the last spot of a row and never drives along the roof edge to change rows. Row 1 starts at the roof edge; later rows start level with the previous row's last spot. | User, 2026-11-10 | Decided, replaces the old edge-to-edge row model |
| D21 | 2026-11-10 | The robot can reverse. `distance_mm` on a DRIVE is signed (negative = reverse). The 5-screw pattern's middle column uses it. | User, 2026-11-10 | Decided |
| D22 | 2026-11-10 | The crest sensor array's error reaches Locomotion inside the ESP32, through its own hardware layer, and Locomotion runs the steering loop (PD on a low-passed error). It is never a serial message. The Pi only gets `lateral_mm` and `along_mm` on the drive's `DONE`, for the record. Answers navigation Q6. | The loop needs tens of hertz or more and sub-millimetre resolution, which the Pi link and a pure Supervisor cannot give; matches D18 | Decided |
| D23 | 2026-11-10 | The roof schematic from the team is read from an SVG or DXF file: the roof outline and the real crest lines, so rows come from the crest lines and not an assumed pitch. The 4 x 4 ft board option is removed: only 4 x 8 ft boards. The pattern variant stays a parameter, chosen from the schematic. | User, 2026-11-10 | Decided. The file format is an assumption until a real schematic is seen |
| D24 | 2026-11-10 | A localization model (`localization.py`) tests whether +/-0.5 mm is achievable. Its control gains equal the firmware's, checked by a test. Its disturbance numbers are placeholders until the bench test. | N4 is tight and hard to judge by eye | Done; results are only as good as the placeholders |
| D25 | 2026-11-10 | The TURN command carries the crest count and the planned sideways gap, so Locomotion checks its crest count against its encoder (a mismatch is `TURN_FAILED`, not a wrong row). | Counting crests alone cannot tell a missed crest from a right one (N14) | Done |
| D26 | 2026-11-10 | Every strip is driven forwards and covers the same stretch: after its last screw it runs on to the level of the next strip's first screw and turns there (`turn_style` run-out, the default). Turning at the last screw and reversing stays as an option. | User, 2026-11-10: strips should have a consistent length and the robot only stops at the screws | Decided. Replaces the reversing plan for the 5-screw pattern |
| D27 | 2026-11-10 | Fine positioning: after stopping at a spot, Locomotion averages several crest array readings and, if the sideways error is outside a small accept limit, nudges sideways by it and reads again (up to 3 times, then `NOT_ALIGNED`). The localization model shows this brings spots straight after a turn inside the +/-0.5 mm tolerance, at a few seconds per run. | The steering loop cannot settle in the zero-length drives that follow a turn | Done in the firmware logic, the simulator and the model. The real nudge (hal_esp32) is still a TODO and its accuracy is a placeholder |

Earlier decisions made before this document (Pi 5 plus ESP32, USB serial, hardware E-stop, retries counted by the Supervisor, and others) are in `../project/next_steps.md` section 2 and `hardware_architecture.md`.

## 7. Open items

See `../planning/navigation/navigation-plan-2026-11-04.md` section 6 for the full list. The ones that change the design most: the deck measurements, the bench test result, and whether +/-0.5 mm is achievable.

## 8. Known risks

- +/-0.5 mm is tight against sensor blur, wheel slip, steering backlash and the sensor-to-drill offset.
- A crest may not be visible through the densdeck at the real standoff.
- Motor and drill noise may swamp passive sensors.
- The firmware compiles but has never run on a board. `hal_esp32.cpp` is all TODO. The serial link beyond its line framing and `robot_main.py` have never touched hardware.

## 9. Change log

| Date | Change |
|---|---|
| 2026-11-04 | Document created. Navigation decisions D1 to D13 recorded. |
| 2026-11-09 | Added D14 to D16 (fastening pattern from Carlisle MF-27, board orientation, snap to crest). |
| 2026-11-09 | Added D17 (two-node ESP32 direction) and D18 (planner outside the Supervisor). |
