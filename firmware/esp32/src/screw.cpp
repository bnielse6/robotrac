#include "screw.h"

#include "camera_client.h"
#include "hal.h"

void Screw::makeSafe() {
  camera.cancel();
  s_ = S::Idle;
}

void Screw::onStart(uint32_t now) {
  nextCheck_ = now;
  s_ = S::Supply;
}

void Screw::tick(uint32_t now) {
  if (!busy_ || s_ == S::Idle) return;
  if (!reached(now, nextCheck_)) return;
  nextCheck_ = now + CHECK_PERIOD_MS;

  switch (s_) {
    case S::Supply:
      if (!hal::screwsAvailable()) {
        finishRefill("SCREWS");
        return;
      }
      s_ = S::Load;
      break;

    case S::Load:
      hal::loadScrew();
      settleUntil_ = now + SCREW_LOAD_SETTLE_MS;
      s_ = S::Settle;
      break;

    case S::Settle:
      if (reached(now, settleUntil_)) s_ = S::Ask;
      break;

    case S::Ask:
      camera.ask(name_, "PLATE_SCREW_OK", cmd_, now);
      s_ = S::AskWait;
      break;

    case S::AskWait:
      switch (camera.poll(now)) {
        case CameraClient::Result::Waiting: break;
        case CameraClient::Result::Yes: finishDone(); break;
        case CameraClient::Result::No:
          hal::clearScrew();
          finishFault("SCREW_NOT_IN_POSITION");
          break;
      }
      break;

    default:
      break;
  }
}
