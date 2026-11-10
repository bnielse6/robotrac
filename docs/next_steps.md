# Project Status and Next Steps

Where the project stands, what was decided, what is still open, and what to do next, in order. Written 2026-10-30. Update it as things change.

## Table of contents

- [1. Where we are](#1-where-we-are)
- [2. Decisions made](#2-decisions-made)
- [3. Next steps](#3-next-steps)
  - [Phase A: now, with no hardware](#phase-a-now-with-no-hardware)
  - [Phase B: when the ESP32 arrives](#phase-b-when-the-esp32-arrives)
  - [Phase C: real hardware, one subsystem at a time](#phase-c-real-hardware-one-subsystem-at-a-time)
  - [Phase D: whole robot](#phase-d-whole-robot)
- [4. Open questions for you](#4-open-questions-for-you)
- [5. Known gaps and risks](#5-known-gaps-and-risks)
- [6. How to pick the work back up](#6-how-to-pick-the-work-back-up)

---

## 1. Where we are

| Area | State | Evidence |
|---|---|---|
| Design: flowcharts, state chart, error handling (E1 to E10) | Done | `complete_system_guide.md`, `diagrams/` (in `docs/`) |
| Hardware architecture | Decided | `hardware_architecture.md` |
| Message schema | Drafted, used by both sides | `message_schema.md`, `roofbot/messages.py` |
| Supervisor (Python) | Written and tested in simulation | 229 tests pass |
| Router, camera service | Written and tested | `tests/test_router.py` |
| Simulator and dashboard | Written, tested, and checked in a headless browser | `simulator_guide.md` |
| Detailed subsystem model (S1 to S5) | Written and tested | `roofbot/detail.py`, `tests/test_detail.py` |
| ESP32 firmware | **Compiles** (simulated and real builds, no warnings). **Never run on a board.** | `firmware_guide.md` |
| Stack light | `LIGHT` message, Supervisor patterns, simulator lamps and firmware flashing done. Lamp pins (`PIN_LIGHT_*`) unset. | `message_schema.md`, `tests/test_supervisor.py` |
| Real hardware layer (`hal_esp32.cpp`) | Empty, every function is a TODO (the stack light output is written but untested) | |
| Pi serial link, `robot_main.py` | Written, **never tried with hardware** | |
| Camera and vision | Not started. `CameraService` answers yes to everything. | |
| Timeouts and limits | Placeholders, except the 10 s torque limit | |

**In one sentence:** the logic is designed, simulated and tested, the firmware builds, and nothing has touched real hardware yet.

## 2. Decisions made

| Date | Decision | Why | Where it is recorded |
|---|---|---|---|
| Earlier | One live camera in a lit enclosure checks plate arrival, placement, plate and screw together, and the final photo | Catches jams before fastening, one camera sees both | `complete_system_guide.md` |
| Earlier | Retries N = 2, torque limit 10 s, turns alternate right and left | Starting values, to be tuned | Guide, section 9 |
| Earlier | Subsystems never talk to each other, only to the Supervisor | Simple, testable | Guide, section 4 |
| 2026-10-30 | Raspberry Pi 5 (8 GB) as Supervisor, vision and operator interface | Needs a real OS for camera, UI and logging | `hardware_architecture.md` |
| 2026-10-30 | ESP32 for the four subsystems | Real-time I/O, fast boot | `hardware_architecture.md` |
| 2026-10-30 | USB serial link, one JSON object per line, 512 byte limit | Simple to build and debug | `message_schema.md` |
| 2026-10-30 | Hardware E-stop that cuts power, not a software message | Must work if software crashes | `hardware_architecture.md` |
| 2026-10-30 | Arduino framework with PlatformIO and ArduinoJson 7 for the firmware | Fast to build, common | `firmware_guide.md` |
| 2026-10-30 | Camera questions (`QUERY` and `ANSWER`) travel over the same link and are answered by the Pi | The camera is on the Pi, the subsystems are on the ESP32 | `message_schema.md` |
| 2026-10-30 | Locomotion faults are retried by the Supervisor too | E8 says "relocate up to N" | `message_schema.md` |
| 2026-10-30 | `START` is refused without a usable camera feed | Nothing can be verified without it | `message_schema.md` |
| 2026-10-30 | `SUBSYSTEM_UNRESPONSIVE` is a new fault with no skip | A silent subsystem leaves the robot in an unknown state | `message_schema.md` |
| 2026-11-03 | A stack light on the robot shows status (green running, flashing amber needs the operator, red E-stop). The Supervisor sets it with a `LIGHT` message, the ESP32 drives the lamps | The operator on the roof may not have the screen in view | `complete_system_guide.md` 3.8, `message_schema.md` |
| 2026-11-10 | New Locomotion fault `OVERSHOT_SPOT`: after reaching the spot the robot stops its wheels and checks it is not past it by more than `SPOT_OVERSHOOT_MM`. It is never retried (a retry repeats the whole drive from past the spot, so it would go further past; the robot can reverse, so an automatic back-up is a possible later improvement), the operator puts the robot back where the drive started and presses RESOLVED, and there is no skip. Before this the arrival check was one-sided and an overshoot was reported as `DONE`. | Overshooting went unnoticed, and a retry would have made it worse | `message_schema.md`, `firmware_guide.md` |
| 2026-11-10 | The robot can reverse (DRIVE `distance_mm` is signed). Crest sensor error reaches Locomotion inside the ESP32 (D22). TURN carries the crest count and sideways gap (D25). Roof schematic comes from the team as SVG or DXF, only 4 x 8 ft boards (D23). Beam terms renamed to crest terms (`OFF_BEAM` is now `OFF_CREST`). Localization model written (D24). | Answers to the open questions on the robot, the schematic and the boards | `design_concept.md` D21 to D25 |
| 2026-11-10 | Strips run on past their last screw to the level of the next strip's first screw and turn there, so every strip covers the same stretch and nothing reverses (D26). The TURN command carries `run_out_mm`. Turning at the last screw and reversing stays as an option. | The user asked for consistent strips that only stop at the screw spots | `design_concept.md` D26, `message_schema.md` |
| 2026-11-10 | Fine positioning at each spot: average several crest array readings, nudge sideways by the error if it is outside the accept limit, read again, up to 3 times, then the new Locomotion fault `NOT_ALIGNED` (retried, then the operator, no skip). The `DONE` reports the final `lateral_mm`. | A spot straight after a turn keeps the turn's sideways error (the loop needs a few hundred mm to settle) | `design_concept.md` D27, `message_schema.md` |
| 2026-10-30 | Fastening never replies until the drill is confirmed retracted | Safety | `firmware_guide.md` |

The "added beyond the guide" decisions in the last rows are listed in `message_schema.md` under "Differences from the system guide". Please confirm you agree with them.

## 3. Next steps

Each step says who does it, what it needs, and how you know it is done.

### Phase A: now, with no hardware

| # | Step | Who | Needs | Done when |
|---|---|---|---|---|
| A1 | **Unit-test the firmware logic on the PC.** Install a small C++ compiler. Build the four state machines against a fake clock and fake sensors. Test each flowchart path and each fault. | Claude | A compiler install (about 100 to 300 MB) | Each flowchart path has a passing test, and the tests run with one command |
| A2 | **Run the real firmware in an emulator (Wokwi).** Expose its serial port to the PC and run `robot_main.py` against it. | Claude, with you creating a free Wokwi account | The Wokwi account and VS Code extension | A full simulated run completes between the real Pi code and the real compiled firmware, including camera questions and a pulled "cable" |
| A3 | **Choose the hardware and draw up the pin map.** Motors and drivers, drill and torque sensing, encoders, crest and front sensors, supply sensors, tripwire, stack light (3 outputs, probably via relays or MOSFETs). Check how many ESP32 pins are needed. Design the E-stop circuit and the power layout. | You choose, Claude drafts | Your parts choices, or a short list of candidates to compare | A parts list, a pin map in `config.h`, and a wiring and power diagram |
| A4 | **Start the camera work.** Pick the camera, lens and light. Record photos or video of plates and screws (a webcam or phone is fine to begin). Build the checks `PLATE_ARRIVED`, `PLACEMENT_OK`, `PLATE_SCREW_OK`, `PHOTO_OK`. **Measure the time each takes.** | You record and measure, Claude writes the harness and the vision code | Sample images or a webcam | A latency number, which answers the open question in the guide, and a first version of the checks behind `CameraService` |
| A5 | **Close the open design questions** in section 4. | You | A short conversation | Each question has an answer, written into the guide |
| A6 | **Improve the simulator.** Model the camera `QUERY` and `ANSWER` path. Add dropped, late and duplicated messages. Add an ESP32 heartbeat to the Pi. | Claude | | New tests pass, and the simulator guide is updated |
| A7 | **Make the dashboard work on the real robot**, not just the simulator, so it is the operator screen. Show the real alerts, fault log and camera feed. | Claude | Decision on the operator device (tablet, laptop, built-in screen) | The same page shows live data from `robot_main.py` |
| A8 | **Persist the fault log and a message log to disk**, and decide what happens after a power loss mid-run. | Claude | Your decision on recovery (see section 4) | Logs survive a restart, and the behavior after a restart is defined and tested |

Suggested order: A5 and A3 first (they unblock the rest), A1 in parallel, then A2, then A4 and A6. A7 and A8 can wait until Phase B.

### Phase B: when the ESP32 arrives

| # | Step | Done when |
|---|---|---|
| B1 | Flash the simulated build: `python -m platformio run -t upload` in `firmware/esp32`. Check it sends `READY`. | A `READY` line appears on the serial port |
| B2 | Run `python robot_main.py --port COM5` (your port) and type `start`. | A full simulated run finishes, using the real board and the simulated hardware layer |
| B3 | Fault injection. Add a `--sim` option to `robot_main.py` (small change) and script the camera service to say no. | Every fault code reaches the operator correctly |
| B4 | Pull the USB cable mid-run, and reset the board mid-run. | The board stops safely, the Pi reports the link down, and the Supervisor stops with `SUBSYSTEM_UNRESPONSIVE` |
| B5 | Leave it running for an hour. | No dropped bytes, no growth in memory, no stalled loop |

Expect to find and fix bugs here. The firmware has only been compiled so far.

### Phase C: real hardware, one subsystem at a time

Fill in `hal_esp32.cpp` and the pins for one subsystem, keep the others simulated, test it with the robot safely restrained, then move on. Suggested order, simplest and safest first:

1. **Fastening** (drill, torque sensor, retract switch). Tune the 10 s limit and the torque target. Test that a stuck drill produces no reply.
2. **Plate** (feeder, tripwire, supply sensor, with the real camera).
3. **Screw** (loader, supply sensor).
4. **Locomotion**, with the robot on blocks first. Tune the drive and turn limits and tolerances.

For each: measure how long things really take, replace the placeholders in `config.h` and `Config` (Supervisor), and update `detail.py` and the simulator guide so they match.

### Phase D: whole robot

| # | Step | Done when |
|---|---|---|
| D1 | One full spot on the bench | Plate, screw and fastening complete in order |
| D2 | A short row, then a turn, then a full route on a mock roof section | The route finishes with no operator help |
| D3 | Real faults on purpose: empty hopper, jam, bad screw, dark image, blocked lens, cable pulled | Each is handled as the guide says |
| D4 | Hardware E-stop test, at each stage of a spot | Everything stops, and only a manual reset recovers |
| D5 | Sun, heat, vibration, dust, power dips | No failures, or each failure is understood |
| D6 | Update the guide, the simulator and the documents with what was learned | The documents match the robot |

## 4. Open questions for you

These need your decision. The first four were already open in `complete_system_guide.md`.

1. **Camera latency.** How long do the camera checks take? You said you would find out.
2. **Light failure.** Is a failed light (image too dark) handled as a camera fault (E9)? It is, for now.
3. **Sensor roles.** What does each sensor really do? In particular the plate and screw supply sensors, and the tripwire (does "tripped" mean a plate is there?).
4. **Time limits.** The values for relocating, reaching a spot, turning, and plate arrival.
5. **How far apart are the rows?** The turn needs the gap between crests to approve the encoder position. It is not in the route map yet.
6. **Is the added behavior acceptable?** `QUERY`/`ANSWER`, heartbeats, `SUBSYSTEM_UNRESPONSIVE`, refusing `START` without a camera, retrying locomotion faults.
7. **After a power loss mid-run**, should the robot start again from the beginning, or can the operator tell it which spot it is at?
8. **Which device is the operator screen?** A tablet over the Pi's Wi-Fi is assumed. Is that right, and is Wi-Fi safe to depend on up there?
9. **Which camera, light and enclosure?** And is a Pi camera module enough, or is a USB camera preferred?
10. **One ESP32 or more?** Direction decided 2026-11-09 (D17 in `design_concept.md`): plan for **two** nodes, a Locomotion node (motors, encoders, IMU, sensor array) and a Tool node (Plate, Screw, Fastening), and run one ESP32 on the bench for now. Reasons: the draft pin map (`pin_map.md`) comes to about 30 GPIO plus I2C and is expected to grow, the subsystems are spread out on the chassis, and the drill is a noise source. **Still open:** the transport between nodes (leaning CAN with a gateway ESP32 so the Pi stays on USB serial, RS-485 as the simpler alternative), the board (classic ESP32 versus ESP32-S3, see `pin_map.md` P1), and the cable lengths and measured noise that will decide it. CAN is back on the table, replacing "no longer planned" in `hardware_architecture.md`.
11. **Is skip allowed after an out-of-supply stop?** The guide says yes (E3 and E5 are in E1 to E7). It is implemented that way.
12. **Stack light colours.** The colours and patterns are proposed, not confirmed. Do you want a buzzer, or a different pattern for a refill stop? The real lamp voltage and the driver circuit (relays or MOSFETs) are also undecided.
13. **Can the robot back up?** Answered 2026-11-10: yes. DRIVE `distance_mm` is signed. Since 2026-11-10 the planner no longer needs it by default (strips run on instead, D26). Still open: an automatic back-up after a small overshoot, and the sign of the steering correction while reversing (it holds straight for now).
14. **Overshoot limit.** `SPOT_OVERSHOOT_MM` (30 mm) is a placeholder. It must exceed the distance the robot travels between two encoder samples plus its stopping distance, and be small enough to protect the screw tolerance. It needs the real speed and stopping distance.
15. **The real schematic.** The importer assumes the roof outline is one closed shape and the crests are straight lines, named or not. Send a real file from the team and the naming and unit rules can be adapted to it.
16. **Fine positioning after a turn.** Done in the logic (2026-11-10): a stop-and-nudge step at each spot. Still open: how the robot physically nudges (the S-move in `hal_esp32.cpp` is a TODO), how accurate a nudge is (placeholder 0.1 mm), and whether the +/-0.5 mm tolerance can be met with the real array-to-drill offset and array calibration, which now dominate the model's answer.
17. **Along-row errors pile up.** Each drive starts from wherever the robot stopped, so stopping errors add along a row. Locomotion could remember the last overshoot and take it off the next drive, and the stopping window (sampling period plus stopping distance) is large.

## 5. Known gaps and risks

| Gap or risk | Why it matters | Planned in |
|---|---|---|
| Firmware never run on a board | Logic and timing bugs are likely | A1, A2, B |
| Real hardware layer empty | The robot cannot move yet | C |
| Serial link code never tried with hardware | Reconnect behavior is unproven | B4 |
| All limits are placeholders | Real timing may make faults fire too early or too late | C |
| The Supervisor's timeouts must stay above the subsystems' longest times | Otherwise a real fault is reported as `SUBSYSTEM_UNRESPONSIVE` | C, and the check in `firmware_guide.md` section 9 |
| No acknowledgement of commands | A command lost on the cable is only noticed at the timeout | A6 |
| No heartbeat from the ESP32 to the Pi | A hung board looks like a slow step until the timeout | A6 |
| The fault log is only in memory | Lost on a restart | A8 |
| The Supervisor's position is lost on a restart | The robot cannot resume a run | A8, question 7 |
| The dashboard only shows the simulator | The real robot has no operator screen yet | A7 |
| The stack light is the only status the operator sees without the screen | If its driver fails the robot looks fine when it is not. The screen alert still works. | A3, D |
| The camera is a single point of failure | A dead camera stops the robot (E9) | By design |
| Heat and power on the roof | A Pi in the sun, a drill on a shared supply | A3, D5 |
| Wi-Fi to the operator screen | If it drops, the operator cannot press RESOLVED. The robot stays safely stopped. | Question 8 |
| Three copies of each flowchart (diagrams, `detail.py`, firmware) | They can drift apart | Keep them in step, see `supervisor_code_guide.md` section 7 |

## 6. How to pick the work back up

1. Read `README.md` for the index and `setup_guide.md` for the tools and commands.
2. Run `python -m unittest discover -s tests -t .` in `supervisor` to confirm the tests still pass.
3. Run `python dashboard.py` and try a scenario.
4. Pick the next step from section 3.
5. When something changes, update the matching document. The index in `README.md` says which one.

If you start a new Claude Code session, point it at `README.md` first. It also has a saved memory note about this project (the architecture, where things are, and what is and is not tested).
