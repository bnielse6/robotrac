# Message Schema

The contract between the Supervisor (Raspberry Pi 5) and the ESP32 subsystems, and between the Supervisor and the operator screen. The code is in `../supervisor/roofbot/messages.py`. If this file and the code disagree, fix one of them.

## Framing

One JSON object per line over USB serial, 115200 baud to start. Lines end in `\n` (a `\r` before it is ignored). **Maximum 512 bytes per line, including the newline.** A line that is too long, is not valid JSON, or fails validation is dropped and logged. It never crashes the receiver.

```
{"v":1,"type":"CMD_START","src":"SUP","dst":"PLATE","id":12,"row":1,"spot":3,"attempt":1,"step":"PLATE","t":41.2}
```

## Fields

| Field | Type | Meaning |
|---|---|---|
| `v` | int | Protocol version. Always 1 for now. Reject anything else. |
| `type` | string | One of the message types below |
| `src`, `dst` | string | `SUP`, `OPERATOR`, `ESTOP`, `LOCOMOTION`, `PLATE`, `SCREW`, `FASTENING`, `CAMERA`, `ALL` |
| `id` | int | Set by the Supervisor on each `CMD_START`. Unique per run. |
| `ref` | int | On `DONE`, `FAULT`, `NEED_REFILL`: the `id` of the `CMD_START` being answered |
| `row`, `spot` | int | Position, counted from 1 |
| `attempt` | int | 1 for the first try, 2 for the first retry, 3 for the second |
| `step` | string | `DRIVE`, `TURN`, `PLATE`, `SCREW`, `FASTEN` |
| `code` | string | Fault code (see below) |
| `params` | object | Extra data for that message type |
| `t` | number | Sender's clock in seconds. For logs only. Never used for decisions. |

Fields that do not apply are left out. Unknown fields are ignored, so they can be added later.

## Messages

| Type | Direction | Required fields | Notes |
|---|---|---|---|
| `START` | Operator to SUP | | Only accepted in IDLE, and only if the camera feed is usable |
| `RESOLVED` | Operator to SUP | | Only in WAIT_OPERATOR. Resumes the same step. Refused for a camera fault until the feed is back. |
| `SKIP_SPOT` | Operator to SUP | | Only in WAIT_OPERATOR. Refused for locomotion and camera faults, and for unresponsive subsystems. |
| `ESTOP` | E-stop to SUP | | Any state. Hardware also cuts power. |
| `RESET` | Operator to SUP | | From ESTOP or RUN_COMPLETE back to IDLE |
| `CMD_START` | SUP to subsystem | `id` `row` `spot` `attempt` `step` | `params`: DRIVE has `distance_mm`, TURN has `direction` (`RIGHT` or `LEFT`) |
| `CMD_ABORT` | SUP to subsystem | | Stop safely now: wheels stopped, plate released, drill retracted. No reply needed. |
| `DONE` | Subsystem to SUP | `ref` | Step finished and the subsystem is in a safe state |
| `FAULT` | Subsystem to SUP | `ref` `code` | Step failed. Subsystem is already in a safe state. |
| `NEED_REFILL` | Plate or Screw to SUP | `ref`, `params.item` | `item` is `PLATES` or `SCREWS`. No retry. |
| `ALERT` | SUP to operator | `code` | `params`: `subsystem`, `allow_skip`, `detail`. `row` and `spot` are included. |
| `LIGHT` | SUP to LIGHT (the stack light) | `params.color`, `params.mode` | `color` is `GREEN`, `AMBER`, `RED` or `OFF`. `mode` is `STEADY` or `FLASH`. Output only, no reply. Sent when the pattern changes and again after a `READY`. The ESP32 does the flashing. |
| `HEARTBEAT` | SUP to ALL, and camera to SUP | | Camera adds `params.ok` (false for a blocked lens or a dark image) |
| `READY` | Subsystem to SUP | | Sent once after every boot. If a step was running, it is lost. |
| `QUERY` | Plate, Screw or Fastening to CAMERA | `id`, `params.question` | A question for the camera. `question` is `PLATE_ARRIVED`, `PLACEMENT_OK`, `PLATE_SCREW_OK` or `PHOTO_OK` (take the photo and say if it is accepted). `row` and `spot` are included. The Pi, not the Supervisor, answers it. |
| `ANSWER` | CAMERA to the asking subsystem | `ref`, `params.ok` | `ref` is the `id` of the `QUERY`. `ok` is true or false. |

`params` can also carry `sim` on a `CMD_START` (for example `"sim":"OFF_BEAM"`). Only the simulated-hardware firmware reads it. The Supervisor never sends it.

## Stack light

The Supervisor sets the light from its state and sends `LIGHT` only when the pattern changes (and again on `READY`, because the board that drives the lamps may have just restarted).

| Supervisor state | `color` | `mode` |
|---|---|---|
| IDLE, RUN_COMPLETE | `GREEN` | `FLASH` |
| DRIVE_TO_SPOT, PLATE, SCREW, FASTEN, TURN_TO_NEXT_ROW | `GREEN` | `STEADY` |
| WAIT_OPERATOR | `AMBER` | `FLASH` |
| ESTOP | `RED` | `STEADY` |

If the ESP32 stops hearing the Supervisor heartbeat (the same 2 s watchdog that aborts the subsystems), it shows `AMBER` `FLASH` by itself, because the robot has stopped and nobody is telling the light anything. The light is dark until the first `LIGHT` arrives.

## Fault codes

`PLATE_NOT_ARRIVED`, `PLACEMENT_REJECTED`, `SCREW_NOT_IN_POSITION`, `TORQUE_TIMEOUT`, `PHOTO_REJECTED`, `OFF_BEAM`, `CANNOT_REACH_SPOT`, `TURN_FAILED`, `CAMERA_FEED_LOST`, `NEED_REFILL`, `ESTOP`, and `SUBSYSTEM_UNRESPONSIVE`.

The first eight, plus `NEED_REFILL`, come from the guide (E1 to E8, and E3 and E5). `CAMERA_FEED_LOST` is E9 and `ESTOP` is E10. A subsystem sends only `FAULT` codes from its own row in section 7 of the guide. **`SUBSYSTEM_UNRESPONSIVE` is new**: the Supervisor raises it itself when a command times out or a subsystem reboots mid-step. It has no skip.

## Rules both sides follow

1. **Answer with `ref`.** The Supervisor ignores any `DONE`, `FAULT` or `NEED_REFILL` whose `ref` is not its outstanding command, or that comes from the wrong subsystem. A late answer to an old attempt cannot move the robot.
2. **One command at a time.** The Supervisor never has more than one `CMD_START` outstanding.
3. **Repeats are safe.** A subsystem that gets a `CMD_START` while already running that step should restart it cleanly. Retries and RESOLVED both re-send a command.
4. **Safe before replying.** Return to the safe state (wheels stopped, plate released, drill retracted) before sending `DONE` or `FAULT`.
5. **Every command has a timeout.** If no answer arrives, the Supervisor sends `CMD_ABORT` and stops with `SUBSYSTEM_UNRESPONSIVE`. The values are placeholders in `Config.step_timeout_s`.
6. **Retries.** A `FAULT` is retried in place up to N = 2 times, so a step runs at most 3 times. The Supervisor counts. The subsystem does not. This applies to locomotion faults too (E8 "relocate").
7. **Camera watchdog.** The camera sends `HEARTBEAT` about every 0.25 s. If it stops, or `ok` is false, for more than 1 s during a run, the Supervisor aborts the step and stops with `CAMERA_FEED_LOST`.

## Camera questions

The camera and its vision code run on the Pi, but Plate, Screw and Fastening run on the ESP32 and need its answers in the middle of a step. So they ask over the same serial link:

```
ESP32 to Pi:  {"v":1,"type":"QUERY","src":"PLATE","dst":"CAMERA","id":4,"row":1,"spot":3,"params":{"question":"PLATE_ARRIVED"}}
Pi to ESP32:  {"v":1,"type":"ANSWER","src":"CAMERA","dst":"PLATE","ref":4,"params":{"ok":true,"question":"PLATE_ARRIVED"}}
```

- The Pi router (`roofbot/router.py`) hands each `QUERY` to the camera service and sends the `ANSWER` straight back. The Supervisor state machine never sees these.
- A `QUERY` `id` belongs to the asking subsystem. It is separate from the Supervisor's command ids.
- **No answer within 1.5 s counts as "no".** The check fails and the subsystem goes round its retry loop. A camera that is really gone is caught separately by the Supervisor (E9).
- One question at a time, because only one subsystem is active at a time.

| Question | Asked by | Used for |
|---|---|---|
| `PLATE_ARRIVED` | Plate | Did the plate arrive in fastening position? |
| `PLACEMENT_OK` | Plate | Combined with the tripwire, approves the placement |
| `PLATE_SCREW_OK` | Screw | Plate and screw together, both in the right spot |
| `PHOTO_OK` | Fastening | Take the photo of the screw and say if it is accepted |

## What the ESP32 firmware must do

- Send `{"v":1,"type":"READY",...}` after every boot. Opening the USB port usually resets the board.
- Treat Supervisor `HEARTBEAT` as a watchdog. **If none arrives for about 2 s, stop the wheels and retract the drill**, then wait. Resume only on a new `CMD_START`.
- Keep one 512 byte line buffer, drop an over-long line up to its newline, and carry on.
- Never act on a malformed line.
- Reply to every `CMD_START` with exactly one `DONE`, `FAULT` or `NEED_REFILL`, carrying the command's `id` as `ref`.

## Differences from the system guide

These were added because the guide has no answer to them yet. Update the guide if you agree.

- `HEARTBEAT`, `READY`, `RESET`, and the `SUBSYSTEM_UNRESPONSIVE` fault.
- `LIGHT`, the stack light (section 3.8 of the guide), and the ESP32 showing flashing amber if the Supervisor goes quiet.
- `QUERY` and `ANSWER`, because the camera is on the Pi and the subsystems that use it are on the ESP32. The guide draws these as subsystem-to-camera arrows but does not say how they cross the link. The simulator does not model them: its detailed subsystems ask the camera internally.
- Locomotion faults are retried by the Supervisor (E8 says relocate up to N). The Supervisor state chart does not draw a retry loop on DRIVE_TO_SPOT or TURN_TO_NEXT_ROW.
- `START` is refused when the camera feed is not usable.
- Skip is also refused for `SUBSYSTEM_UNRESPONSIVE`, because the robot's state is not known.
