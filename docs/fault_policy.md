# Fault policy

Rule: the robot completes plate, screw and fastening at a spot before it moves. It never moves on by itself after a failure.

1. A failed step is retried in place up to N times (N = 2).
2. If retries are used up, something is empty (NEED_REFILL), or the camera feed is lost, the robot stops where it is and shows an alert: spot, subsystem, fault code, plus the live camera feed.
3. The operator fixes it on the robot and presses RESOLVED. The robot resumes the same step.
4. SKIP SPOT is only an operator-chosen last resort for a spot that cannot be fixed. It is logged. It is not offered for locomotion or camera faults.

A subsystem must return to a safe-to-move state (drill retracted, plate released) before it reports FAULT.
The Supervisor adds the spot number. Log entry = spot, subsystem, fault code, time, operator action.

The live camera sits in an enclosed space with its own light, so glare and changing sunlight do not affect it. It confirms that each plate and screw arrived (to avoid jams), verifies placement and the final photo, and streams to the operator screen. The Supervisor watches that the feed is alive.

| # | Fault code | Subsystem | Robot action |
|---|---|---|---|
| E1 | PLATE_NOT_ARRIVED (live camera sees no plate) | Plate | Feed plate again up to N, then stop and alert |
| E2 | PLACEMENT_REJECTED (live camera + tripwire) | Plate | Push plate again up to N, then stop and alert |
| E3 | NEED_REFILL (plates) | Plate | Stop immediately and alert (no retry) |
| E4 | SCREW_NOT_IN_POSITION (live camera sees the plate and screw together and they are missing or not in the right spot) | Screw | Reload and realign up to N, then stop and alert |
| E5 | NEED_REFILL (screws) | Screw | Stop immediately and alert (no retry) |
| E6 | TORQUE_TIMEOUT (10 seconds) | Fastening | Retract drill, retry up to N, then stop and alert |
| E7 | PHOTO_REJECTED | Fastening | Retake photo up to N, then stop and alert |
| E8 | OFF_CREST / CANNOT_REACH_SPOT / OVERSHOT_SPOT / NOT_ALIGNED / TURN_FAILED | Locomotion | Relocate up to N, then stop and alert (no skip). OVERSHOT_SPOT is never retried: stop and alert at once |
| E9 | CAMERA_FEED_LOST (no frames, lens blocked, or image too dark because the light failed) | Camera | Stop current step safely and alert (no retry, no skip) |
| E10 | ESTOP | Any | ESTOP, manual reset |
