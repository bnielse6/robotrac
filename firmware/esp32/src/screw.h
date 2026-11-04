// Screw: S4. Names match the nodes in diagrams/subsystems/S4_screw.mmd.
#pragma once

#include "subsystem.h"

class Screw : public Subsystem {
 public:
  Screw() : Subsystem("SCREW") {}
  bool handles(const char* step) const override { return !strcmp(step, "SCREW"); }
  void tick(uint32_t now) override;

 protected:
  void makeSafe() override;
  void onStart(uint32_t now) override;

 private:
  enum class S : uint8_t {
    Idle,
    Supply,    // screws available?
    Load,      // load the screw into fastening position
    Settle,    // wait for the loader to finish
    Ask,       // ask the camera: plate and screw together, both in the right spot?
    AskWait,   // waiting for the answer
  };

  S s_ = S::Idle;
  uint32_t nextCheck_ = 0;
  uint32_t settleUntil_ = 0;
};
