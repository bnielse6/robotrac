# Design concept

The long-term reference for the roofing robot's design. It is updated whenever a design decision is made or changed, so that at the end of the project it is the one document that describes what was built and why. It summarizes and points to the detailed docs. It does not replace them.

Started 2026-11-04. See the change log at the bottom.

How to read it: every decision has an ID, a date, a status and a reason. **Decided** means the user chose it. **Proposed** is Claude's recommendation awaiting confirmation or test data. **Superseded** means replaced, kept so the history is visible.

## 1. Purpose and scope

A robot that drives over a flat roof and fastens roofing plates down with screws, working in a lawnmower pattern. Control system for the MSE 4499 capstone. A Raspberry Pi 5 runs the Supervisor state machine, vision and the operator UI. An ESP32 runs four subsystems (Locomotion, Plate, Screw, Fastening) over USB serial.

Detailed behavior is in `complete_system_guide.md`. The hardware split is in `hardware_architecture.md`. The messages are in `message_schema.md`.

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

Details: `supervisor_code_guide.md`, `firmware_guide.md`, `simulator_guide.md`.

## 5. Navigation and sensing concept

Working detail is in `navigation/navigation-plan-2026-11-04.md`. Reasoning is in `navigation/navigation-brainstorm-2026-11-04.md`.

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
| D2 | 2026-11-04 | "Beam" means the flute being screwed into. Beam terms in the docs and code will be renamed later. | The old joist meaning no longer applies | Decided, rename pending |
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
| D14 | 2026-11-09 | Spots come from the Carlisle MF-27 board pattern stamped on a grid of 4x8 ft boards, not from a uniform spacing. The pattern variant (5 or 8 fasteners per 4x8 board) is a roof-dependent parameter. | The spec fixes fastener positions per board. See `navigation/Fastning Report.pdf` | Decided |
| D15 | 2026-11-09 | The 8 ft board edges run along the flutes, so rows run along the board length. | User, 2026-11-09 | Decided |
| D16 | 2026-11-09 | Each spot is snapped to the nearest crest and its offset is reported. | Spot positions in inches may not land on crests, depending on flute pitch | Proposed, needs flute pitch |
| D17 | 2026-11-09 | Plan for two ESP32 nodes: Locomotion (motors, encoders, IMU, sensor array) and Tool (Plate, Screw, Fastening). Bench work stays on one board. Transport between nodes is open, leaning CAN with a gateway. | Pin count is about 30 and growing, subsystems are spread out, the drill is a noise source. See `pin_map.md` | Proposed direction, transport undecided |
| D18 | 2026-11-09 | Path planning stays out of the Supervisor. `planner.py` runs before the run and hands the Supervisor a `Route`. Cross-track correction runs in Locomotion firmware. | The Supervisor must stay a pure state machine with no I/O | Decided |

Earlier decisions made before this document (Pi 5 plus ESP32, USB serial, hardware E-stop, retries counted by the Supervisor, and others) are in `next_steps.md` section 2 and `hardware_architecture.md`.

## 7. Open items

See `navigation/navigation-plan-2026-11-04.md` section 6 for the full list. The ones that change the design most: the deck measurements, the bench test result, and whether +/-0.5 mm is achievable.

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
