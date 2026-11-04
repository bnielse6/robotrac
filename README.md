# Roofing Robot Control System (MSE 4499)

The control system for a robot that fastens plates and screws along rows of a roof. This folder holds the design, the Pi software, the simulator, and the ESP32 firmware.

## Start here

| I want to... | Read or run |
|---|---|
| Understand what the robot does and how it handles errors | `docs/complete_system_guide.md` |
| See how it is built (Pi + ESP32 + camera) | `docs/hardware_architecture.md` |
| See the exact messages between the parts | `docs/message_schema.md` |
| Choose controllers, power and drivers | `docs/electrical_recommendations.md` |
| Try the simulation | `python dashboard.py` in `supervisor/`, then read `docs/simulator_guide.md` |
| Understand the Pi code | `docs/supervisor_code_guide.md` |
| Understand or build the ESP32 firmware | `docs/firmware_guide.md` |
| See what is done, what was decided, and what to do next | `docs/next_steps.md` |
| Install the tools, run commands, or fix a problem | `docs/setup_guide.md` |

## Folders

| Folder | What is in it |
|---|---|
| `docs/` | The design documents, plus `docs/diagrams/` (all `.mmd` sources and `.png` renders) and `docs/original-flowcharts/` (the original hand-drawn flowcharts) |
| `supervisor/` | Python code for the Pi: Supervisor, message schema, simulator, dashboard, tests |
| `firmware/esp32/` | C++ firmware for the ESP32 (PlatformIO project) |

## Documents

| Document | About |
|---|---|
| `docs/complete_system_guide.md` | The robot's behavior: subsystems, the Supervisor state chart, every error (E1 to E10), decisions made, open questions |
| `docs/fault_policy.md` | One page version of the error rules |
| `docs/hardware_architecture.md` | Decision record: Pi 5 (8 GB), ESP32, USB serial, hardware E-stop |
| `docs/electrical_recommendations.md` | Recommended controllers, power, E-stop, drivers, noise handling and bring-up order. A recommendation, not yet a decision |
| `docs/message_schema.md` | The contract between the Pi and the ESP32, including camera questions |
| `docs/simulator_guide.md` | What the simulator is for, its limits, and how to use the dashboard |
| `docs/supervisor_code_guide.md` | A tour of the Python code |
| `docs/firmware_guide.md` | The ESP32 firmware, how to build it, and how to bring it up |
| `docs/next_steps.md` | Status, decision log, open questions, known gaps, and the roadmap in phases |
| `docs/setup_guide.md` | Tools installed on this PC, commands, where files go, troubleshooting, Pi setup outline |
| `docs/design_concept.md` | The long-term design reference: requirements, architecture summary, navigation and sensing concept, and the design decision log. Updated whenever a decision changes |
| `docs/navigation/` | Navigation work: `navigation-notes.md` (the user's notes), `navigation-brainstorm-2026-11-04.md` (the discussion, buy list and bench test plan) and `navigation-plan-2026-11-04.md` (conclusions, what is next, open questions) |

## Status

| Part | State |
|---|---|
| Design (flowcharts, state chart, errors) | Done |
| Message schema | First draft, reviewed against the simulator |
| Supervisor, router, camera service | Written and tested (87 tests) |
| Simulator and dashboard | Written and tested. The dashboard was checked in a headless browser. |
| Pi serial link and `robot_main.py` | Written, **not yet tried on hardware** |
| ESP32 firmware | Written and **compiles** (simulated and real-hardware builds). **Not yet run on a board.** |
| Real hardware layer (`hal_esp32.cpp`) | Empty, every function is a TODO |
| Stack light | Message, Supervisor patterns, simulator and firmware logic done and tested. Lamp pins and driver circuit not chosen. |
| Camera vision code | Not started. `CameraService` answers yes to everything. |
| Timeouts and limits | Placeholders, except the 10 s torque limit. To be measured. |

## Quick commands

    cd supervisor
    python dashboard.py                              the visual simulator
    python -m unittest discover -s tests -t .        all tests
    python robot_main.py --port COM5                 the real thing (needs the ESP32)

    cd firmware/esp32
    python -m platformio run                         build the firmware (or `pio run` if it is on your PATH)
