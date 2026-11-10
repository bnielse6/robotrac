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
    Crest,       // on the crest?
    LimitCrest,  // time limit used up?
    Relocate,   // relocate to the crest
    AtSpot,     // at the right spot?
    Over,       // past the spot by more than the limit?
    Aligned,    // sideways error within the accept limit? (averages ALIGN_SAMPLES readings)
    LimitAlign, // tried too many times?
    Nudge,      // nudge sideways by the error
    NudgeWait,  // waiting for the nudge to finish
    LimitSpot,  // time limit used up?
    Move,       // keep moving to the spot
    // S2: turn
    RunOut,     // drive on to the turn point (run-out), if the route map has one
    T90a,       // turned 90?
    Turn1,      // turn
    Front,      // front sensor on the next crest?
    LimitTurn,  // distance or time limit used up?
    Enc,        // encoder position approved?
    T90b,       // turned 90 again?
    Turn2,      // turn
  };

  bool turnedNinety() const;
  void steer(uint32_t now);   // cross-track correction. Runs on every pass of loop() while driving

  S s_ = S::Idle;
  uint32_t nextCheck_ = 0;

  // drive
  float targetMm_ = 0;     // distance to travel, always >= 0
  bool reverse_ = false;   // the command asked for a negative distance: drive backwards
  bool driving_ = false;   // the wheels are driving along the row, so the steering is active
  uint32_t lastSteer_ = 0;
  // fine positioning at the spot
  float alignSum_ = 0;     // readings added up so far
  int alignCount_ = 0;     // how many
  int alignTries_ = 0;     // nudges so far
  float alignErr_ = 0;     // the averaged sideways error (mm, positive = right of the crest)
  uint32_t nudgeDeadline_ = 0;
  float lastErr_ = 0;      // the filtered lateral error at the last steering update, for the filter and the D term
  bool relocating_ = false;
  uint32_t relocateDeadline_ = 0;
  uint32_t spotDeadline_ = 0;

  // turn
  bool right_ = true;
  uint32_t turnDeadline_ = 0;
  uint32_t forwardDeadline_ = 0;
};
