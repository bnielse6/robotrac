#include "locomotion.h"

#include <math.h>

#include "hal.h"

void Locomotion::makeSafe() {
  driving_ = false;
  hal::steer(0);
  hal::stopWheels();
  s_ = S::Idle;
}

void Locomotion::onStart(uint32_t now) {
  nextCheck_ = now;
  driving_ = false;
  hal::steer(0);
  hal::stopWheels();
  if (!strcmp(cmd_.step, "DRIVE")) {
    alignTries_ = 0;
    alignSum_ = 0;
    alignCount_ = 0;
    reverse_ = cmd_.distanceMm < 0;  // a negative distance means reverse
    targetMm_ = fabsf(cmd_.distanceMm);
    hal::resetEncoder();
    relocating_ = false;
    spotDeadline_ = now + DRIVE_SPOT_LIMIT_MS;
    s_ = S::Crest;
  } else {  // TURN
    right_ = cmd_.direction[0] != 'L';
    hal::resetHeading();
    hal::resetEncoder();
    turnDeadline_ = now + TURN_TURN_LIMIT_MS;
    if (cmd_.runOutMm > 0) {  // first drive on past the last spot, to the level where the turn happens
      forwardDeadline_ = now + DRIVE_SPOT_LIMIT_MS;
      hal::driveForward();
      s_ = S::RunOut;
    } else {
      s_ = S::T90a;
    }
  }
}

bool Locomotion::turnedNinety() const { return fabsf(hal::headingDeg()) >= 90.0f - TURN_ANGLE_TOLERANCE_DEG; }

// Keeps the screw line over the crest centre while driving. PD on the lateral error from the crest
// sensor array: steer back toward the crest. Runs every pass of loop(), not once per flowchart node,
// because the nodes are visited only every few tens of milliseconds.
void Locomotion::steer(uint32_t now) {
  if (!driving_) return;
  if (reverse_) {  // TODO: reversing flips the sign of the correction. Hold straight until that is worked out.
    hal::steer(0);
    return;
  }
  uint32_t dtMs = now - lastSteer_;
  if (dtMs < STEER_PERIOD_MS) return;
  // Low-pass the reading first: differentiating raw sensor noise would swamp the D term.
  float filt = lastErr_ + CROSS_TRACK_FILTER * (hal::crossTrackMm() - lastErr_);
  float command = -(CROSS_TRACK_KP * filt + CROSS_TRACK_KD * (filt - lastErr_) / (dtMs / 1000.0f));
  if (command > STEER_MAX) command = STEER_MAX;
  if (command < -STEER_MAX) command = -STEER_MAX;
  hal::steer(command);
  lastErr_ = filt;
  lastSteer_ = now;
}

void Locomotion::tick(uint32_t now) {
  if (!busy_ || s_ == S::Idle) return;
  steer(now);  // before the check period, so it runs every pass
  if (!reached(now, nextCheck_)) return;
  nextCheck_ = now + CHECK_PERIOD_MS;

  switch (s_) {
    // ---------------- S1: drive straight
    case S::Crest:
      if (hal::onCrest()) {
        relocating_ = false;
        s_ = S::AtSpot;
      } else {
        if (!relocating_) {  // first look off the crest: start the clock
          relocating_ = true;
          relocateDeadline_ = now + DRIVE_RELOCATE_LIMIT_MS;
        }
        s_ = S::LimitCrest;
      }
      break;

    case S::LimitCrest:
      if (reached(now, relocateDeadline_)) {
        finishFault("OFF_CREST");  // wheels stop in makeSafe()
      } else {
        driving_ = false;  // no steering while hunting for the crest
        hal::steer(0);
        hal::relocate();
        s_ = S::Relocate;
      }
      break;

    case S::Relocate:
      s_ = S::Crest;  // check the crest again
      break;

    case S::AtSpot:
      if (hal::encoderMm() >= targetMm_ - SPOT_TOLERANCE_MM) {
        driving_ = false;
        hal::steer(0);
        hal::stopWheels();  // stop at once, then read where it ended up
        s_ = S::Over;
      } else {
        s_ = S::LimitSpot;
      }
      break;

    case S::Over:
      if (hal::encoderMm() > targetMm_ + SPOT_OVERSHOOT_MM) {
        finishFault("OVERSHOT_SPOT");  // wheels are already stopped. A retry would repeat the whole
                                       // drive from past the spot, so the Supervisor does not retry.
      } else {
        alignSum_ = 0;
        alignCount_ = 0;
        s_ = S::Aligned;
      }
      break;

    // Fine positioning: the robot is standing still, so average several readings of the crest
    // array. Within the accept limit: done. Otherwise nudge sideways by the error and read again.
    case S::Aligned:
      alignSum_ += hal::crossTrackMm();
      if (++alignCount_ < ALIGN_SAMPLES) break;  // keep averaging
      alignErr_ = alignSum_ / alignCount_;
      alignSum_ = 0;
      alignCount_ = 0;
      if (fabsf(alignErr_) <= ALIGN_ACCEPT_MM) {
        // Report what the crest sensors and the encoder say about where it stopped.
        finishDoneWithError(alignErr_, hal::encoderMm() - targetMm_);
      } else {
        s_ = S::LimitAlign;
      }
      break;

    case S::LimitAlign:
      if (alignTries_ >= ALIGN_MAX_ATTEMPTS) {
        finishFault("NOT_ALIGNED");  // the nudges did not get it inside the limit
      } else {
        s_ = S::Nudge;
      }
      break;

    case S::Nudge:
      alignTries_++;
      nudgeDeadline_ = now + NUDGE_LIMIT_MS;
      hal::nudge(alignErr_);
      s_ = S::NudgeWait;
      break;

    case S::NudgeWait:
      if (hal::nudgeDone()) {
        s_ = S::Aligned;  // read again
      } else if (reached(now, nudgeDeadline_)) {
        finishFault("NOT_ALIGNED");  // the nudge never finished
      }
      break;

    case S::LimitSpot:
      if (reached(now, spotDeadline_)) {
        finishFault("CANNOT_REACH_SPOT");
      } else {
        if (reverse_) {
          hal::driveBackward();
        } else {
          hal::driveForward();
        }
        if (!driving_) {  // first time round: start the steering from the current error
          driving_ = true;
          lastSteer_ = now;
          lastErr_ = hal::crossTrackMm();
        }
        s_ = S::Move;
      }
      break;

    case S::Move:
      s_ = S::Crest;  // keep checking while the wheels turn
      break;

    // ---------------- S2: turn to the next row
    case S::RunOut:
      if (hal::encoderMm() >= cmd_.runOutMm - SPOT_TOLERANCE_MM) {
        hal::stopWheels();
        hal::resetHeading();
        hal::resetEncoder();
        turnDeadline_ = now + TURN_TURN_LIMIT_MS;
        s_ = S::T90a;
      } else if (reached(now, forwardDeadline_)) {
        finishFault("TURN_FAILED");  // could not drive on to the turn point in time
      }
      break;

    case S::T90a:
      if (turnedNinety()) {
        hal::stopWheels();
        hal::resetEncoder();
        forwardDeadline_ = now + TURN_FORWARD_LIMIT_MS;
        hal::driveForward();  // "drive forward"
        s_ = S::Front;
      } else {
        s_ = S::Turn1;
      }
      break;

    case S::Turn1:
      if (reached(now, turnDeadline_)) {
        finishFault("TURN_FAILED");
      } else {
        hal::turn(right_);
        s_ = S::T90a;
      }
      break;

    case S::Front:
      if (cmd_.crests > 0) {  // the route map says how many crests to cross
        s_ = hal::crestsCrossed() >= cmd_.crests ? S::Enc : S::LimitTurn;
      } else {
        s_ = hal::frontSensorOnCrest() ? S::Enc : S::LimitTurn;
      }
      break;

    case S::LimitTurn:
      if (reached(now, forwardDeadline_)) {
        finishFault("TURN_FAILED");
      } else {
        s_ = S::Front;  // keep driving
      }
      break;

    case S::Enc:
      // With the row gap from the route map, the encoder must agree with the crest count: too short
      // means keep driving, too far means the wrong crest was counted, so it runs out the time limit
      // and reports TURN_FAILED. Without a gap, only a minimum distance is checked.
      if (cmd_.distanceMm > 0 ? fabsf(hal::encoderMm() - cmd_.distanceMm) <= TURN_GAP_TOLERANCE_MM
                              : hal::encoderMm() >= TURN_MIN_FORWARD_MM) {
        hal::stopWheels();
        hal::resetHeading();
        turnDeadline_ = now + TURN_TURN_LIMIT_MS;
        s_ = S::T90b;
      } else {
        s_ = S::LimitTurn;
      }
      break;

    case S::T90b:
      if (turnedNinety()) {
        finishDone();
      } else {
        s_ = S::Turn2;
      }
      break;

    case S::Turn2:
      if (reached(now, turnDeadline_)) {
        finishFault("TURN_FAILED");
      } else {
        hal::turn(right_);
        s_ = S::T90b;
      }
      break;

    default:
      break;
  }
}
