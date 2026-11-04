// Roofing robot, ESP32 side.
//
// Reads one JSON line at a time from the USB serial port, hands CMD_START and CMD_ABORT to the right
// subsystem, passes camera ANSWERs to the camera client, and watches the Supervisor heartbeat.
//
// IMPORTANT: Serial carries only protocol lines. Never Serial.print() debug text, the Pi would read
// it as a bad message. For debugging, blink an LED or use a second UART.
#include <Arduino.h>

#include "camera_client.h"
#include "config.h"
#include "fastening.h"
#include "hal.h"
#include "locomotion.h"
#include "plate.h"
#include "protocol.h"
#include "screw.h"

namespace {

Locomotion locomotion;
Plate plate;
Screw screw;
Fastening fastening;
Subsystem* const subsystems[] = {&locomotion, &plate, &screw, &fastening};

LineReader reader;

uint32_t lastHeartbeat = 0;
bool heartbeatSeen = false;
bool failsafe = false;

// Stack light. The Supervisor sends the pattern; this board does the flashing.
struct LightPattern {
  bool red = false, amber = false, green = false;
  bool flash = false;
};
LightPattern light;  // starts dark until the Supervisor says otherwise

void updateStackLight(uint32_t now) {
  // If the Supervisor has gone quiet the robot has stopped itself, so show "needs the operator".
  LightPattern p = light;
  if (failsafe) p = LightPattern{false, true, false, true};
  bool lit = !p.flash || ((now / LIGHT_FLASH_HALF_PERIOD_MS) % 2 == 0);
  hal::setStackLight(p.red && lit, p.amber && lit, p.green && lit);
}

Subsystem* findSubsystem(const char* name) {
  for (Subsystem* s : subsystems) {
    if (!strcmp(s->name(), name)) return s;
  }
  return nullptr;
}

bool supervisorAlive(uint32_t now) {
  return heartbeatSeen && !reached(now, lastHeartbeat + HEARTBEAT_TIMEOUT_MS);
}

void handle(const Message& m, uint32_t now) {
  switch (m.type) {
    case MsgType::Heartbeat:
      lastHeartbeat = now;
      heartbeatSeen = true;
      break;

    case MsgType::Light:
      light.red = !strcmp(m.lightColor, "RED");
      light.amber = !strcmp(m.lightColor, "AMBER");
      light.green = !strcmp(m.lightColor, "GREEN");
      light.flash = !strcmp(m.lightMode, "FLASH");
      break;

    case MsgType::Answer:
      camera.onAnswer(m);
      break;

    case MsgType::CmdAbort: {
      Subsystem* s = findSubsystem(m.dst);
      if (s) s->abort();
      break;
    }

    case MsgType::CmdStart: {
      Subsystem* s = findSubsystem(m.dst);
      // Ignore commands for another subsystem, for a step it does not do, or when the Supervisor
      // is not sending heartbeats. The Supervisor will time out and stop, which is the safe result.
      if (!s || !s->handles(m.step) || !supervisorAlive(now)) break;
      hal::setSimFault(m.sim);  // ignored by real hardware
      s->start(m, now);
      break;
    }

    default:
      break;
  }
}

}  // namespace

void setup() {
  Serial.setRxBufferSize(1024);  // room for two full lines if the loop is ever slow
  Serial.begin(SERIAL_BAUD);
  hal::begin();
  protocol::sendReady();  // tells the Pi this board has just (re)started
}

void loop() {
  uint32_t now = millis();

  hal::tick(now);

  while (reader.poll(Serial)) {
    Message m;
    if (protocol::parse(reader.line(), m)) handle(m, now);
    // A line that does not parse is dropped, nothing else happens.
  }

  // Heartbeat watchdog: the Supervisor sends one about every 0.5 s.
  if (heartbeatSeen && !supervisorAlive(now)) {
    if (!failsafe) {
      failsafe = true;
      for (Subsystem* s : subsystems) s->abort();  // wheels stopped, plate released, drill retracted, no reply
    }
  } else {
    failsafe = false;
  }

  if (!failsafe) {
    for (Subsystem* s : subsystems) s->tick(now);
  }

  updateStackLight(now);
}
