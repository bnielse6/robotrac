// Base class for Locomotion, Plate, Screw and Fastening.
//
// The rules every subsystem follows (docs/message_schema.md, "Rules both sides follow"):
//   - exactly one reply per command: DONE, FAULT or NEED_REFILL, carrying the command's id as `ref`
//   - back in a safe state BEFORE the reply is sent
//   - abort stops safely and sends no reply
//   - a new command while busy restarts cleanly
//
// A subsystem never blocks. tick() is called from loop() many times a second and moves one
// step through its flowchart each time it is due.
#pragma once

#include <string.h>

#include "protocol.h"

// True once `now` has reached `deadline`. Safe when millis() wraps around.
inline bool reached(uint32_t now, uint32_t deadline) { return static_cast<int32_t>(now - deadline) >= 0; }

class Subsystem {
 public:
  explicit Subsystem(const char* name) : name_(name) {}
  virtual ~Subsystem() {}

  const char* name() const { return name_; }
  bool busy() const { return busy_; }

  // Does this subsystem handle the step named in a CMD_START?
  virtual bool handles(const char* step) const = 0;

  // Begin a command. If one is already running it is stopped safely first.
  void start(const Message& cmd, uint32_t now);

  // Stop safely and do not reply. Used for CMD_ABORT and when the heartbeat is lost.
  void abort();

  // Called from loop().
  virtual void tick(uint32_t now) = 0;

 protected:
  // Put every actuator in its safe state: wheels stopped, plate released, drill retracted.
  // Must be safe to call at any time, any number of times.
  virtual void makeSafe() = 0;

  // Set up for cmd_ and take the first step of the flowchart.
  virtual void onStart(uint32_t now) = 0;

  // The three possible answers. Each one makes the subsystem safe, then sends one reply.
  void finishDone();
  void finishFault(const char* code);
  void finishRefill(const char* item);

  const char* name_;
  Message cmd_;
  bool busy_ = false;
};
