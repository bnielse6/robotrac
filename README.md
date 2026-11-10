# Roofing Robot Control System (MSE 4499)

The control system for a robot that fastens plates and screws along rows of a roof. This folder holds the design, the Pi software, the simulator, and the ESP32 firmware.

## Start here

| I want to... | Read or run |
|---|---|
| Understand what the robot does and how it handles errors | `docs/design/complete_system_guide.md` |
| See how it is built (Pi + ESP32 + camera) | `docs/design/hardware_architecture.md` |
| See the exact messages between the parts | `docs/software/message_schema.md` |
| Choose controllers, power and drivers | `docs/design/electrical_recommendations.md` |
| Try the simulation | `python dashboard.py` in `supervisor/`, then read `docs/software/simulator_guide.md` |
| Understand the Pi code | `docs/software/supervisor_code_guide.md` |
| Understand or build the ESP32 firmware | `docs/software/firmware_guide.md` |
| See what is done, what was decided, and what to do next | `docs/project/next_steps.md` |
| Install the tools, run commands, or fix a problem | `docs/project/setup_guide.md` |
| See why a design choice was made (decision log D1 and up) | `docs/design/design_concept.md` |
| Present the path planning work | `docs/planning/path_planning_findings.md` |
| Find a doc by topic | `docs/README.md` |

## Folders

| Folder | What is in it |
|---|---|
| `docs/` | All documentation, grouped by purpose. Index: `docs/README.md` |
| `docs/design/` | What the robot does and why: system guide, fault policy, hardware, electrical, pin map, design decision log |
| `docs/software/` | How the code works: message schema, Supervisor code guide, simulator guide, firmware guide |
| `docs/project/` | Status, decisions and next steps; setup and troubleshooting |
| `docs/planning/` | Path planning findings (for presenting), brainstorm and navigation records, figures, sample schematics |
| `docs/diagrams/`, `docs/original-flowcharts/` | Flowchart and state chart sources and renders; the original hand-drawn flowcharts |
| `supervisor/` | Python code for the Pi: Supervisor, message schema, simulator, dashboard, tests |
| `firmware/esp32/` | C++ firmware for the ESP32 (PlatformIO project) |

## Code that has its own explanation

| Code | About | Doc |
|---|---|---|
| `supervisor/roofbot/planner.py` | Roof layout planner: whole 4x8 ft boards, MF-27 fastener patterns, drawn outlines, crest snap, lawnmower rows, reversing and turn data. Runs in the simulator and dashboard through `layout_to_route` | `docs/planning/path_planning_findings.md` |
| `supervisor/roofbot/planner_svg.py`, `supervisor/plan_preview.py` | SVG preview of a planned layout, with named layers and one style block to restyle | `docs/software/supervisor_code_guide.md` |
| `supervisor/roofbot/schematic.py`, `docs/planning/samples/` | Reads a roof schematic (SVG or DXF) into an outline and crest positions | `docs/software/supervisor_code_guide.md` |
| `supervisor/roofbot/shapes.py` | Library of common roof outlines (L, T, U, H, plus, ...) | `docs/software/supervisor_code_guide.md` |
| `supervisor/roofbot/localization.py`, `supervisor/accuracy_study.py` | Model of how accurately Locomotion's cross-track control stops at each spot (is +/-0.5 mm achievable?), placeholder numbers | `docs/planning/path_planning_findings.md` |

## Status

| Part | State |
|---|---|
| Design (flowcharts, state chart, errors) | Done |
| Message schema | First draft, reviewed against the simulator |
| Supervisor, router, camera service | Written and tested (229 tests) |
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
