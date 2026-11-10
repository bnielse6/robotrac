# ESP32 Firmware Guide

The firmware that runs the four subsystems (Locomotion, Plate, Screw, Fastening) on the ESP32. The code is in `../firmware/esp32/`. The messages it speaks are defined in `message_schema.md`, and the logic it follows is the S1 to S5 flowcharts in `../design/complete_system_guide.md`.

> **Status: compiles, not yet run on a board.** Both environments build with no warnings (PlatformIO 6.2.0, ESP32 Arduino core, ArduinoJson 7). Using about 26% of flash and 7% of RAM. Nothing has been run on a real ESP32 yet, so the behavior described here is what the code is written to do, not something that has been seen working. Work through the stages in section 8.

## Table of contents

- [1. What the firmware does](#1-what-the-firmware-does)
- [2. Building and flashing](#2-building-and-flashing)
- [3. How it is organised](#3-how-it-is-organised)
- [4. The main loop](#4-the-main-loop)
- [5. The subsystems](#5-the-subsystems)
- [6. The hardware layer](#6-the-hardware-layer)
- [7. Safety behavior](#7-safety-behavior)
- [8. Bringing it up, in stages](#8-bringing-it-up-in-stages)
- [9. Settings](#9-settings)
- [10. File reference](#10-file-reference)
- [11. Known gaps](#11-known-gaps)

---

## 1. What the firmware does

The ESP32 is the Pi's hands. It never decides what happens next. It waits for a command from the Supervisor, carries out one step of one flowchart, and answers with exactly one message.

```
Pi (Supervisor)                         ESP32
   │  CMD_START  step=PLATE  ───────►   Plate subsystem starts its flowchart
   │                                      │  QUERY PLATE_ARRIVED ──────► (Pi camera)
   │  ◄────────────────  ANSWER ok ◄──────┘
   │  ◄──────────────────  DONE  ref=12
```

- Each subsystem is a **non-blocking state machine** that mirrors its flowchart node for node.
- All real-world access goes through one small interface, the **HAL** (`hal.h`). There is a simulated version, so the whole board can be tested with nothing wired up, and a real version to fill in.
- The camera is on the Pi. Subsystems ask it questions over the same serial link (see `message_schema.md`, "Camera questions").

## 2. Building and flashing

You need PlatformIO. Either install the **PlatformIO IDE** extension in VS Code, or run `pip install platformio`.

From `firmware/esp32/`:

| Command | What it does |
|---|---|
| `pio run` | Builds the simulated-hardware firmware (`esp32dev`) |
| `pio run -t upload` | Builds and flashes it over USB |
| `pio run -e esp32dev_real` | Builds the real-hardware version (`esp32dev_real`) |

The first build downloads the ESP32 toolchain and the ArduinoJson library. That is about 5.4 GB of disk space in total and took about 4.5 minutes. Later builds take 15 to 50 seconds.

On this PC PlatformIO was installed with `pip install --user platformio`, and its `pio` command is not on the PATH. Use `python -m platformio run` instead of `pio run`. Build output goes in `firmware/esp32/.pio/`, which is safe to delete (it is rebuilt). The toolchain itself is in `%USERPROFILE%\.platformio`.

**Do not use the serial monitor.** The USB serial port carries only protocol lines. Anything else printed there is read by the Pi as a bad message. For debugging, blink an LED or add a second UART.

## 3. How it is organised

```
firmware/esp32/
  platformio.ini        build settings, two environments (simulated and real hardware)
  include/config.h      every number you might change: limits, tolerances, pins
  src/
    main.cpp            setup(), loop(), message dispatch, heartbeat watchdog
    protocol.h/.cpp     JSON line format, parser, senders, LineReader
    subsystem.h/.cpp    base class: one reply per command, safe before replying
    camera_client.h/.cpp  QUERY and ANSWER with a timeout
    locomotion.h/.cpp   S1 drive straight, S2 turn
    plate.h/.cpp        S3
    screw.h/.cpp        S4
    fastening.h/.cpp    S5
    hal.h               the hardware interface
    hal_sim.cpp         pretend hardware (default)
    hal_esp32.cpp       real hardware, every function a TODO
```

The Python side mirrors this: `supervisor/roofbot/messages.py` is the same message format, and `supervisor/roofbot/detail.py` models the same flowcharts for the simulator.

## 4. The main loop

`loop()` in `main.cpp` does five things, over and over, without ever waiting:

1. **`hal::tick`**. The simulator moves its fake robot. The real HAL updates anything that needs regular attention.
2. **Read lines.** `LineReader` collects bytes into lines. Each line is parsed. A line that does not parse is dropped. Then:
   - `HEARTBEAT`: remember when it arrived.
   - `ANSWER`: give it to the camera client.
   - `LIGHT`: remember the stack light pattern (colour and steady or flash).
   - `CMD_ABORT`: abort that subsystem.
   - `CMD_START`: start that subsystem, if the step belongs to it and the Supervisor is alive.
3. **Watchdog.** If heartbeats were arriving and have stopped for 2 s, abort all four subsystems (see section 7).
4. **`tick` each subsystem.** Each one advances its flowchart if it is due.
5. **Stack light.** `updateStackLight` turns the remembered pattern into lamp on/off (flashing at `LIGHT_FLASH_HALF_PERIOD_MS`) and calls `hal::setStackLight`. While the watchdog has tripped it shows flashing amber instead.

`setup()` opens the serial port and sends `READY`, which tells the Pi the board has just (re)started. Opening the USB port usually resets the board, so expect `READY` every time the Pi connects.

## 5. The subsystems

Every subsystem follows the same contract (`subsystem.h`):

- **One reply per command**: `DONE`, `FAULT` (with a code) or `NEED_REFILL`, carrying the command's id as `ref`.
- **Safe before replying.** `makeSafe()` runs first, then the reply is sent.
- **Abort stops safely and sends nothing.**
- **A new command while busy** stops the old one safely and starts fresh.
- **Never blocks.** A subsystem checks its sensors every 20 ms (`CHECK_PERIOD_MS`) and takes one step.

The state names in each `.h` file match the node names in the flowchart diagrams, so you can read the code next to `docs/diagrams/subsystems/`.

### Locomotion (S1 and S2)

**Drive straight.** `Crest` (on the crest?) leads to `AtSpot` (encoder reached the target?). If not on the crest, `LimitCrest` checks the relocate time limit and either gives up with `OFF_CREST` or goes to `Relocate` and back to `Crest`. If not at the spot, `LimitSpot` either gives up with `CANNOT_REACH_SPOT` or drives on (`Move`) and checks again. Once at the spot, `AtSpot` stops the wheels at once and `Over` (past the spot by more than `SPOT_OVERSHOOT_MM`?) either reports `OVERSHOT_SPOT` or goes on to fine positioning. `Aligned` averages `ALIGN_SAMPLES` readings of the crest array while the robot stands still; within `ALIGN_ACCEPT_MM` it finishes with `DONE`, which carries `lateral_mm` and `along_mm`. Otherwise `LimitAlign` checks the tries (`ALIGN_MAX_ATTEMPTS`, then `NOT_ALIGNED`), `Nudge` calls `hal::nudge()` with the error and `NudgeWait` polls `hal::nudgeDone()` (a timeout is also `NOT_ALIGNED`), and it reads again. The nudge is a small S-move in the hardware layer (turn a few degrees, drive a short way, turn back, take back the distance covered along the row); `hal_esp32.cpp` has it as a TODO. A negative `distance_mm` drives backwards (`hal::driveBackward()`); the encoder counts distance travelled either way.

**Cross-track steering.** While driving, `Locomotion::steer()` runs on every pass of `loop()` (every `STEER_PERIOD_MS`), not once per flowchart node. It low-passes `hal::crossTrackMm()` (the crest sensor array's lateral error, positive = right of the crest), then steers against it with a PD law: `command = -(KP * error + KD * d(error)/dt)`, limited to `STEER_MAX`, through `hal::steer()`. It holds straight while reversing (the sign for reversing is not worked out yet) and while hunting for the crest. The same gains are in `supervisor/roofbot/localization.py`, which models this loop, and a test keeps the two equal. The array's error never goes over the serial link.

**Turn.** If the TURN carries `params.run_out_mm`, `RunOut` first drives on that far past the last spot (the strip runs on to the level where the next strip's first screw is), then `T90a` (turned 90?) with `Turn1` until yes, then drive forward. `Front` loops with `LimitTurn` until the front sensor has counted `params.crests` crests (`hal::crestsCrossed()`), or, if the route map gave no count, until it sees the next crest, or the limit is used up (`TURN_FAILED`). `Enc` then checks the encoder against `params.distance_mm`, the planned sideways gap, to within `TURN_GAP_TOLERANCE_MM`: too short keeps driving, too far means the wrong crest was counted, so it runs out the limit and reports `TURN_FAILED`. Without a gap it only checks `TURN_MIN_FORWARD_MM`. then `T90b` and `Turn2` do the second 90 degree turn. Direction comes from `params.direction`. Right turns are positive heading.

### Plate (S3)

`Supply` (plates available?) or `NEED_REFILL`. Feed the plate, wait a moment (`Settle`), then ask the camera `PLATE_ARRIVED`. If no, `LimitPlate` either gives up (`PLATE_NOT_ARRIVED`, feed stopped, plate cleared) or pushes again and asks again. If yes, `Release` the plate, wait, then ask `PLACEMENT_OK`. The placement is approved only if the camera says yes **and** the tripwire sees the plate. Otherwise `PLACEMENT_REJECTED`.

### Screw (S4)

`Supply` (screws available?) or `NEED_REFILL`. Load the screw, wait, ask `PLATE_SCREW_OK`. Yes means `DONE`. No means clear the screw and `SCREW_NOT_IN_POSITION`.

### Fastening (S5)

Start the drill. `Torque` checks the torque sensor against the target. If low, `LimitTorque` checks the 10 s limit measured from the start of drilling and loops (`keep screwing`) or gives up (`TORQUE_TIMEOUT`). When the torque is right, ask `PHOTO_OK` (the camera takes the photo and judges it). Yes means `DONE`, no means `PHOTO_REJECTED`. **In all three cases the drill is retracted first**, and the reply is sent only after the retract switch says it is retracted. If it never does, no reply is sent and the Supervisor stops with `SUBSYSTEM_UNRESPONSIVE`, which has no skip.

### The camera client

`camera.ask(...)` sends a `QUERY`. `camera.poll(now)` returns `Waiting`, `Yes` or `No`. If no answer arrives within 1.5 s it returns `No`. That makes the check fail safely and the subsystem uses its normal retry path.

## 6. The hardware layer

`hal.h` lists everything the subsystems need: sensor reads (`onCrest`, `encoderMm`, `torqueNm`, ...) and actuator commands (`driveForward`, `feedPlate`, `drillStart`, ...). It also has `setStackLight(red, amber, green)`, which only switches the lamps. `main.cpp` does the flashing, so the HAL stays simple. Actuator commands stay in effect until changed. Everything must return at once.

| Implementation | Chosen by | What it is |
|---|---|---|
| `hal_sim.cpp` | `USE_SIM_HAL=1` (default, `esp32dev`) | Fake robot: drives at 200 mm/s, turns at 90 deg/s, has 12 plates and 12 screws, a drill that builds torque over about 1.6 s. Needs no wiring. |
| `hal_esp32.cpp` | `USE_SIM_HAL=0` (`esp32dev_real`) | Real pins and drivers. **Every function is a TODO.** |

**The unfinished real HAL fails safe.** Its sensors say "no" and the drill never reports retracted, so a robot flashed with it unmodified will not move and the Supervisor will stop with a fault.

**Simulated faults.** With the simulated HAL, a `CMD_START` can carry `"params":{"sim":"OFF_CREST"}` to make the fake hardware misbehave:

| `sim` value | Effect |
|---|---|
| `OFF_CREST` | The crest sensors never see the crest |
| `CANNOT_REACH_SPOT` | The wheels stall after 50 mm (use a target above 50 mm) |
| `OVERSHOT_SPOT` | The robot coasts 60 mm past the target when the wheels stop |
| `NOT_ALIGNED` | Nudges do nothing, so the sideways error never comes inside the limit |
| `DRIFT` | The robot wanders sideways 3 mm/s, so the steering has to work (watch `lateral_mm` in the `DONE`) |
| `TURN_FAILED` | The front sensor never sees the next crest |
| `NO_PLATES`, `NO_SCREWS` | The supply sensor says empty |
| `NO_TRIPWIRE` | The tripwire never sees the plate |
| `TORQUE_LOW` | Torque stops at 1.0 N·m, below the target |
| `STUCK_DRILL` | The drill never retracts (so no reply is ever sent) |

Faults that depend on the camera (plate not arrived, screw not in position, photo rejected) are chosen on the Pi: script the `CameraService` to answer no (`camera.queue("PLATE_ARRIVED", False, False, False)`).

## 7. Safety behavior

| Situation | What the board does |
|---|---|
| No heartbeat for 2 s (after at least one) | Aborts all subsystems: wheels stopped, plate released, drill retracted. Sends no reply. The Supervisor will time out. It resumes only on a new `CMD_START`. |
| No heartbeat for 2 s (after at least one) | Also: the stack light shows flashing amber |
| `CMD_START` arrives with no live heartbeat | Ignored |
| `CMD_START` for a step the subsystem does not do | Ignored |
| `CMD_ABORT` | That subsystem is made safe. No reply. |
| `CMD_START` while already busy | The old command is stopped safely, then the new one starts |
| Camera does not answer | The check counts as "no" |
| Drill never reports retracted | No reply is sent |
| A line is too long, or not valid | Dropped, and the board carries on |
| Board reboots mid-step | Sends `READY`. The Supervisor treats the step as lost. |

**The E-stop is not in this firmware.** It must be a hardware cut to motor and drill power. The ESP32 only reports to the Pi if the Pi tells it to abort.

## 8. Bringing it up, in stages

Do these in order. Each stage proves one more thing.

1. **Build.** `python -m platformio run`. (Done: it compiles.)
2. **Flash and check `READY`.** Flash the simulated build. Run `python -c "import serial; s=serial.Serial('COM5',115200,timeout=3); print(s.readline())"` (change the port). You should see a `READY` line.
3. **Talk to it by hand.** From the `supervisor` folder, run `python robot_main.py --port COM5`. Type `start`. The Supervisor should send commands, the board should answer, and the Pi should answer the board's camera questions with yes. A full run should finish.
4. **Inject faults.** Script the camera service to say no, or edit `robot_main.py` to send a `sim` value, and check each fault reaches the operator with the right code.
5. **Pull the USB cable mid-run.** The board should stop (heartbeat) and the Pi should report the link down and, after the command timeout, `SUBSYSTEM_UNRESPONSIVE`.
6. **Real hardware, one subsystem at a time.** Build `esp32dev_real`. Fill in the pins in `config.h` and the TODOs in `hal_esp32.cpp` for the first subsystem (suggested order: Fastening, Plate, Screw, then Locomotion with the robot on blocks). Keep the other three working. If you can only flash one image, add a per-subsystem switch to `hal_esp32.cpp` that falls back to the simulated behavior for the unfinished ones.
7. **Tune the limits** in `config.h` from measurements.

## 9. Settings

All in `include/config.h`. Everything except the torque limit is a placeholder.

| Setting | Default | Meaning |
|---|---|---|
| `SERIAL_BAUD` | 115200 | Must match the Pi |
| `MAX_LINE_BYTES` | 512 | Longest line, including the newline |
| `HEARTBEAT_TIMEOUT_MS` | 2000 | No heartbeat for this long, stop everything |
| `CAMERA_ANSWER_TIMEOUT_MS` | 1500 | No answer counts as "no" |
| `LIGHT_FLASH_HALF_PERIOD_MS` | 500 | Stack light on for this long, then off for this long |
| `PIN_LIGHT_RED`, `PIN_LIGHT_AMBER`, `PIN_LIGHT_GREEN` | -1 | Stack light outputs (HIGH = lamp on). Not wired yet. A real stack light is usually 24 V, so these will drive relays or MOSFETs, not the lamps directly. |
| `CHECK_PERIOD_MS` | 20 | How often a subsystem looks at its sensors |
| `DRIVE_RELOCATE_LIMIT_MS` | 6000 | Time to find the crest before `OFF_CREST` |
| `DRIVE_SPOT_LIMIT_MS` | 20000 | Time to reach the spot before `CANNOT_REACH_SPOT` |
| `SPOT_TOLERANCE_MM` | 5 | How close counts as "at the spot" |
| `SPOT_OVERSHOOT_MM` | 30 | Past the spot by more than this is `OVERSHOT_SPOT`. Must exceed the distance travelled between two encoder samples (about 16 mm in the simulator) plus the stopping distance. Placeholder |
| `TURN_TURN_LIMIT_MS` | 8000 | Time for each 90 degree turn |
| `TURN_FORWARD_LIMIT_MS` | 15000 | Time to find the next crest |
| `TURN_ANGLE_TOLERANCE_DEG` | 3 | How close counts as "turned 90" |
| `TURN_MIN_FORWARD_MM` | 50 | Smallest forward distance the encoder will approve, used only when the TURN has no `distance_mm` |
| `TURN_GAP_TOLERANCE_MM` | 25 | How close the encoder must be to the planned sideways gap. Must exceed the travel between two samples. Placeholder |
| `CROSS_TRACK_KP` | 0.08 | Steering command per mm of lateral error. Placeholder. Kept equal to `localization.py` by a test |
| `CROSS_TRACK_KD` | 0.04 | Steering command per mm/s of change in the error. Placeholder |
| `CROSS_TRACK_FILTER` | 0.3 | Low-pass on the sensor reading, 0 to 1 |
| `STEER_MAX` | 1.0 | Limit of the steering command |
| `STEER_PERIOD_MS` | 10 | How often the steering is recomputed |
| `CROSS_TRACK_CAPTURE_MM` | 40 | Further off the crest than this and `onCrest()` is false |
| `LATERAL_TOLERANCE_MM` | 0.5 | The target (N4). Reported in the `DONE` |
| `ALIGN_ACCEPT_MM` | 0.2 | At the spot, nudge until the averaged sideways error is within this. Placeholder, kept equal to `localization.py` |
| `ALIGN_MAX_ATTEMPTS` | 3 | Nudges before `NOT_ALIGNED` |
| `ALIGN_SAMPLES` | 8 | Readings averaged before deciding (the robot is standing still) |
| `NUDGE_LIMIT_MS` | 6000 | Time allowed for one nudge before `NOT_ALIGNED` |
| `PLATE_ARRIVE_LIMIT_MS` | 5000 | Time to keep pushing before `PLATE_NOT_ARRIVED` |
| `PLATE_*_SETTLE_MS`, `SCREW_LOAD_SETTLE_MS` | 500 to 800 | Wait after an actuator before asking the camera |
| `TORQUE_LIMIT_MS` | 10000 | **From the guide.** |
| `TORQUE_TARGET_NM` | 4.0 | Placeholder |
| `PIN_*` | -1 | Real hardware pins. -1 means not wired. |

The Supervisor has its own, longer step timeouts (`supervisor/roofbot/supervisor.py`, `Config`). Each must be longer than the longest a subsystem can take, or you get `SUBSYSTEM_UNRESPONSIVE` instead of the real fault. After changing a limit here, check it against the Supervisor's.

## 10. File reference

| File | Contents |
|---|---|
| `main.cpp` | `setup`, `loop`, `handle` (dispatch), watchdog |
| `protocol.h/.cpp` | `Message`, `MsgType`, `protocol::parse`, `sendReady/Done/Fault/NeedRefill/Query`, `LineReader` |
| `subsystem.h/.cpp` | `Subsystem` base class, `reached()` (millis-wrap-safe time check) |
| `camera_client.h/.cpp` | `CameraClient`, the shared `camera` object |
| `locomotion.h/.cpp` | `Locomotion` (steps DRIVE and TURN) |
| `plate.h/.cpp` | `Plate` (step PLATE) |
| `screw.h/.cpp` | `Screw` (step SCREW) |
| `fastening.h/.cpp` | `Fastening` (step FASTEN) |
| `hal.h` | The hardware interface |
| `hal_sim.cpp` | Simulated hardware |
| `hal_esp32.cpp` | Real hardware (TODO) |
| `config.h` | All settings and the pin map |

## 11. Known gaps

- **Compiled but never run.** A clean compile says nothing about behavior. Expect to find logic bugs, especially in timing, when it first runs on a board.
- **The real HAL is empty.** Motor control, encoders, torque sensing and the supply sensors all need writing.
- **The turn's encoder check is crude.** It only checks a minimum forward distance. The route map should give the real gap between rows.
- **No `ACK`.** A command lost on the cable is only noticed when the Supervisor's timeout expires.
- **No live heartbeat from the ESP32 to the Pi**, only `READY` at boot. The Pi cannot tell a hung board from a slow step until the timeout.
- **One Pi-side camera.** The `CameraService` answers yes to everything until the vision code exists.
- **Timings are placeholders.** All of section 9 except the torque limit.
- **No unit tests for the firmware.** The Python tests cover the message format, and the simulator covers the logic, but nothing runs the C++ yet. A host-side test build of the state machines is a good next step.
