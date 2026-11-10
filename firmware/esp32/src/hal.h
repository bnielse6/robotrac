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

// A fault to simulate in the next command, e.g. "OFF_CREST". Ignored by the real hardware.
// Names: NOT_ALIGNED (nudges do nothing), DRIFT (the robot slowly wanders sideways, so the steering has to work), OFF_CREST, CANNOT_REACH_SPOT (stalls after 50 mm), OVERSHOT_SPOT (coasts 60 mm past the
//        target when the wheels stop), TURN_FAILED, NO_PLATES, NO_SCREWS,
//        NO_TRIPWIRE, TORQUE_LOW, STUCK_DRILL. Empty string for none.
// Faults that depend on the camera (plate not arrived, screw not in position, photo rejected)
// are chosen on the Pi, by what CameraService answers.
void setSimFault(const char* name);

// ---- stack light (output only). Flashing is done by main.cpp, so this just switches the lamps.
void setStackLight(bool red, bool amber, bool green);

// ---- locomotion
bool onCrest();               // crest sensors: is the robot on the crest, within CROSS_TRACK_CAPTURE_MM?
float crossTrackMm();        // crest sensors: lateral offset of the screw line from the crest centre.
                             //   Positive means the robot is to the right of the crest. Meaningful while onCrest()
bool frontSensorOnCrest();    // front sensor: is the front on the next crest?
int crestsCrossed();         // front sensor: crests counted since resetEncoder()
float encoderMm();           // distance travelled since resetEncoder(). Always >= 0, forwards or backwards
void resetEncoder();
float headingDeg();          // angle turned since resetHeading(). Right turns are positive.
void resetHeading();
void driveForward();         // keep driving forward
void driveBackward();        // keep driving straight back along the row (encoderMm still counts up)
void nudge(float lateralMm);  // start a sideways nudge that corrects `lateralMm` of error (positive = the robot is
                              //   right of the crest, so it moves left). A small S-move: turn a few degrees, drive a short way, turn
                              //   back, then take back the along-row distance it covered. Poll nudgeDone()
bool nudgeDone();            // true when the last nudge has finished (and true if none was started). stopWheels() cancels a nudge
void steer(float command);   // trim while driving: -1 full left, 0 straight, +1 full right. Stays until changed
void relocate();             // nudge sideways or back to find the crest again
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
