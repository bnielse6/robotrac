# Simulator Guide

What the simulator is for, what it does and does not prove, how it works, and how to use it. The code is in `../supervisor/`. For the robot logic itself see `complete_system_guide.md`, and for the messages see `message_schema.md`.

## Table of contents

- [1. Purpose](#1-purpose)
- [2. What it proves and what it does not](#2-what-it-proves-and-what-it-does-not)
- [3. How it works](#3-how-it-works)
- [4. The dashboard, screen by screen](#4-the-dashboard-screen-by-screen)
- [5. Scenarios](#5-scenarios)
- [6. Reading the message log](#6-reading-the-message-log)
- [7. The automated tests](#7-the-automated-tests)
- [8. Running it](#8-running-it)
- [9. Where the simulator ends and real hardware starts](#9-where-the-simulator-ends-and-real-hardware-starts)
- [10. Known limits and placeholders](#10-known-limits-and-placeholders)

---

## 1. Purpose

The robot's control system is a Supervisor (the master state machine) that tells four subsystems what to do and reacts when they succeed, fail or go silent. Most of the difficult design work is in the **reactions**: retries, stopping, alerting, skipping, the camera feed, the E-stop.

The simulator exists so you can **check that logic before any hardware exists**, and keep checking it as the design changes. It does three jobs:

1. **Test the Supervisor.** Run it against fake subsystems that you can make succeed or fail on demand, and confirm it does what the guide says.
2. **Let you see it.** The dashboard shows the state, the robot's position, every message and every alert, so you can understand and demonstrate the behavior without reading code.
3. **Give a safety net.** When the Supervisor code is changed later, the automated tests show straight away if an old rule has broken.

It is also the reference the real ESP32 firmware will be built against. The firmware must behave like the fake subsystems do: answer each command with exactly one `DONE`, `FAULT` or `NEED_REFILL`.

## 2. What it proves and what it does not

**It proves** that the Supervisor logic is consistent with the guide:

- The fixed order: drive, plate, screw, fasten, then the row check.
- Retries: a failed step runs at most 3 times (1 try plus N = 2 retries), then the robot stops.
- The robot never moves on by itself after a failure.
- RESOLVED resumes the same step. SKIP SPOT moves on and is logged.
- Skip is refused for locomotion, camera and unresponsive-subsystem faults.
- A supply that runs out stops the robot at once, with no retry.
- A silent subsystem is timed out and aborted.
- A late or wrong reply is ignored.
- A lost or bad camera feed stops the robot, and RESOLVED is refused until the feed is back.
- The E-stop aborts everything from any state and needs a manual reset.
- Turns alternate right and left, and distances come from the route map.

**It does not prove** anything about the physical world:

- Whether a plate actually jams, a screw actually strips, or a wheel actually slips.
- Whether the camera can really decide "plate arrived" fast enough. This is the open latency question in the guide.
- Whether the timeouts and retry count are right. They are placeholders.
- Motor control, encoder counting, torque sensing or any ESP32 firmware.
- The real USB serial link: cable unplugs, noise, reset on connect.

Passing the simulator means the **decision logic is sound**. It does not mean the robot works.

## 3. How it works

```
 Operator buttons ──┐
                    ▼
              ┌────────────┐   CMD_START / CMD_ABORT    ┌──────────────────┐
              │ Supervisor │ ─────────────────────────► │ Fake subsystems  │
              │ (real code)│ ◄───────────────────────── │ Locomotion       │
              └────────────┘   DONE / FAULT / REFILL    │ Plate  Screw     │
                    ▲                                   │ Fastening        │
                    │  heartbeat (ok / not ok)          └──────────────────┘
              ┌────────────┐
              │ Fake camera│
              └────────────┘
```

- **The Supervisor is the real code** (`roofbot/supervisor.py`), the same file that will run on the Raspberry Pi. It does no I/O of its own. It receives messages and a clock, and it sends messages out.
- **The fake subsystems** come in two kinds. Both answer each `CMD_START` from a **script** you set: succeed, fail with a chosen code, report an empty supply, or never answer. When the script is empty they answer DONE.
  - **Simple stubs** (`roofbot/sim.py`) wait 0.2 s and answer. The fast tests use these.
  - **Detailed subsystems** (`roofbot/detail.py`) are what the dashboard uses. While a step runs, each one walks through its own flowchart (S1 to S5) one node at a time, with a duration for each, and its sensors change as it goes. The scripted outcome decides which branch it takes. See section 4a.
- **The fake camera** sends a heartbeat several times a second saying the image is ok or not ok. You can turn the image bad or stop the heartbeat completely.
- **The world** (`SimWorld`) connects them with a small message delay and a **simulated clock**. Because the clock is a number the world advances, a long run takes milliseconds and every run gives the same result.
- **The messages are the real ones** from `message_schema.md`, so what you see in the log is what will cross the USB cable later.

The dashboard (`dashboard.py` and `ui/index.html`) is a thin layer on top. It advances the simulated clock in real time (adjustable speed), shows what the world contains, and turns button presses into the same messages an operator would send.

## 4. The dashboard, screen by screen

### Scenario and clock

Pick a scenario and press **Load scenario**. You can set the number of rows and spots per row. **Pause**, **Step 0.1 s** (one small tick of simulated time) and the **speed** setting let you slow it down or run it faster.

### Supervisor state

The Supervisor's state chart as a row of boxes. The lit box is where it is now. **WAIT FOR OPERATOR** and **E-STOP** light red. When the robot is stopped, the step it will resume after RESOLVED has a dashed outline. The line under it says what the Supervisor is waiting for, and which retry it is on.

### Roof

One line per row, one circle per spot, in the direction the robot travels (row 2 runs right to left). Green is done, blue is where the robot is, red is where it stopped, amber is skipped.

### Operator screen and buttons

The buttons the operator has: **START**, **RESOLVED**, **SKIP SPOT**, **RESET**, **E-STOP**. A button is dimmed when it would do nothing right now (for example START while running), but it can still be pressed, so you can confirm it is ignored. Below the buttons is the **alert** the operator screen would show: spot, subsystem, fault code, and whether skip is allowed.

### Inside the subsystems

The fastening area card also shows the **stack light** (red, amber and green lamps, flashing when the pattern is `FLASH`), so you can see what the operator on the roof would see. `SimWorld.light` and `light_history` hold the same thing for tests.

Below the main screen is one panel per subsystem (see section 4a), plus a picture of the fastening area.

### Messages

### Message log

Every message, newest at the bottom, with simulated time, sender, receiver, type and details. See section 6. Heartbeats are hidden unless you tick *show heartbeats*.

### Fault log

One line for each stop: when, which spot, which subsystem, which code, and what the operator did (RESOLVED, SKIPPED, ESTOP, or still waiting). This is the fault log the guide describes. **Supervisor notes** underneath lists things it ignored and why (stale replies, buttons pressed at the wrong time, timeouts, retries).

### Tests tab

Runs the automated tests (section 7) and shows each result.

## 4a. Inside the subsystems

Each subsystem has a panel showing what is happening **inside** it while the Supervisor waits for its single answer.

| Part of the panel | What it shows |
|---|---|
| Status and note | Idle, working (which flowchart), not responding, or aborted. The note says what it is doing right now, for example "Camera: plate has arrived". |
| Progress bar | How far through the current flowchart step it is |
| **Flowchart list** | The nodes of that subsystem's flowchart (S1 to S5). The current node is highlighted and pulses. Nodes already visited are shaded. A check shows **YES** or **NO**, a count like ×3 shows how many times a loop went round, and the branch it took is in bold. A node that was never reached stays faint. |
| Sensors | The values the subsystem would read, such as beam sensors, encoder distance, heading, plates left, tripwire, drill position, torque, and the 10 second torque timer. Good and bad values are colored. |
| Path taken | The last visited nodes with their time and result, newest first |
| Break it | Queue a fault for the subsystem's next command(s). Pick an outcome, how many times, and press **Queue**. **Clear** empties the queue. The faults offered depend on the flowchart (Locomotion has a DRIVE or TURN choice). |
| Refill supply | On Plate and Screw. Sets the hopper or magazine back to 12. |

**What each fault looks like inside**

| Fault | What you will see in the flowchart |
|---|---|
| `OFF_BEAM` | Beam check NO, limit not used up, relocate, beam check NO again, and so on, until the limit is used up. Wheels stop, then it reports. |
| `CANNOT_REACH_SPOT` | The encoder creeps up but at-the-spot stays NO. It loops twice and then the limit is used up. |
| `TURN_FAILED` | Turns 90, drives forward, the front sensor never sees the next beam, and the limit is used up. |
| `PLATE_NOT_ARRIVED` | Feed, camera NO, push again, camera NO, push again, camera NO, then the limit is used up. Feed stopped, plate cleared. |
| `PLACEMENT_REJECTED` | The plate arrives and is released, but the camera and tripwire say NO. |
| `SCREW_NOT_IN_POSITION` | The screw loads, but the camera does not see both in the right spot. |
| `TORQUE_TIMEOUT` | The torque meter stalls below the target while the timer climbs to 10 s. Then the drill retracts and it reports. |
| `PHOTO_REJECTED` | Torque is reached, the photo is taken and not accepted. The drill retracts and it reports. |
| Silent | The panel shows NOT RESPONDING. After the Supervisor's timeout it shows ABORTED. |

Every fault ends with the subsystem in its **safe state** (wheels stopped, drill retracted, plate cleared) before the fault is reported, which is the rule from the guide.

**Supplies are real.** The Plate and Screw panels each count what is left (12 to start) and use one per finished spot. Queueing a REFILL outcome empties the hopper. Pressing RESOLVED without refilling just stops again at the same check. Press **Refill supply** first, then RESOLVED.

**The fastening area picture** shows the plate sliding in, the screw loading (offset to the side when it is not lined up), the drill coming down with a torque readout, and a flash when the photo is taken. The camera view turns red when the image is bad, and the light dims. While the robot is driving, the picture says so.

**Timings are placeholders** (a check takes 0.25 s, feeding a plate 0.8 s, drilling 1.5 s, and so on), except the 10 second torque limit. They only make the animation readable.

## 5. Scenarios

| Scenario | What it does | What to look for |
|---|---|---|
| Happy path | Nothing goes wrong | The full loop, a turn at the end of each row, RUN COMPLETE |
| Plate fails once, the retry works | Plate reports `PLATE_NOT_ARRIVED` once | A second `CMD_START` with `try 2`. No alert. The operator is never involved. |
| Plate fails 3 times | Plate reports a fault on every attempt | The robot stops after the 3rd attempt, red alert, fault log entry. RESOLVED resumes at PLATE. SKIP SPOT moves on. |
| Torque times out twice, then works | Fastening fails twice | Two retries, third attempt works, no alert (E6) |
| Screws run out at the first spot | The magazine is emptied and Screw reports `NEED_REFILL` | Stops at once with no retry (E5). Press **Refill supply** on the Screw panel, then RESOLVED. |
| Robot goes off the beam 3 times | Locomotion reports `OFF_BEAM` every time | Stops. SKIP SPOT is refused (E8). |
| Screw subsystem stops answering | Screw accepts the command and goes quiet | After the timeout the Supervisor sends `CMD_ABORT` and stops with `SUBSYSTEM_UNRESPONSIVE` |
| Empty, press START yourself | Nothing queued, not started | Your own experiments |

Things worth trying on the empty scenario:

- Tick *bad image* or *feed dead* mid-run. The robot stops with `CAMERA_FEED_LOST`. RESOLVED is refused until you untick it. SKIP SPOT is always refused.
- Press **E-STOP** at any moment, including while it is waiting for the operator. Everything is aborted. Only RESET then START restarts, and it restarts from row 1, spot 1.
- Queue faults on two different subsystems and see how the retries do not carry over from one step to the next.
- Press RESOLVED or SKIP SPOT while the robot is running. Nothing should happen.

## 6. Reading the message log

| Message | Meaning |
|---|---|
| `CMD_START` (blue) | The Supervisor tells a subsystem to do its step. `#12` is the command's id. `try 2` means it is a retry. |
| `DONE` (green) | The subsystem finished. `↩ #12` says which command it answers. |
| `FAULT` (red) | The step failed, with the reason. |
| `NEED_REFILL` (amber) | The supply is empty. |
| `CMD_ABORT` (dark red) | The Supervisor tells a subsystem to stop safely now. Seen after a timeout, a camera fault or an E-stop. |
| `ALERT` (red) | The Supervisor tells the operator screen the robot has stopped. |
| `START`, `RESOLVED`, `SKIP_SPOT`, `RESET` (purple) | Operator button presses |
| `LIGHT` (grey) | The Supervisor sets the stack light. The same pattern is drawn as three lamps in the fastening area card. |
| `HEARTBEAT`, `READY` (grey) | Liveness messages. Hidden by default. |

The pattern to look for is one `CMD_START`, then exactly one answer carrying the same id. If a command has no answer, a timeout follows. If an answer arrives with the wrong id, it is ignored and appears in the Supervisor notes.

## 7. The automated tests

There are 87 tests in `supervisor/tests/`. They use the same simulator as the dashboard, with no browser. Each one sets up a situation, runs the Supervisor, and checks the result.

| File | What it checks |
|---|---|
| `test_messages.py` | Messages encode and decode correctly, bad lines are rejected (not JSON, wrong version, unknown type, missing fields, too long), the `LIGHT` message needs a known colour and mode, and the serial line framing copes with partial chunks and over-long lines |
| `test_supervisor.py` | The behaviors listed in section 2: happy path, order, turns and distances, retries, stop and alert, RESOLVED, SKIP SPOT and when it is refused, refill, timeouts, stale and wrong-source replies, reboot mid-step, camera faults, E-stop and reset, and the stack light for each state |
| `test_detail.py` | The detailed subsystems: every flowchart edge points at a real node, each fault takes the path described in section 4a, the torque timer reaches 10 s, faults are reported only in a safe state, failing steps finish inside the Supervisor's timeouts, empty hoppers stay empty until refilled, and abort or E-stop stops wheels and drill |
| `test_router.py` | The `QUERY` and `ANSWER` messages, the camera service, and the router that connects the Supervisor to the ESP32 link |
| `test_dashboard.py` | The dashboard backend: every scenario loads, the state can be turned into JSON for the page, bad input gives an error rather than a crash |

Run them from the **Tests tab**, or from a terminal with `python -m unittest discover -s tests -t .`. They should all pass after any change. If one fails, the test name says which rule broke.

## 8. Running it

Install Python 3.9 or newer, then from the `supervisor` folder:

```
python dashboard.py
```

The dashboard opens at `http://127.0.0.1:8765`. Press Ctrl+C in the terminal to stop it. No extra packages are needed.

Other ways to run:

- `python run_sim.py happy` (also `plate-jam`, `refill`, `camera`, `estop`) prints a message trace in the terminal, with no browser.
- `python -m unittest discover -s tests -t .` runs the tests only.

## 9. Where the simulator ends and real hardware starts

The Supervisor does not know whether the other end is a fake or real. That is what allows the stages in the earlier plan:

| Stage | Supervisor | Subsystems | Link | Status |
|---|---|---|---|---|
| 1. Software simulation | Real code | Fake, scripted | In memory | Done (this simulator) |
| 2. Virtual serial | Real code | A script pretending to be the ESP32 | Virtual serial pair | Not started |
| 3. ESP32, no motors | Real code on the Pi | Real firmware that fakes the work with delays | USB serial | Not started |
| 4. Hardware in the loop | Real code on the Pi | Real hardware, one subsystem at a time | USB serial | Not started |

At each stage the same scenarios and the same fault injection apply. The behavior you see in the dashboard is what the real robot should show.

## 10. Known limits and placeholders

- **Timeouts are guesses.** Step timeouts (30 s drive, 30 s turn, 20 s plate, 15 s screw, 25 s fasten) and the camera timeout (1 s) are in `Config` in `supervisor.py`. The guide says the real values must be measured. Only the 10 s torque limit is a real requirement, and it belongs in the fastening firmware, not the Supervisor.
- **The simulator does not model the camera questions.** On the real robot a subsystem sends a `QUERY` to the Pi and waits for an `ANSWER` (see `message_schema.md`). In the simulator the detailed subsystems decide the camera answers themselves from the scripted outcome. The `QUERY` path is tested separately in `tests/test_router.py`.
- **The detailed subsystems are a model of the flowcharts, not of the machine.** Sensor values move on a timer. Nothing responds to physics, and the flowchart loops only happen when a fault is scripted.
- **Fake subsystems always behave exactly as scripted.** Real ones can answer late, answer twice, or answer after being aborted. Add scripts for these if they matter.
- **Messages are never lost or corrupted in the simulator.** Only the unit tests cover bad lines. Dropped messages will matter with a real cable.
- **There is no physics.** Distances in `CMD_START` are sent but nothing moves.
- **Fixed message delay.** The 5 ms delay is the same for every message.
- **The serial link code has not been run on hardware.** Only its line framing is tested.
- **Behaviors added beyond the guide** (heartbeats, `READY`, `RESET`, `SUBSYSTEM_UNRESPONSIVE`, retrying locomotion faults, refusing START without a camera) are listed in `message_schema.md`. Confirm you agree with them.
