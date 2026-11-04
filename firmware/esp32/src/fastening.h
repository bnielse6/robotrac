// Fastening: S5. Names match the nodes in docs/diagrams/subsystems/S5_fastening.mmd.
//
// Safety rule: the drill must be retracted BEFORE the answer is sent. If the retract switch never
// reports "retracted", this subsystem never replies. The Supervisor then times out and stops with
// SUBSYSTEM_UNRESPONSIVE, which has no skip. That is deliberate.
#pragma once

#include "subsystem.h"

class Fastening : public Subsystem {
 public:
  Fastening() : Subsystem("FASTENING") {}
  bool handles(const char* step) const override { return !strcmp(step, "FASTEN"); }
  void tick(uint32_t now) override;

 protected:
  void makeSafe() override;
  void onStart(uint32_t now) override;

 private:
  enum class S : uint8_t {
    Idle,
    Torque,       // right torque? (torque sensor)
    LimitTorque,  // 10 second limit used up? if not, keep screwing
    Photo,        // ask the camera to take a photo and judge it
    PhotoWait,    // waiting for the answer
    Retract,      // retract the drill, then answer with `result_`
  };
  enum class Result : uint8_t { Done, TorqueTimeout, PhotoRejected };

  void beginRetract(uint32_t now, Result result);

  S s_ = S::Idle;
  Result result_ = Result::Done;
  uint32_t nextCheck_ = 0;
  uint32_t drillStartedAt_ = 0;
};
