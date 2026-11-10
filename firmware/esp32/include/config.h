// All the numbers you are likely to change live here.
//
// Time limits and tolerances are PLACEHOLDERS, except TORQUE_LIMIT_MS (10 s, from the system guide).
// They have to be measured on the real robot.
#pragma once

#include <stdint.h>

// 1 = simulated hardware (src/hal_sim.cpp), 0 = real hardware (src/hal_esp32.cpp). platformio.ini sets it.
#ifndef USE_SIM_HAL
#define USE_SIM_HAL 1
#endif

// ---- link to the Pi (see docs/message_schema.md)
#define PROTOCOL_VERSION 1
#define SERIAL_BAUD 115200
#define MAX_LINE_BYTES 512                 // longest line, including the newline

// ---- safety
#define HEARTBEAT_TIMEOUT_MS 2000          // no Supervisor heartbeat for this long: stop everything
#define CAMERA_ANSWER_TIMEOUT_MS 1500      // no answer from the camera counts as "no"

// ---- stack light
#define LIGHT_FLASH_HALF_PERIOD_MS 500     // a flashing lamp is on for this long, then off for this long

// ---- how often each subsystem looks at its sensors
#define CHECK_PERIOD_MS 20

// ---- locomotion, drive straight (S1)
#define DRIVE_RELOCATE_LIMIT_MS 6000       // how long to hunt for the crest before OFF_CREST
#define DRIVE_SPOT_LIMIT_MS 20000          // how long to reach the spot before CANNOT_REACH_SPOT
#define SPOT_TOLERANCE_MM 5.0f             // arrived once the encoder is within this of the target
// Past the spot by more than this counts as OVERSHOT_SPOT. It must be larger than the distance the
// robot travels between two encoder samples plus its stopping distance, or a normal arrival would
// be reported as an overshoot: one pass round the drive loop is about 4 checks (80 ms), which is
// 16 mm at the simulator's 200 mm/s. PLACEHOLDER, to be set from the real speed and stopping distance.
#define SPOT_OVERSHOOT_MM 30.0f

// ---- locomotion, cross-track control. This runs inside Locomotion (not over the serial link): the
// crest sensor array is wired to this board, and the loop is far too fast for the Pi. All PLACEHOLDERS.
// The same gains are in the Python localization model (roofbot/localization.py); a test keeps them equal.
#define CROSS_TRACK_KP 0.08f               // steering command per mm of lateral error
#define CROSS_TRACK_KD 0.04f               // steering command per mm/s of change in the error
#define CROSS_TRACK_FILTER 0.3f            // low-pass on the sensor reading: 0 ignores it, 1 uses it raw
#define STEER_MAX 1.0f                     // limit of the steering command: -1 full left, +1 full right
#define STEER_PERIOD_MS 10                 // how often the correction is recomputed while driving
#define CROSS_TRACK_CAPTURE_MM 40.0f       // further off the crest than this, onCrest() is false
#define LATERAL_TOLERANCE_MM 0.5f          // the screw line should be within this of the crest centre. Reported, not enforced

// ---- locomotion, fine positioning at the spot (stop and nudge). After stopping, Locomotion averages
// ALIGN_SAMPLES readings of the crest array; if the average is further than ALIGN_ACCEPT_MM from the
// crest centre it nudges sideways by that error and reads again, up to ALIGN_MAX_ATTEMPTS nudges,
// then reports NOT_ALIGNED. All PLACEHOLDERS, kept equal to roofbot/localization.py by a test.
#define ALIGN_ACCEPT_MM 0.2f
#define ALIGN_MAX_ATTEMPTS 3
#define ALIGN_SAMPLES 8
#define NUDGE_LIMIT_MS 6000                // time allowed for one nudge before NOT_ALIGNED

// ---- locomotion, turn (S2)
#define TURN_TURN_LIMIT_MS 8000            // time allowed for each 90 degree turn
#define TURN_FORWARD_LIMIT_MS 15000        // time allowed to find the next crest
#define TURN_ANGLE_TOLERANCE_DEG 3.0f
#define TURN_MIN_FORWARD_MM 50.0f          // used only when the route map gives no row gap
// When the TURN command carries the sideways gap (distance_mm), the encoder must agree with it to
// within this, or the crest count was wrong and the turn fails. Must exceed the distance travelled
// between two encoder samples. PLACEHOLDER.
#define TURN_GAP_TOLERANCE_MM 25.0f

// ---- plate (S3)
#define PLATE_ARRIVE_LIMIT_MS 5000         // how long to keep pushing before PLATE_NOT_ARRIVED
#define PLATE_FEED_SETTLE_MS 800           // wait after feeding before asking the camera
#define PLATE_PUSH_SETTLE_MS 600
#define PLATE_RELEASE_SETTLE_MS 500

// ---- screw (S4)
#define SCREW_LOAD_SETTLE_MS 800

// ---- fastening (S5)
#define TORQUE_LIMIT_MS 10000              // from the guide
#define TORQUE_TARGET_NM 4.0f
#define RETRACT_SETTLE_MS 300

// ---- real hardware pins. -1 means "not wired yet". Fill these in for your board.
// Used only by src/hal_esp32.cpp.
#define PIN_CREST_SENSOR -1
#define PIN_FRONT_SENSOR -1
#define PIN_ENCODER_A -1
#define PIN_ENCODER_B -1
#define PIN_MOTOR_LEFT_PWM -1
#define PIN_MOTOR_RIGHT_PWM -1
#define PIN_PLATE_SUPPLY_SENSOR -1
#define PIN_TRIPWIRE -1
#define PIN_PLATE_FEED -1
#define PIN_PLATE_PUSH -1
#define PIN_PLATE_RELEASE -1
#define PIN_SCREW_SUPPLY_SENSOR -1
#define PIN_SCREW_LOAD -1
#define PIN_DRILL_MOTOR -1
#define PIN_DRILL_RETRACTED_SWITCH -1
#define PIN_TORQUE_ADC -1
#define PIN_LIGHT_RED -1
#define PIN_LIGHT_AMBER -1
#define PIN_LIGHT_GREEN -1
