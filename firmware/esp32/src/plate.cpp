#include "plate.h"

#include "camera_client.h"
#include "hal.h"

void Plate::makeSafe() {
  hal::stopFeed();
  hal::releasePlate();
  camera.cancel();
  s_ = S::Idle;
}

void Plate::onStart(uint32_t now) {
  nextCheck_ = now;
  s_ = S::Supply;
}

void Plate::settle(uint32_t now, uint32_t ms, S next) {
  settleUntil_ = now + ms;
  next_ = next;
  s_ = S::Settle;
}

void Plate::tick(uint32_t now) {
  if (!busy_ || s_ == S::Idle) return;
  if (!reached(now, nextCheck_)) return;
  nextCheck_ = now + CHECK_PERIOD_MS;

  switch (s_) {
    case S::Supply:
      if (!hal::platesAvailable()) {
        finishRefill("PLATES");
        return;
      }
      hal::feedPlate();  // "feed the plate toward fastening position"
      arriveDeadline_ = now + PLATE_ARRIVE_LIMIT_MS;
      settle(now, PLATE_FEED_SETTLE_MS, S::Arrived);
      break;

    case S::Settle:
      if (reached(now, settleUntil_)) s_ = next_;
      break;

    case S::Arrived:
      camera.ask(name_, "PLATE_ARRIVED", cmd_, now);
      s_ = S::ArrivedWait;
      break;

    case S::ArrivedWait:
      switch (camera.poll(now)) {
        case CameraClient::Result::Waiting: break;
        case CameraClient::Result::Yes: s_ = S::Release; break;
        case CameraClient::Result::No: s_ = S::LimitPlate; break;
      }
      break;

    case S::LimitPlate:
      if (reached(now, arriveDeadline_)) {
        hal::stopFeed();
        hal::clearPlate();
        finishFault("PLATE_NOT_ARRIVED");
      } else {
        hal::pushPlate();  // "push the plate again"
        settle(now, PLATE_PUSH_SETTLE_MS, S::Arrived);
      }
      break;

    case S::Release:
      hal::releasePlate();
      settle(now, PLATE_RELEASE_SETTLE_MS, S::Approve);
      break;

    case S::Approve:
      camera.ask(name_, "PLACEMENT_OK", cmd_, now);
      s_ = S::ApproveWait;
      break;

    case S::ApproveWait: {
      CameraClient::Result r = camera.poll(now);
      if (r == CameraClient::Result::Waiting) break;
      if (r == CameraClient::Result::Yes && hal::tripwirePlateDetected()) {
        finishDone();
      } else {
        hal::clearPlate();
        finishFault("PLACEMENT_REJECTED");
      }
      break;
    }

    default:
      break;
  }
}
