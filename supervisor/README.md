# Supervisor (Raspberry Pi side)

Python code for the roofing robot Supervisor, the message schema, and a simulator.
The written contract is `../diagrams/message_schema.md`.

Needs Python 3.9 or newer. Nothing else for the simulator and tests. `pyserial` is only needed for the real serial link.

## Visual dashboard (easiest way to see what is happening)

    python dashboard.py

It opens http://127.0.0.1:8765 in your browser. No extra packages needed.

- **Simulator tab:** pick a scenario and press Load. Watch the Supervisor state, the robot moving across the roof,
  the operator screen, and every message between the Supervisor and the subsystems. Press the operator buttons yourself,
  queue faults on any subsystem, break the camera, pause or single-step time, or speed it up.
- **Tests tab:** runs the whole automated test suite and shows each test as passed or failed.

## Run the tests

From the command line instead:

From this folder:

    python -m unittest discover -s tests -t .

## Run a simulated roof

    python run_sim.py happy
    python run_sim.py plate-jam
    python run_sim.py refill
    python run_sim.py camera
    python run_sim.py estop

## Layout

| File | What it is |
|---|---|
| `roofbot/messages.py` | Message types, fault codes, JSON line encode and decode with validation |
| `roofbot/route.py` | Route map: rows, spots, distances, turn direction |
| `roofbot/supervisor.py` | The state machine. No I/O. Driven by `on_message(msg, now)` and `tick(now)` |
| `roofbot/sim.py` | Simple fake subsystems and camera, and `SimWorld` that wires them to the Supervisor on a fake clock |
| `roofbot/detail.py` | Detailed subsystems that walk through their own flowcharts (S1 to S5) with sensors. Used by the dashboard (`SimWorld(route, detailed=True)`) |
| `roofbot/router.py` | Pi glue: Supervisor + camera service + ESP32 link + operator |
| `roofbot/camera_service.py` | Answers the ESP32's camera questions (QUERY to ANSWER). Plug the vision code in here. |
| `roofbot/serial_link.py` | Line framing and the USB serial link to the ESP32 (not yet tried on hardware) |
| `robot_main.py` | Runs the real Supervisor against the real ESP32 (`python robot_main.py --port COM5`, not yet tried on hardware) |
| `tests/` | 80 tests: messages, Supervisor rules, detailed subsystems, dashboard backend, router and camera service |

A tour of all of this is in `../diagrams/supervisor_code_guide.md`.

## Writing a test

    w = make_world()
    w.plate.queue(Step.PLATE, fault(FaultCode.PLATE_NOT_ARRIVED), fault(FaultCode.PLATE_NOT_ARRIVED))
    w.start_run()
    w.run_until_state(State.RUN_COMPLETE)

`queue()` scripts what a stub answers to each command for a step. Once the script is used up it answers DONE.
Use `silent()` for a subsystem that never answers, `refill("PLATES")` for an empty supply, and
`w.camera.ok = False` or `w.camera.silent = True` for camera problems. Alerts for the operator land in `w.alerts`.
Every message is in `w.trace`.

## Values that are placeholders

`Config.step_timeout_s` (30, 30, 20, 15, 25 seconds) and `camera_timeout_s` (1 s) are guesses.
The guide says these still need to be measured.
