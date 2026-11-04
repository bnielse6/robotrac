// Plate: S3. Names match the nodes in docs/diagrams/subsystems/S3_plate.mmd.
#pragma once

#include "subsystem.h"

class Plate : public Subsystem {
 public:
  Plate() : Subsystem("PLATE") {}
  bool handles(const char* step) const override { return !strcmp(step, "PLATE"); }
  void tick(uint32_t now) override;

 protected:
  void makeSafe() override;
  void onStart(uint32_t now) override;

 private:
  enum class S : uint8_t {
    Idle,
    Supply,       // plates available?
    Settle,       // wait a moment for the feed, push or release to finish, then go to next_
    Arrived,      // ask the camera: did the plate arrive?
    ArrivedWait,  // waiting for the answer
    LimitPlate,   // time limit used up? if not, push the plate again
    Release,      // release the plate
    Approve,      // ask the camera: placement good?
    ApproveWait,  // waiting for the answer (and the tripwire)
  };

  void settle(uint32_t now, uint32_t ms, S next);

  S s_ = S::Idle;
  S next_ = S::Idle;
  uint32_t nextCheck_ = 0;
  uint32_t settleUntil_ = 0;
  uint32_t arriveDeadline_ = 0;
};
