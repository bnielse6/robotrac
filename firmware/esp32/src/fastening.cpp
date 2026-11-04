#include "fastening.h"

#include "camera_client.h"
#include "hal.h"

void Fastening::makeSafe() {
  hal::drillRetract();
  camera.cancel();
  s_ = S::Idle;
}

void Fastening::onStart(uint32_t now) {
  nextCheck_ = now;
  hal::drillStart();  // "drill the screw in"
  drillStartedAt_ = now;
  s_ = S::Torque;
}

void Fastening::beginRetract(uint32_t now, Result result) {
  (void)now;
  result_ = result;
  hal::drillRetract();
  s_ = S::Retract;
}

void Fastening::tick(uint32_t now) {
  if (!busy_ || s_ == S::Idle) return;
  if (!reached(now, nextCheck_)) return;
  nextCheck_ = now + CHECK_PERIOD_MS;

  switch (s_) {
    case S::Torque:
      s_ = (hal::torqueNm() >= TORQUE_TARGET_NM) ? S::Photo : S::LimitTorque;
      break;

    case S::LimitTorque:
      if (reached(now, drillStartedAt_ + TORQUE_LIMIT_MS)) {
        beginRetract(now, Result::TorqueTimeout);
      } else {
        s_ = S::Torque;  // "keep screwing"
      }
      break;

    case S::Photo:
      camera.ask(name_, "PHOTO_OK", cmd_, now);  // the camera takes the photo and judges it
      s_ = S::PhotoWait;
      break;

    case S::PhotoWait:
      switch (camera.poll(now)) {
        case CameraClient::Result::Waiting: break;
        case CameraClient::Result::Yes: beginRetract(now, Result::Done); break;
        case CameraClient::Result::No: beginRetract(now, Result::PhotoRejected); break;
      }
      break;

    case S::Retract:
      hal::drillRetract();
      if (!hal::drillRetracted()) break;  // not safe yet. Keep waiting, send nothing.
      if (result_ == Result::Done) finishDone();
      else if (result_ == Result::TorqueTimeout) finishFault("TORQUE_TIMEOUT");
      else finishFault("PHOTO_REJECTED");
      break;

    default:
      break;
  }
}
