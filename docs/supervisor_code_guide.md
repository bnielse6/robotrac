# Supervisor Code Guide (Python, runs on the Pi)

A tour of the code in `../supervisor/`: what each file is for, how the pieces fit together, and how to change things. For the behavior the code implements, see `complete_system_guide.md`. For the messages, see `message_schema.md`. For how to use the simulator, see `simulator_guide.md`.

Requires Python 3.9 or newer. No packages are needed, except `pyserial` for the real serial link.

## Table of contents

- [1. The big picture](#1-the-big-picture)
- [2. Folder layout](#2-folder-layout)
- [3. Module reference](#3-module-reference)
- [4. How a message travels](#4-how-a-message-travels)
- [5. Running things](#5-running-things)
- [6. Common changes](#6-common-changes)
- [7. Design rules to keep](#7-design-rules-to-keep)
- [8. Tests](#8-tests)

---

## 1. The big picture

```
                    ┌────────────────────────────────────────────────┐
  operator ───────► │ Router                                         │ ◄─── ESP32 (serial link)
  (buttons, CLI)    │   ┌─────────────┐     ┌───────────────────┐    │      DONE, FAULT, QUERY...
                    │   │ Supervisor  │     │ CameraService     │    │ ───► CMD_START, CMD_ABORT,
                    │   │ state       │     │ answers QUERYs    │    │      HEARTBEAT, ANSWER
  operator ◄─────── │   │ machine     │     └───────────────────┘    │
  (ALERT)           │   └─────────────┘                              │
                    └────────────────────────────────────────────────┘
```

- The **Supervisor** is a pure state machine. It has no idea what a serial port is. It is driven by `on_message(msg, now)` and `tick(now)` and it sends through a `send` function it is given.
- The **Router** is the glue on the real robot. The **SimWorld** is the glue in the simulator. Both give the Supervisor the same thing to talk to.
- Because the Supervisor never touches I/O, the same code runs in the simulator, in the tests, and on the robot.

## 2. Folder layout

```
supervisor/
  roofbot/                 the package
    messages.py            message types, fault codes, JSON line encode and decode
    route.py               the route map
    supervisor.py          the Supervisor state machine
    router.py              Pi glue: Supervisor + camera service + serial link + operator
    camera_service.py      answers the ESP32's camera questions
    serial_link.py         USB serial: line framing, reconnect
    sim.py                 simple fake subsystems, fake camera, SimWorld
    detail.py              detailed subsystems that walk through their flowcharts
  dashboard.py             the browser dashboard backend
  ui/index.html            the dashboard page
  run_sim.py               print a simulated run in the terminal
  robot_main.py            run the real thing on the Pi
  tests/                   87 tests
  README.md                short how-to
```

## 3. Module reference

### `roofbot/messages.py`

The message format. Everything else imports from here.

| Name | What it is |
|---|---|
| `MsgType` | Every message type: `START`, `RESOLVED`, `SKIP_SPOT`, `ESTOP`, `RESET`, `CMD_START`, `CMD_ABORT`, `DONE`, `FAULT`, `NEED_REFILL`, `ALERT`, `LIGHT`, `HEARTBEAT`, `READY`, `QUERY`, `ANSWER` |
| `Node` | Who a message is from or to: `SUP`, `OPERATOR`, `ESTOP`, `LOCOMOTION`, `PLATE`, `SCREW`, `FASTENING`, `CAMERA`, `LIGHT`, `ALL` |
| `Step` | `DRIVE`, `TURN`, `PLATE`, `SCREW`, `FASTEN` |
| `FaultCode` | All fault codes, including `SUBSYSTEM_UNRESPONSIVE` |
| `Message` | A dataclass with the fields in `message_schema.md`. Enums are turned into plain strings on creation. |
| `encode(msg)` | Message to one newline-terminated JSON line (bytes). Validates first. Refuses lines over 512 bytes. |
| `decode(line)` | One line to a Message. Raises `MessageError` for anything wrong (bad JSON, wrong version, unknown type, missing field, wrong type of field). |
| `validate(msg)` | The per-type rules (for example `FAULT` needs `ref` and a known `code`) |
| `CAMERA_QUESTIONS` | The four questions a subsystem may ask the camera |

To add a message type: add it to `MsgType`, add its required fields to `_REQUIRED`, add any special rule to `validate`, document it in `message_schema.md`, and add a test. Mirror it in `firmware/esp32/src/protocol.cpp` if the ESP32 reads it.

### `roofbot/route.py`

`RowPlan(spots, spacing_mm, start_offset_mm)` is one row. `Route(rows)` is the list of rows. It answers three questions: how many spots are in a row (`spots_in_row`), how far to drive to a spot (`distance_to_spot_mm`: the start offset for spot 1, the spacing for the rest), and which way to turn at the end of a row (`turn_direction`: right after odd rows, left after even). Rows and spots are numbered from 1.

### `roofbot/supervisor.py`

The state machine. Read this one first.

| Name | What it is |
|---|---|
| `State` | `IDLE`, `DRIVE_TO_SPOT`, `PLATE`, `SCREW`, `FASTEN`, `TURN_TO_NEXT_ROW`, `WAIT_OPERATOR`, `RUN_COMPLETE`, `ESTOP` |
| `STATE_STEP` | Which subsystem and step each working state commands |
| `Config` | `max_retries` (N, default 2), `step_timeout_s` per step, `camera_timeout_s`, `heartbeat_interval_s`. The timeouts are placeholders. |
| `Supervisor(route, config, send)` | The machine. `send` is called with every message it wants to send. |
| `on_message(msg, now)` | Feed it every message that arrives, from anywhere (operator, ESP32, camera heartbeat). |
| `STATE_LIGHT` / `_update_light()` | The stack light pattern for each state. `_set_state` calls `_update_light`, which sends a `LIGHT` message only if the pattern changed. `light` holds the last pattern sent. A `READY` forces a resend. |
| `tick(now)` | Call often. Sends heartbeats, checks the camera feed, checks command timeouts. |
| `fault_log` | List of `FaultRecord` (time, row, spot, subsystem, code, detail, operator action) |
| `skipped_spots`, `events`, `transitions` | For the dashboard and tests |
| `camera_usable` | Whether the camera feed is currently usable |

How it works, in short:

1. `START` in IDLE (and the camera usable) puts it at row 1, spot 1 in `DRIVE_TO_SPOT` and sends the first `CMD_START`.
2. Only one command is outstanding at a time. It is stored in `pending` with its id and a deadline.
3. A `DONE` whose `ref` matches `pending` moves to the next state (`_advance`). After FASTEN, `_after_spot` does the row check: more spots, end of row (turn), or run complete.
4. A `FAULT` is retried in place while `retries < max_retries`, otherwise `_stop` moves to `WAIT_OPERATOR` and sends an `ALERT`. `NEED_REFILL` stops at once.
5. `RESOLVED` re-enters the state that stopped. `SKIP_SPOT` goes to the row check if `allow_skip` is true.
6. `ESTOP` sends `CMD_ABORT` to all four subsystems and moves to `ESTOP`. `RESET` returns to IDLE.
7. Replies that do not match `pending` (wrong id or wrong sender) are ignored and noted in `events`.
8. In `tick`, a lost camera feed or an expired command deadline aborts the step and stops with `CAMERA_FEED_LOST` or `SUBSYSTEM_UNRESPONSIVE`. Neither allows skip.

The time `now` is just a number of seconds from any clock. That is what makes it testable.

### `roofbot/router.py`

`Router(route, send_to_link, on_alert, camera, camera_ok, config)` is the Pi's glue.

- `on_link_message(msg, now)`: a message from the ESP32. A `QUERY` goes to the camera service and the `ANSWER` goes straight back. Anything else goes to the Supervisor.
- `on_operator(MsgType, now)`: a button press. Wraps it as a message from the operator (or the E-stop).
- `tick(now)`: sends the Supervisor a camera heartbeat every 0.25 s, with `ok` from the `camera_ok()` function you gave it, then ticks the Supervisor.
- The Supervisor's output is split: `ALERT`s go to `on_alert`, everything else (including `LIGHT`) goes to `send_to_link`, so the ESP32 gets the stack light pattern.

`camera_ok` is where the real camera plugs in: it should return whether frames are arriving and the image is usable.

### `roofbot/camera_service.py`

`CameraService(decide)` answers `QUERY` messages. `handle(query)` returns the `ANSWER`. Scripted answers (`queue("PLATE_ARRIVED", False, False)`) are used first, then `decide(question, query)`, which defaults to yes. **This is where the vision code will go**: pass a `decide` function that looks at the camera image.

### `roofbot/serial_link.py`

- `LineFramer`: turns chunks of bytes into lines, drops over-long lines and recovers. Unit tested.
- `SerialLink(port, on_message, on_error, baud, reconnect_s)`: runs a thread that opens the port, reads lines, decodes them, and reconnects if the cable is pulled. `send(msg)` returns False if the port is down. `connected` says whether it is up. **Not yet tried on real hardware.** Needs `pyserial`.

### `roofbot/sim.py`

The simulator's simple parts, and the world that connects everything.

| Name | What it is |
|---|---|
| `done()`, `fault(code)`, `refill(item)`, `silent()` | Make an `Outcome`, what a fake subsystem answers |
| `StubSubsystem` | Fake subsystem: answers after a fixed delay from a script. `queue(step, *outcomes)` sets the script. Records `commands` and `aborts`. |
| `StubCamera` | Sends a heartbeat. Set `ok` or `silent` to break it. |
| `SimWorld(route, config, latency_s, response_time_s, detailed)` | The Supervisor, four subsystems and a camera on a fake clock. `detailed=True` uses `detail.py`. |

Useful `SimWorld` methods: `start_run()`, `operator(MsgType.X)`, `run(seconds)`, `run_until(predicate, timeout)`, `run_until_state(State.X)`. Everything sent is in `trace`, and operator alerts are in `alerts`.

### `roofbot/detail.py`

`ProcessSubsystem` is a `StubSubsystem` that walks through its own flowchart while a command runs. `FLOWS` holds the flowcharts as data (it is also sent to the dashboard to draw). For each command it builds a list of `Phase`s (a node, a duration, a result for checks, and how the sensors change), plays them out in time, then sends the single reply. Section 4a of `simulator_guide.md` describes what it shows. The timings are placeholders.

To change a flowchart: edit `FLOWS` and the matching builder (`_drive`, `_turn`, `_plate`, `_screw`, `_fasten`), and keep it in step with `docs/diagrams/subsystems/` and with the firmware. `tests/test_detail.py` checks that every edge in `FLOWS` points at a real node.

### `dashboard.py` and `ui/index.html`

`Controller` owns a detailed `SimWorld` and advances it in real time on a thread. `snapshot()` produces everything the page shows. `action()` takes button presses, fault injections, scenario loads and so on. `PRESETS` are the scenarios. `TestRunner` runs the test suite and parses the output. `make_handler` is a plain `http.server` with `/api/state`, `/api/meta`, `/api/action`, `/api/tests`, `/api/run_tests`. The page polls `/api/state` five times a second and redraws. There are no external libraries.

### `run_sim.py`

Prints a terminal trace of a simulated run: `happy`, `plate-jam`, `refill`, `camera`, `estop`.

### `robot_main.py`

The program for the real robot. Opens the serial port, builds a `Router`, and loops at 50 Hz: messages in, operator commands from the keyboard (`start`, `resolved`, `skip`, `estop`, `reset`, `status`, `quit`), `router.tick`. Prints alerts and state changes. **Not yet tried on hardware.**

## 4. How a message travels

One command, on the real robot:

1. The Supervisor decides to place a plate and calls `send(CMD_START to PLATE)`.
2. The Router passes it to `SerialLink.send`, which `encode`s it to a JSON line and writes it to the USB port.
3. The ESP32 runs the Plate flowchart. It sends `QUERY PLATE_ARRIVED`.
4. `SerialLink` reads the line, `decode`s it, and calls `Router.on_link_message`. The Router sees a `QUERY`, asks `CameraService.handle`, and sends the `ANSWER` back.
5. The ESP32 finishes and sends `DONE` with `ref` set to the command's id.
6. `Router.on_link_message` gives it to `Supervisor.on_message`, which matches `ref` to `pending` and moves on.

In the simulator, steps 2 to 5 are replaced by `SimWorld` delivering messages to a `ProcessSubsystem`.

## 5. Running things

From the `supervisor` folder:

| Command | What it does |
|---|---|
| `python dashboard.py` | The browser dashboard |
| `python run_sim.py happy` | A simulated run in the terminal |
| `python -m unittest discover -s tests -t .` | All the tests |
| `python robot_main.py --port COM5` | The real Supervisor with the real ESP32 |

## 6. Common changes

| I want to... | Change |
|---|---|
| Change the route | Build a different `Route` in `robot_main.py` (or the arguments) |
| Change N, the retry count | `Config.max_retries` |
| Change a step timeout | `Config.step_timeout_s`. Keep it above the longest the subsystem can take. |
| Plug in the real camera | Pass `camera_ok=` and a `CameraService(decide=...)` to `Router` in `robot_main.py` |
| Add a fault code | `FaultCode` in `messages.py`, the subsystem that raises it, `detail.py` and its flowchart, `message_schema.md`, firmware, and tests. Decide whether skip is allowed (`allow_skip` in `supervisor.py`). |
| Add a scenario to the dashboard | An entry in `PRESETS` in `dashboard.py` |
| Add a rule to the Supervisor | Add a test in `tests/test_supervisor.py` first, in the style of the existing ones |

## 7. Design rules to keep

- **The Supervisor does no I/O.** No serial ports, files, sleeps, or reading the clock. Pass `now` in.
- **One command at a time.** Never have two `CMD_START`s outstanding.
- **Match replies by `ref` and sender.** Never trust a reply because it merely arrived.
- **The robot never moves on by itself after a failure.** Only `RESOLVED` or `SKIP_SPOT` from the operator does.
- **Every failure path ends in a safe, logged state.** If a new failure path is added, it must call `_stop` and write a `FaultRecord`.
- **Keep the three copies of the flowcharts in step**: `docs/diagrams/subsystems/`, `detail.py`, and the firmware.

## 8. Tests

87 tests in `tests/`. Run them from the dashboard's Tests tab or with the command above. They should pass after every change.

| File | Covers |
|---|---|
| `test_messages.py` | Encode and decode, rejected input, the `LIGHT` message, line framing |
| `test_supervisor.py` | Every rule in the guide, using the simple fake subsystems, including the stack light for each state |
| `test_detail.py` | The detailed subsystems and their flowcharts |
| `test_dashboard.py` | The dashboard backend |
| `test_router.py` | `QUERY` and `ANSWER`, the camera service, the router |

Not covered: `serial_link.py` beyond its framing, `robot_main.py`, and anything on the ESP32. Those need hardware.
