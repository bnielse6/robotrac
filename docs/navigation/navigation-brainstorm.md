# Navigation brainstorm

Notes from a brainstorm on 2026-11-04, following `navigation-notes.md`. Nothing here is decided. No code or other docs were changed. The terms "beam" and `OFF_BEAM` elsewhere in the docs come from an earlier joist assumption and have not been updated (see the open questions).

## 1. Facts established

| Topic | Answer |
|---|---|
| Surface | The robot drives on **densdeck**, on top of **corrugated steel decking**, on top of steel beams. The beams and the deck are hidden. |
| Roof | Flat. The outline shape varies per job and is **given by the company**. |
| Spot accuracy | As accurate as possible. The screw should land in the **middle of the top of a flute** (the crest). |
| Target | The screw only needs to go **through the flute crest**. It does **not** need to hit the joist. |
| Beam spacing | Known, but **must not be relied on** as the source of position. |
| Beam width | "About 3 ft", to be confirmed by measurement. It is unclear what this refers to (see open questions). |
| Start pose | The **operator places the robot at one of the roof corners**. |
| Radio | GPS and Wi-Fi are likely poor on a roof. Navigation does not need either: the Supervisor, ESP32 and sensors are all on the robot. Only the operator screen depends on Wi-Fi, and the robot stops safely if it drops. |
| Sensor idea | A **ring of magnetic sensors** that reads the steel through the densdeck and produces a vector pointing the way the robot should move, to align it. |

## 2. Ideas from the original notes

- Wheel encoders, an IMU, and some absolute reference (rare earth magnets or a localization camera, never used one before).
- Possibly ROS 2 Nav2, for its waypoint following. The thinking was that the pattern and the space are known, so compute the best path mathematically.
- A **waypoint generator** that turns an uploaded pattern into fastening coordinates `(x, y)`.
- References: OpenMower (lawn mower code) and a coverage path planning paper (links in `navigation-notes.md`).

## 3. Conclusions so far

**Nav2 is probably overkill.** The path is fixed by the roof layout and the robot never leaves it, so there is little to plan. Nav2 would add ROS 2 to the Pi next to a Supervisor that is deliberately pure and clock-injected. Revisit it only if the robot turns out to need real 2D free driving.

**Two separate jobs need two signals:**

| Job | Question | Source |
|---|---|---|
| Along-track | How far down the row am I, and is this the right spot? | Encoders and IMU heading, with absolute fixes to cancel drift (counting flutes may serve as a ruler) |
| Cross-track | Is the screw line over the flute crest? | The magnetic sensor array, giving a lateral error |

**Control shape:** follow the planned line by dead reckoning, and correct sideways from the sensor array. That is a line follower with feed-forward, and a PID on the lateral error or pure pursuit should be enough.

**The deck dominates the magnetic signal.** The steel deck is directly under the densdeck, so it will swamp anything below it. Implications:

- Use **differential or gradient** readings across the ring, so the part of the deck that looks the same to every sensor cancels. This matches the ring idea.
- Expect a **periodic ripple** as the sensors pass crests and valleys. That ripple is the signal when the target is the crest, and it can also act as a flute-counting ruler.
- **Active sensing** (inductive or eddy current, or a magnetometer plus a drive coil) is probably better than passive field sensing, which is weak and will pick up noise from the drill and motors. This needs a bench test, not an argument.

**Start pose:** treat the operator-placed corner as a **coarse prior** only. A small placement error becomes a systematic offset for every row. The first sensor detection should snap the lateral position. The operator should choose the corner and start heading on the UI so the generator knows which way the serpentine runs.

**Waypoint generator** (a pure Python function beside the Supervisor, with unit tests, feeding the route map). It must handle non-rectangular outlines, edge setbacks, row starts and ends, and the serpentine turn sequence, and output `(row, spot, x, y, heading)` in roof coordinates. Today the route map is hand-programmed (rows, spots per row, distances).

## 4. Open questions

1. **Row direction vs the flutes.** Do rows run *along* a flute (the robot holds one crest) or *across* flutes (it crosses a crest every pitch and stops at one per fastener)? These are very different control problems. This is the biggest open question.
2. **What does "beam" mean now?** The joist no longer matters, so what is the "3 ft wide beam" in the notes, and what should the rows and the docs' "beam" terms (`OFF_BEAM`, beam sensors, route map) actually refer to? The docs may need renaming.
3. **Deck dimensions:** flute pitch, crest width, depth, and the densdeck thickness. How wide is the target to hit, and what lateral tolerance follows?
4. **Candidate sensor.** None chosen yet. Suggest two or three (for example a Hall/magnetometer breakout and an inductive one) to compare.
5. **Can the sensor resolve a crest through densdeck?** This is the main technical risk and is cheap to test on the bench.

## 5. Proposed next steps

1. **Bench experiment.** Corrugated deck with densdeck on top. Move a candidate sensor or small ring across it and log the readings. Check whether crests are visible through the densdeck and what the ripple looks like. Claude can write the logging and plotting script once a sensor is picked.
2. **Waypoint generator** and a **localization model in the simulator** with injectable drift, flute-count fixes and lateral sensor fixes. This shows how good the sensing must be before parts are bought.
3. **Update the docs and terminology** once questions 1 and 2 are answered, keeping `complete_system_guide.md`, `message_schema.md`, the simulator (`detail.py`) and the firmware in step.
