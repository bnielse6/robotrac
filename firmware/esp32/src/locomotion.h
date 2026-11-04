// Locomotion: S1 (drive straight to the next spot) and S2 (turn onto the next row).
// The state names match the node names in docs/diagrams/subsystems/S1_*.mmd and S2_*.mmd.
#pragma once

#include "subsystem.h"

class Locomotion : public Subsystem {
 public:
  Locomotion() : Subsystem("LOCOMOTION") {}
  bool handles(const char* step) const override { return !strcmp(step, "DRIVE") || !strcmp(step, "TURN"); }
  void tick(uint32_t now) override;

 protected:
  void makeSafe() override;
  void onStart(uint32_t now) override;

 private:
  enum class S : uint8_t {
    Idle,
    // S1: drive straight
    Beam,       // on the beam?
    LimitBeam,  // time limit used up?
    Relocate,   // relocate to the beam
    AtSpot,     // at the right spot?
    LimitSpot,  // time limit used up?
    Move,       // keep moving to the spot
    // S2: turn
    T90a,       // turned 90?
    Turn1,      // turn
    Front,      // front sensor on the next beam?
    LimitTurn,  // distance or time limit used up?
    Enc,        // encoder position approved?
    T90b,       // turned 90 again?
    Turn2,      // turn
  };

  bool turnedNinety() const;

  S s_ = S::Idle;
  uint32_t nextCheck_ = 0;

  // drive
  float targetMm_ = 0;
  bool relocating_ = false;
  uint32_t relocateDeadline_ = 0;
  uint32_t spotDeadline_ = 0;

  // turn
  bool right_ = true;
  uint32_t turnDeadline_ = 0;
  uint32_t forwardDeadline_ = 0;
};
