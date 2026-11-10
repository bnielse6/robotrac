# Navigation plan

Written 2026-11-04 from `navigation-brainstorm-2026-11-04.md`. This is the working document: what we concluded, what we are doing about it, and what comes next. The brainstorm stays as the record of how we got here. Decisions that affect the whole robot are copied into `../design_concept.md`, which is the long-term reference.

**Update 2026-11-10.** Step 5 (waypoint generator), Step 6 (localization model, `roofbot/localization.py`), Step 7 (the beam rename: `OFF_BEAM` is now `OFF_CREST`) and the control-path part of Step 8 are done. Q6 is answered: the crest array error stays inside Locomotion on the ESP32 (design decision D22). Q7 is still open; the model shows along-row errors add up between spots. The bench test (Steps 1 to 4) is still to do, and every sensor number in the model is a placeholder until then. This document still uses the old word beam in places; it is kept as the record.

Status words used below: **Decided** (the user chose it), **Proposed** (Claude's recommendation, not yet confirmed), **Open** (needs information), **Done**.

## 1. What we are solving

The robot drives a **lawnmower pattern** over a flat roof, going up and down the roof along the flutes of the steel deck. It stops at fastening spots and puts a screw through the **crest** of a flute. It drives on densdeck over corrugated steel deck, so the deck is hidden from any camera.

Two jobs, two signals:

| Job | Question | Source |
|---|---|---|
| Along-track | How far down the row am I, and is this the right spot? | Wheel encoders and IMU heading, with absolute fixes to cancel drift |
| Cross-track | Is the screw line over the crest? | A small sensor array that reads the steel deck through the densdeck |

## 2. Conclusions and the decisions made from them

| # | Conclusion or decision | Status |
|---|---|---|
| N1 | Rows run **along** the flutes. The robot crosses flutes only when it changes rows. | Decided |
| N2 | "Beam" in the old docs means **the flute being screwed into**. The old joist meaning is gone. | Decided |
| N3 | The sensor must find the **crest**, not the valley. | Decided |
| N4 | Lateral tolerance of the screw line against the crest center is **+/-0.5 mm** (may change). This is tight: see section 5. | Decided, may change |
| N5 | Nav2 is overkill. The path is fixed by the roof layout, so use dead reckoning plus sensor correction. | Proposed |
| N6 | Control is a **line follower with feed-forward**. Follow the planned line by dead reckoning, correct sideways from the sensor array. A PID on the lateral error or pure pursuit should be enough. | Proposed |
| N7 | Use **differential** readings (one sensor minus another), because the deck dominates the signal and the common part cancels. | Proposed |
| N8 | Use a **diamond-shaped array** instead of a ring: left and right tips for cross-track error, front and rear for heading. | Decided (the user's idea; sizing proposed) |
| N9 | Diamond width `w` is about **half the flute pitch** (`w = p/2`) and at least the sensor standoff height. A full pitch gives no signal. | Proposed, needs the measurements |
| N10 | Prefer **active sensing** (inductive or eddy current) over passive field sensing. | Proposed, needs the bench test |
| N11 | The operator-placed corner is a **coarse prior** only. The first crest detection snaps the lateral position. | Proposed |
| N12 | Counting crests passed is a **ruler** for the sideways move at a row change. | Proposed |
| N13 | Build a **waypoint generator** (a pure function with unit tests) that outputs `(row, spot, x, y, heading)` in roof coordinates. | Proposed |
| N14 | The array only holds the lock on a crest. **Encoders and the known layout choose which crest**, because every crest looks the same. | Proposed |

## 3. What is being done now

| Item | State |
|---|---|
| Brainstorm and decisions written up | Done (`navigation-brainstorm-2026-11-04.md`, sections 1 to 10) |
| Buy list for three test sensors | Done in the doc, nothing ordered yet |
| Bench test plan | Written (brainstorm section 10), not run |
| Deck measurements (pitch, crest width, depth, densdeck thickness, standoff) | Waiting on the user, in person |
| Terminology rename (`OFF_BEAM` and others) | Not started, deliberately deferred |
| Code | Nothing changed. The Supervisor, simulator and firmware are as before. |

## 4. What to do next, in order

**Step 1: measure the deck (user, in person).** Fill in the table in brainstorm section 7: flute pitch, crest width, flute depth, densdeck thickness, planned sensor height. Also record the real tolerance of the screw and drill, since the +/-0.5 mm may be relaxed or tightened by it.

**Step 2: order the test sensors (user).** One each of the three in brainstorm section 9, plus the test-rig extras. Check part numbers and stock first, because they were written from memory.

**Step 3: run the bench test (user, with Claude writing the logging script).** Follow brainstorm section 10. Bring back the numbers for each sensor, standoff and `w`.

**Step 4: choose the sensor and size the diamond (Claude and user).** From the results, pick the sensor, the standoff and `w`. Then update `../design_concept.md` and mark N8 to N10 as decided or changed.

**Step 5: waypoint generator (Claude).** Pure Python beside the Supervisor, with unit tests. Handle non-rectangular outlines, edge setbacks, row starts and ends, and the serpentine turn sequence.

**Step 6: localization model in the simulator (Claude).** Add injectable drift, crest-count fixes and lateral sensor fixes with the measured noise. This shows whether +/-0.5 mm is achievable before the mechanical design is frozen. Optionally a small `w/p` sweep to confirm the sizing rule.

**Step 7: rename the beam terms (Claude).** Change `OFF_BEAM`, "beam sensors" and the route map wording to flute-based terms. This must stay in step across `complete_system_guide.md`, `message_schema.md`, `supervisor_code_guide.md`, `detail.py`, the tests and the firmware. See `CLAUDE.md`.

**Step 8: hardware path (later).** Turn the chosen sensor into a firmware reading through `hal.h` and `hal_esp32.cpp`, and decide how the cross-track error reaches the Locomotion subsystem.

## 5. Risks and things to watch

- **+/-0.5 mm is very tight.** The sensor blur (about as wide as its height above the metal), wheel slip, steering backlash, chassis flex and the offset between the sensor and the drill all add up in that budget. Options if it is not achievable: a wider screw target, a stop-and-nudge fine positioning step, or a floating drill head.
- **The crest may not be visible through the densdeck** at the real standoff. This is the main technical risk and is why the bench test comes first.
- **Motor and drill noise** may swamp the signal, especially for passive sensors.
- **Crest ambiguity:** a lock on the wrong crest looks the same as the right one (N14).
- **Part numbers are unverified** (brainstorm section 9).

## 6. Open questions

| # | Question | Needed from |
|---|---|---|
| Q1 | Flute pitch, crest width, flute depth. (Densdeck thickness answered 2026-11-09: 15.9 mm.) | User, measuring |
| Q2 | Achievable sensor height above the densdeck | User and mechanical design |
| Q3 | What the "3 ft wide beam" in `navigation-notes.md` referred to, now that "beam" means the flute | User |
| Q4 | Real tolerance of the screw and drill, which sets how firm the +/-0.5 mm is | User |
| Q5 | Which sensor wins the bench test | Bench test |
| Q6 | How the cross-track error reaches Locomotion (a new message, or inside the Locomotion subsystem) | Claude and user, after Q5 |
| Q7 | Whether any absolute fix is needed beyond crest counting (magnets, a camera) | Simulator results |
| Q8 | Is there an insulation layer between the steel deck and the densdeck, and how thick? It adds to the sensor standoff. The installation guide's cutaway shows one. (Added 2026-11-09) | User, will check |
| Q9 | **Answered 2026-11-09**: Carlisle MF-27 (`Fastning Report.pdf`). Per 4x8 ft board, 5 fasteners (Dens-Deck over insulation of at least 40 mm) at (12,12), (36,12), (24,48), (12,84), (36,84) in, or 8 fasteners (re-roof, polyiso under 40 mm) at x = 12 and 36 in, y = 12, 36, 60, 84 in. 4x4 ft board: 4 fasteners at x = 12 and 36, y = 12 and 36. Which variant applies depends on the roof, so it is a parameter. Board long edges run along the flutes. | Done |
| Q10 | Flute pitch decides whether spots land on crests. Not measured yet. | User, measuring |
