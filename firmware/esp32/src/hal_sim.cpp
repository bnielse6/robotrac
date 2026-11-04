// Pretend hardware. Lets the board talk the real protocol and run the real subsystem
// flowcharts with nothing wired up. Speeds are made up: 200 mm/s driving, 90 deg/s turning.
#include "config.h"

#if USE_SIM_HAL

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "hal.h"

namespace {

char simFault[24] = "";
bool fault(const char* name) { return strcmp(simFault, name) == 0; }

enum class Motion : uint8_t { Stopped, Forward, Relocate, TurnRight, TurnLeft };
Motion motion = Motion::Stopped;
float encoder = 0;
float heading = 0;
uint32_t lastTick = 0;

int platesLeft = 12;
bool plateFed = false;
bool plateReleased = false;

int screwsLeft = 12;

bool drilling = false;
float drillDepth = 0;  // 0 retracted, 1 fully in
float torque = 0;

}  // namespace

namespace hal {

void begin() { lastTick = 0; }

void setSimFault(const char* name) { snprintf(simFault, sizeof(simFault), "%s", name ? name : ""); }

void tick(uint32_t now) {
  if (lastTick == 0) lastTick = now;
  float dt = (now - lastTick) / 1000.0f;
  lastTick = now;

  switch (motion) {
    case Motion::Forward:
      encoder += 200.0f * dt;
      if (fault("CANNOT_REACH_SPOT") && encoder > 50.0f) encoder = 50.0f;  // wheels slip
      break;
    case Motion::TurnRight: heading += 90.0f * dt; break;
    case Motion::TurnLeft: heading -= 90.0f * dt; break;
    default: break;
  }

  if (drilling) {
    drillDepth = fminf(1.0f, drillDepth + dt);
    float maxTorque = fault("TORQUE_LOW") ? 1.0f : 4.5f;
    torque = fminf(maxTorque, torque + 2.5f * dt);
  } else if (drillDepth > 0 && !fault("STUCK_DRILL")) {
    drillDepth = fmaxf(0.0f, drillDepth - dt / 0.3f);
    if (drillDepth == 0) torque = 0;
  }
}

// ---- stack light (the simulated lamps do nothing)
void setStackLight(bool red, bool amber, bool green) { (void)red; (void)amber; (void)green; }

// ---- locomotion
bool onBeam() { return !fault("OFF_BEAM"); }
bool frontSensorOnBeam() { return !fault("TURN_FAILED") && encoder >= 80.0f; }
float encoderMm() { return encoder; }
void resetEncoder() { encoder = 0; }
float headingDeg() { return heading; }
void resetHeading() { heading = 0; }
void driveForward() { motion = Motion::Forward; }
void relocate() { motion = Motion::Relocate; }
void turn(bool right) { motion = right ? Motion::TurnRight : Motion::TurnLeft; }
void stopWheels() { motion = Motion::Stopped; }

// ---- plate
bool platesAvailable() { return !fault("NO_PLATES") && platesLeft > 0; }
void feedPlate() {  // called once per Plate command
  plateFed = true;
  plateReleased = false;
  platesLeft--;
}
void pushPlate() {}
void stopFeed() {}
void releasePlate() {
  if (plateFed) plateReleased = true;
}
void clearPlate() {
  plateFed = false;
  plateReleased = false;
}
bool tripwirePlateDetected() { return plateReleased && !fault("NO_TRIPWIRE"); }

// ---- screw
bool screwsAvailable() { return !fault("NO_SCREWS") && screwsLeft > 0; }
void loadScrew() { screwsLeft--; }
void clearScrew() {}

// ---- fastening
void drillStart() { drilling = true; }
float torqueNm() { return torque; }
void drillRetract() { drilling = false; }
bool drillRetracted() { return !drilling && drillDepth <= 0.01f; }

}  // namespace hal

#endif  // USE_SIM_HAL
