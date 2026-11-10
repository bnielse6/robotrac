# Brainstorm, 2026-11-09

Everything discussed in the 2026-11-09 session: the path planner, the roof deck and fastening pattern, the visualization, how the Supervisor fits in, and the hardware split. It continues `navigation/navigation-brainstorm-2026-11-04.md` and `navigation/navigation-plan-2026-11-04.md`. Decisions are in `../design/design_concept.md` (D14 to D18). Status words: **Decided** (the user chose it), **Proposed** (Claude's recommendation), **Open**, **Done**.

## 1. Path planner

**Starting point.** The plan's Step 5, the waypoint generator, was chosen first because it is the only step that needs neither the deck measurements nor the bench test.

**Spots come first, then the path.** The robot drives only to fastening locations, so the path follows from where the screws go. The layers are: roof schematic, then fastening layout, then drive path, then output `(row, spot, x, y, heading)`. For a rectangle the lawnmower with the fewest turns is already optimal, so no search algorithm is needed until the schematic has obstacles or non-rectangular shapes. Decided: rectangle only for now, whole boards only, one pattern variant per roof.

**The densdeck does not enter the planner.** It is a flat layer that does not change any x/y position, so the planner works in one top-down frame. The densdeck matters for sensor standoff and screw length, not for the path.

**The schematic.** The user says the real schematic is a shape with the flute outlines. That means row positions can come from the crest lines directly. Flute pitch stays as a fallback parameter.

**What was built (Done).** `supervisor/roofbot/planner.py` and `tests/test_planner.py`, 14 tests, 101 in all pass. `plan(RoofSpec)` tiles whole 4 x 8 ft boards, stamps the MF-27 pattern, snaps each spot to the nearest crest when a pitch is given, and orders the rows as a lawnmower with alternating headings and a crest count at each row change. Frame: mm, origin at the start corner, x across the flutes, y along them, heading in maths convention. Not modelled yet: cut boards, the running-bond stagger, other start corners, a conversion to `Route` (spot spacing is uneven).

## 2. Deck and fastening pattern

**Densdeck StormX** (product page, 2026-11-09): boards 4 ft wide by 4 or 8 ft long (1219 mm, 1219 or 2438 mm), 5/8 in (15.9 mm) thick, flute spanability 18 in. No edge profile or fastening schedule on the page.

**Installation guide** (`navigation/DensDeck StormX Installation Guide.pdf`): boards are butted tightly with no gapping, laid in a running bond, edge joints on and parallel to the top flutes. Fastening is left to the system manufacturer and FM Global. The 6 in grid marks on the board are an installer reference, not fastening positions. The cutaway shows an **insulation layer** between the steel deck and the densdeck.

**Carlisle MF-27** (`navigation/Fastning Report.pdf`), fastener positions per 4 x 8 ft board, in inches (x across the width, y along the length):

| Variant | Use | Count | Positions |
|---|---|---|---|
| Five | Dens-Deck over insulation of at least 1-1/2 in (40 mm) | 5 | (12,12), (36,12), (24,48), (12,84), (36,84) |
| Eight | Re-roof, polyiso under 1-1/2 in | 8 | x = 12 and 36, y = 12, 36, 60, 84 |
| Either, 4 x 4 ft board | | 4 | x = 12 and 36, y = 12 and 36 |

Decided: the variant depends on the roof, so it is a parameter. The 8 ft board edges run along the flutes. Spot spacing is uneven (36 in in the five variant, with the middle spot only on the center line).

**Consequences.**
- The five variant implies at least 40 mm of insulation, so the sensor standoff could be 56 mm or more (40 + 16). That makes seeing the crest harder. The user will check whether the roof has insulation (Q8).
- Board seams run along the rows, with a cross-seam every 1219 or 2438 mm. With tight butting these are probably small steps. They are an optional SVG layer, not in the planner.
- Spot positions are multiples of 6 in. They land on crests only if the flute pitch divides evenly, for example 6 in. Not measured yet (Q10), so each spot reports its offset from the nearest crest.

## 3. Visualization

Proposed: generate an SVG from the planner output so the path looks like the roof and can be restyled. Named layer groups (`flutes`, `rows`, `spots`, `robot-path`, `outline`), styling in one CSS block, real units (1 unit is 1 mm). Priorities: planner correct first, then a plain accurate plot with numbered spots and travel arrows (this catches bugs), then roof-like styling, then hand-editing for presentation. Avoid an SVG editor in the app, a 3D look, or reading an edited SVG back into planning. The dashboard already draws a route map, and the new view may reuse its page. **Open:** not started. The dashboard code has not been looked at.

## 4. Supervisor and communication

**Path planning stays out of the Supervisor (Decided, D18).** The Supervisor is a pure state machine with no I/O. The planner runs before the run and hands it a `Route`. Cross-track correction runs in Locomotion firmware. Mid-run replanning, if ever needed, would be a new `plan()` call outside the Supervisor. Open: an adapter from `Layout` to `Route`, or a `RowPlan` that takes a list of distances.

**How it communicates.** Every message is one JSON line of at most 512 bytes. The Supervisor sends `CMD_START` to one subsystem at a time and gets exactly one `DONE`, `FAULT` or `NEED_REFILL` back, matched by `id` and sender. One-way `LIGHT` messages set the stack light. Heartbeats run both ways, with a 2 s watchdog on the ESP32. The camera is on the Pi, and ESP32 subsystems ask it with `QUERY` and get `ANSWER`, which the Supervisor never sees.

**Links.** Supervisor to ESP32 is **USB serial**, not Wi-Fi. Inside the Pi everything is in-process. Correction to something said in the session: `../project/next_steps.md` item 8 says a tablet over the Pi's Wi-Fi is assumed for the operator screen, so Wi-Fi is planned for the operator link only, and its safety up on the roof is still an open question.

## 5. Hardware: how many ESP32s

**Facts from the docs.** There is one ESP32 running all four subsystems today. `../design/hardware_architecture.md` said to start with one and split later if needed, `../design/electrical_recommendations.md` said one ESP32-S3 is enough and suggested a two-way split if needed (one for Locomotion, one for Plate, Screw and Fastening), and `../project/next_steps.md` question 10 left it open. The user remembered four separate boards, which the docs never planned.

**Processing is not the limit.** Only one subsystem works at a time, the firmware is non-blocking state machines, and encoder counting is done in hardware on the ESP32. Pin count and noise are the limits.

**Pin map** (`../design/pin_map.md`, draft): about 30 GPIO plus a shared I2C bus, and `config.h` has only 19 pin defines. Missing: a second encoder, motor direction pins, actuators for `clearPlate`, `clearScrew` and `drillRetract`, and E-stop sense. Mismatch to settle (P1): the docs say ESP32-S3 but `platformio.ini` builds `esp32dev`, the classic ESP32, which has far fewer usable pins.

**Direction (Proposed, D17).** Two nodes: Locomotion (motors, encoders, IMU, sensor array, the noise-critical signals) and Tool (Plate, Screw, Fastening, one assembly at the drill). Bench work stays on one board. Four boards would add wiring and failure points without a shown need. Transport between nodes is undecided:
- **CAN with a gateway ESP32.** The Pi stays on USB serial and the Supervisor is untouched. The ESP32 has a built-in CAN controller. The catch is that classic CAN frames carry 8 bytes, so the 512-byte JSON would need fragmenting or a compact binary format on the CAN side. The Pi 5 has no built-in CAN, which is why the gateway is attractive.
- **RS-485** carrying the same JSON lines. Simpler software, but it needs addressing.
- Leaning CAN, but this was not checked against the real wiring.

**Unchanged.** Subsystems talk only to the Supervisor, the hardware E-stop does not depend on any bus, and a lost node must fail safe with its own heartbeat watchdog.

**Not yet known.** Cable lengths and which signals are farthest from where they are read (the user is still building). The most valuable single change if only the sensor array is far from the rest: put its reader beside it.

## 6. Open items

| # | Item | Needed from |
|---|---|---|
| Q8 | Is there an insulation layer, and how thick? | User, will check |
| Q10 | Flute pitch, crest width, flute depth | User, measuring |
| P1 to P5 | Board choice, motor driver, sensor read method, torque method, locations (`../design/pin_map.md`) | User and bench |
| Transport | CAN with gateway or RS-485, after cable lengths and bench noise are known | Bench and chassis layout |
| Cut boards | Pattern for cut boards at the roof edges is not on the MF-27 sheet | User or the Carlisle spec |
| Adapter | `Layout` to `Route` | Claude |
| SVG preview | Layers and styling as in section 3 | Claude |
| Terminology rename | `OFF_BEAM` and the other beam terms, still deferred | Claude |

## 7. Next steps

**Done later the same day:** the SVG preview (`roofbot/planner_svg.py`, `plan_preview.py`, 109 tests pass). Try it with `python plan_preview.py --variant eight --pitch 152.4 -o roof.svg` from `supervisor/`. By default a crest is placed under the board edges.

**To pick up next (in order):**
1. Claude: the `Layout` to `Route` adapter, so the Supervisor and the simulator can run a planned layout. Spot spacing is uneven, so either extend `RowPlan` to take a list of distances or build the adapter around `PlannedRow.distances_mm()`. Add tests, update `../software/supervisor_code_guide.md`, and keep the test counts in `README.md` and `CLAUDE.md` accurate.
2. User: check for insulation under the densdeck (Q8), measure the flute pitch, crest width and depth (Q10), fill in the Location column of `../design/pin_map.md`.
3. Claude: make the firmware split-ready (build environments for the two nodes sharing the protocol code, a heartbeat watchdog per node, check that messages carry enough addressing). Do not write CAN or RS-485 code yet.
4. Bench test of the sensor, which also shows the motor noise that decides the transport.
5. Later: cut boards and the running-bond stagger in the planner, other start corners, the `OFF_BEAM` rename, and a dashboard view of the plan (the dashboard's route map has no geometry today).
