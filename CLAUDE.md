# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Control system for a roofing robot (MSE 4499 capstone). A Raspberry Pi 5 runs a Supervisor state machine, vision and an operator UI. An ESP32 runs four subsystems (Locomotion, Plate, Screw, Fastening) over USB serial. No git repo. Windows, PowerShell/Git Bash. `README.md` is the index to all docs, and `docs/next_steps.md` has status, the decision log and open questions.

## Commands

Python 3.12 is installed per-user and is not on the PATH of terminals opened before the install. If `python` fails, use `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`. All Python commands run from `supervisor/`:

```
python -m unittest discover -s tests -t .                 # all tests (229, ~1 s)
python -m unittest tests.test_supervisor.Retries -v       # one class
python -m unittest tests.test_supervisor.Retries.test_three_failures_stop_and_alert   # one test
python dashboard.py                                       # visual simulator at http://127.0.0.1:8765 (--port N, --no-browser)
python run_sim.py happy                                   # terminal trace (happy, plate-jam, refill, camera, estop)
python robot_main.py --port COM5                          # real Supervisor against a real ESP32
python plan_preview.py --variant eight --pitch 152.4 -o roof.svg   # SVG of a planned roof
python accuracy_study.py --shape L --variant eight        # can the +/-0.5 mm sideways tolerance be met? (placeholder numbers)
```

Firmware, from `firmware/esp32/` (`pio` is not on the PATH, use `python -m platformio`):

```
python -m platformio run                  # simulated-hardware build (env esp32dev)
python -m platformio run -e esp32dev_real # real-hardware build
python -m platformio run -t upload
```

There is no linter configured. There are no firmware tests. A first PlatformIO build downloads about 5 GB.

## Architecture

**The Supervisor does no I/O.** `supervisor/roofbot/supervisor.py` is a pure state machine driven by `on_message(msg, now)` and `tick(now)`, sending through an injected `send` callable. `now` is any number of seconds, never read from a clock inside. This lets one implementation run in the tests, the simulator (`sim.py`, fake clock) and on the robot (`router.py`, real serial). Keep it that way.

**Message flow.** Everything is a `Message` (`messages.py`) sent as one JSON line, max 512 bytes. The Supervisor commands one subsystem at a time with `CMD_START` (carries `id`); the subsystem answers with exactly one `DONE`, `FAULT(code)` or `NEED_REFILL` whose `ref` is that `id`. The Supervisor ignores any reply whose `ref` or sender does not match its outstanding command. Subsystems never talk to each other. The Supervisor also sets the stack light with a one-way `LIGHT` message on every state change (patterns in `STATE_LIGHT`, `supervisor.py`); the ESP32 does the flashing and shows flashing amber if the heartbeat stops. Retries (N=2) are counted by the Supervisor, never the subsystem. After retries run out it stops in `WAIT_OPERATOR` and only the operator (`RESOLVED`, `SKIP_SPOT`) moves it on. Skip is refused for locomotion, camera and `SUBSYSTEM_UNRESPONSIVE` faults.

**The camera lives on the Pi but is used mid-step by ESP32 subsystems.** They send `QUERY` and the Pi's `Router` hands it to `CameraService`, which returns `ANSWER`. The Supervisor state machine never sees these. The Supervisor only sees a camera `HEARTBEAT` (`params.ok`) and stops the robot with `CAMERA_FEED_LOST` if it goes bad. `CameraService` answers yes to everything until vision code is plugged in.

**Two simulator fidelities, on purpose.** `sim.py` `StubSubsystem` answers after 0.2 s and is what the fast Supervisor tests use. `detail.py` `ProcessSubsystem` walks each subsystem's S1 to S5 flowchart node by node with sensors and supplies, and is what the dashboard uses (`SimWorld(route, detailed=True)`). The detailed model takes seconds of simulated time per step, so tests using it need long `run_until` timeouts. Its camera checks are internal, not `QUERY`/`ANSWER`.

**Three copies of each subsystem flowchart must stay in step**: `docs/diagrams/subsystems/S*.mmd`, `FLOWS` plus the builders in `supervisor/roofbot/detail.py`, and the state machines in `firmware/esp32/src/{locomotion,plate,screw,fastening}.cpp` (their state names match the node names). `tests/test_detail.py` only checks that `FLOWS` is internally consistent.

**Firmware.** Non-blocking state machines (`subsystem.h` base class: one reply per command, `makeSafe()` before any reply, abort sends no reply). All hardware goes through `hal.h`, with `hal_sim.cpp` (default, fake robot, optional `params.sim` fault in `CMD_START`) or `hal_esp32.cpp` (every function is a TODO that fails safe). Main loop has a Supervisor-heartbeat watchdog (2 s) that aborts everything. `hal::setStackLight` switches the stack light lamps. Fastening deliberately sends no reply until the drill's retract switch confirms.

**Roof planning.** `roofbot/planner.py` turns a roof (rectangle, drawn outline, or an SVG/DXF schematic read by `schematic.py`) into rows of spots; `layout_to_route` hands the Supervisor a `Route` whose distances are signed (negative = reverse) and whose rows carry the crest count and sideways gap for the turn. The dashboard's Roof plan tab drives all of it. The robot turns at the level of the next strip's first screw (it runs on past its last screw if needed), never along the roof edge, and nothing reverses by default (`turn_style`). `localization.py` models Locomotion's cross-track loop; its gains must equal `firmware/esp32/include/config.h` (a test checks).

## Things that will bite you

- **Never `Serial.print` text in the firmware.** The port carries only protocol lines.
- **The Supervisor's step timeouts (`Config.step_timeout_s`) must exceed the longest a subsystem can take**, in both `detail.py` and firmware `config.h`, or a real fault shows up as `SUBSYSTEM_UNRESPONSIVE`. `tests/test_detail.py::test_failing_steps_finish_inside_the_supervisor_timeouts` checks the simulator side.
- **Alerts and other messages have delivery latency in `SimWorld`** (5 ms). After an action, `run(0.1)` before reading `world.alerts`.
- **`SimWorld.start_run()` runs 0.1 s first** because the Supervisor refuses START until it has seen a camera heartbeat.
- **Port 8765 may hold a stale `dashboard.py`** from an earlier session, serving old code. Kill it before restarting.
- All timeouts, tolerances and speeds are placeholders except the 10 s torque limit. The firmware compiled before 2026-11-10 but has never run on a board, and the changes since (overshoot check, reverse driving, turn data, cross-track steering, the crest renames) have **not been compiled** (no PlatformIO here). `serial_link.py` beyond its line framing and `robot_main.py` have never touched hardware.

## Documentation

The owner asked that all code be documented. When changing behavior, update the matching doc: messages in `docs/message_schema.md`, Python in `docs/supervisor_code_guide.md`, simulator and dashboard in `docs/simulator_guide.md`, firmware in `docs/firmware_guide.md`, and status or decisions in `docs/next_steps.md`. Keep test counts and status tables in `README.md` accurate. `docs/complete_system_guide.md` is the source of truth for intended robot behavior (error rules E1 to E10, subsystem flows), and `docs/message_schema.md` lists every deliberate departure from it.
