#include "locomotion.h"

#include <math.h>

#include "hal.h"

void Locomotion::makeSafe() {
  hal::stopWheels();
  s_ = S::Idle;
}

void Locomotion::onStart(uint32_t now) {
  nextCheck_ = now;
  hal::stopWheels();
  if (!strcmp(cmd_.step, "DRIVE")) {
    targetMm_ = cmd_.distanceMm;
    hal::resetEncoder();
    relocating_ = false;
    spotDeadline_ = now + DRIVE_SPOT_LIMIT_MS;
    s_ = S::Beam;
  } else {  // TURN
    right_ = cmd_.direction[0] != 'L';
    hal::resetHeading();
    hal::resetEncoder();
    turnDeadline_ = now + TURN_TURN_LIMIT_MS;
    s_ = S::T90a;
  }
}

bool Locomotion::turnedNinety() const { return fabsf(hal::headingDeg()) >= 90.0f - TURN_ANGLE_TOLERANCE_DEG; }

void Locomotion::tick(uint32_t now) {
  if (!busy_ || s_ == S::Idle) return;
  if (!reached(now, nextCheck_)) return;
  nextCheck_ = now + CHECK_PERIOD_MS;

  switch (s_) {
    // ---------------- S1: drive straight
    case S::Beam:
      if (hal::onBeam()) {
        relocating_ = false;
        s_ = S::AtSpot;
      } else {
        if (!relocating_) {  // first look off the beam: start the clock
          relocating_ = true;
          relocateDeadline_ = now + DRIVE_RELOCATE_LIMIT_MS;
        }
        s_ = S::LimitBeam;
      }
      break;

    case S::LimitBeam:
      if (reached(now, relocateDeadline_)) {
        finishFault("OFF_BEAM");  // wheels stop in makeSafe()
      } else {
        hal::relocate();
        s_ = S::Relocate;
      }
      break;

    case S::Relocate:
      s_ = S::Beam;  // check the beam again
      break;

    case S::AtSpot:
      if (hal::encoderMm() >= targetMm_ - SPOT_TOLERANCE_MM) {
        finishDone();
      } else {
        s_ = S::LimitSpot;
      }
      break;

    case S::LimitSpot:
      if (reached(now, spotDeadline_)) {
        finishFault("CANNOT_REACH_SPOT");
      } else {
        hal::driveForward();
        s_ = S::Move;
      }
      break;

    case S::Move:
      s_ = S::Beam;  // keep checking while the wheels turn
      break;

    // ---------------- S2: turn to the next row
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
      s_ = hal::frontSensorOnBeam() ? S::Enc : S::LimitTurn;
      break;

    case S::LimitTurn:
      if (reached(now, forwardDeadline_)) {
        finishFault("TURN_FAILED");
      } else {
        s_ = S::Front;  // keep driving
      }
      break;

    case S::Enc:
      // TODO: compare with the real row gap from the route map, not just a minimum.
      if (hal::encoderMm() >= TURN_MIN_FORWARD_MM) {
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
