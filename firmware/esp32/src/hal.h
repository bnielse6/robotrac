// Hardware abstraction layer: everything the subsystems need from the real world.
//
// The subsystems (locomotion.cpp, plate.cpp, screw.cpp, fastening.cpp) only call these functions.
// There are two implementations, chosen by the USE_SIM_HAL build flag:
//   hal_sim.cpp    pretend hardware, so the board can be tested with nothing wired up
//   hal_esp32.cpp  the real pins and drivers (every function is a TODO to fill in)
//
// Actuator functions are commands that stay in effect until changed (driveForward keeps driving
// until stopWheels). They must return at once. Sensor functions must return at once too.
#pragma once

#include <stdint.h>

namespace hal {

void begin();             // set up pins and drivers
void tick(uint32_t now);  // called every loop(). The simulator moves its fake robot here.

// A fault to simulate in the next command, e.g. "OFF_BEAM". Ignored by the real hardware.
// Names: OFF_BEAM, CANNOT_REACH_SPOT (stalls after 50 mm), TURN_FAILED, NO_PLATES, NO_SCREWS,
//        NO_TRIPWIRE, TORQUE_LOW, STUCK_DRILL. Empty string for none.
// Faults that depend on the camera (plate not arrived, screw not in position, photo rejected)
// are chosen on the Pi, by what CameraService answers.
void setSimFault(const char* name);

// ---- stack light (output only). Flashing is done by main.cpp, so this just switches the lamps.
void setStackLight(bool red, bool amber, bool green);

// ---- locomotion
bool onBeam();               // beam sensors: are the wheels on the beam?
bool frontSensorOnBeam();    // front sensor: is the front on the next beam?
float encoderMm();           // distance driven since resetEncoder()
void resetEncoder();
float headingDeg();          // angle turned since resetHeading(). Right turns are positive.
void resetHeading();
void driveForward();         // keep driving forward
void relocate();             // nudge sideways or back to find the beam again
void turn(bool right);       // keep turning on the spot
void stopWheels();

// ---- plate
bool platesAvailable();
void feedPlate();            // feed a plate toward fastening position
void pushPlate();            // push it again
void stopFeed();
void releasePlate();         // let go of the plate
void clearPlate();           // remove a bad plate so the next attempt starts clean
bool tripwirePlateDetected();

// ---- screw
bool screwsAvailable();
void loadScrew();            // load a screw into fastening position
void clearScrew();           // remove a missing or misaligned screw

// ---- fastening
void drillStart();           // drill the screw in
float torqueNm();            // current torque
void drillRetract();         // retract the drill
bool drillRetracted();       // retract switch

}  // namespace hal
