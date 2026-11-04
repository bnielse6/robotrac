// The real hardware. EVERY FUNCTION HERE IS A TODO.
//
// Each one currently does nothing and returns the answer that makes the robot fail loudly and
// safely: sensors say "no" and the drill never reports retracted. So a robot flashed with this file
// unmodified will not move, and the Supervisor will stop with a fault. That is on purpose.
//
// To fill it in:
//   1. Set the pins in include/config.h.
//   2. Replace each TODO below with the real read or write. Keep every function non-blocking.
//   3. Test one subsystem at a time, with the other three still working through the Supervisor's
//      simulator (see diagrams/firmware_guide.md, "Bringing up real hardware").
#include "config.h"

#if !USE_SIM_HAL

#include <Arduino.h>

#include "hal.h"

namespace {
void inputPin(int pin) {
  if (pin >= 0) pinMode(pin, INPUT);
}
void outputPin(int pin) {
  if (pin >= 0) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);  // everything starts off
  }
}
}  // namespace

namespace hal {

void begin() {
  inputPin(PIN_BEAM_SENSOR);
  inputPin(PIN_FRONT_SENSOR);
  inputPin(PIN_ENCODER_A);
  inputPin(PIN_ENCODER_B);
  inputPin(PIN_PLATE_SUPPLY_SENSOR);
  inputPin(PIN_TRIPWIRE);
  inputPin(PIN_SCREW_SUPPLY_SENSOR);
  inputPin(PIN_DRILL_RETRACTED_SWITCH);
  outputPin(PIN_MOTOR_LEFT_PWM);
  outputPin(PIN_MOTOR_RIGHT_PWM);
  outputPin(PIN_PLATE_FEED);
  outputPin(PIN_PLATE_PUSH);
  outputPin(PIN_PLATE_RELEASE);
  outputPin(PIN_SCREW_LOAD);
  outputPin(PIN_DRILL_MOTOR);
  outputPin(PIN_LIGHT_RED);
  outputPin(PIN_LIGHT_AMBER);
  outputPin(PIN_LIGHT_GREEN);
  // TODO: attach encoder interrupts (or use the ESP32 PCNT pulse counter, which counts in hardware).
  // TODO: configure PWM channels (ledc) for the motors and the drill.
  // TODO: configure the ADC for the torque sensor.
}

void tick(uint32_t now) {
  (void)now;
  // TODO: anything that has to be updated every loop, such as converting encoder counts to mm.
}

void setSimFault(const char* name) { (void)name; }  // simulation only

// ---- stack light. Drives the lamps (or the relays that switch them). HIGH = lamp on.
void setStackLight(bool red, bool amber, bool green) {
  if (PIN_LIGHT_RED >= 0) digitalWrite(PIN_LIGHT_RED, red ? HIGH : LOW);
  if (PIN_LIGHT_AMBER >= 0) digitalWrite(PIN_LIGHT_AMBER, amber ? HIGH : LOW);
  if (PIN_LIGHT_GREEN >= 0) digitalWrite(PIN_LIGHT_GREEN, green ? HIGH : LOW);
}

// ---- locomotion
bool onBeam() { return false; }            // TODO: read the beam sensors
bool frontSensorOnBeam() { return false; } // TODO: read the front sensor
float encoderMm() { return 0; }            // TODO: encoder counts to millimetres
void resetEncoder() {}                     // TODO
float headingDeg() { return 0; }           // TODO: from the encoders (or an IMU). Right is positive.
void resetHeading() {}                     // TODO
void driveForward() {}                     // TODO: both motors forward. Control speed and straightness.
void relocate() {}                         // TODO: whatever finds the beam again
void turn(bool right) { (void)right; }     // TODO: motors in opposite directions
void stopWheels() {}                       // TODO: motors off (and brake if you have one)

// ---- plate
bool platesAvailable() { return false; }       // TODO: read the plate supply sensor
void feedPlate() {}                            // TODO
void pushPlate() {}                            // TODO
void stopFeed() {}                             // TODO
void releasePlate() {}                         // TODO
void clearPlate() {}                           // TODO
bool tripwirePlateDetected() { return false; } // TODO: read the tripwire

// ---- screw
bool screwsAvailable() { return false; }  // TODO: read the screw supply sensor
void loadScrew() {}                       // TODO
void clearScrew() {}                      // TODO

// ---- fastening
void drillStart() {}                       // TODO: drill motor on
float torqueNm() { return 0; }             // TODO: read the torque sensor and convert to N*m
void drillRetract() {}                     // TODO: motor off and retract
bool drillRetracted() { return false; }    // TODO: read the retract switch

}  // namespace hal

#endif  // !USE_SIM_HAL
