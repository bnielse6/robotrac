// How a subsystem asks the camera a question.
//
// The camera runs on the Pi. A subsystem sends a QUERY over the serial link and the Pi sends
// back an ANSWER. Only one subsystem is active at a time, so one client is shared.
//
//   camera.ask(name_, "PLATE_ARRIVED", cmd_, now);
//   ... later, each tick ...
//   switch (camera.poll(now)) { case Waiting: ...; case Yes: ...; case No: ...; }
//
// If no answer comes within CAMERA_ANSWER_TIMEOUT_MS, poll() reports No. That is the safe reading:
// the check fails and the subsystem goes round its retry loop. A dead camera is caught separately by
// the Supervisor, which stops the whole robot (E9).
#pragma once

#include "protocol.h"

class CameraClient {
 public:
  enum class Result : uint8_t { Waiting, Yes, No };

  // question is one of PLATE_ARRIVED, PLACEMENT_OK, PLATE_SCREW_OK, PHOTO_OK.
  void ask(const char* node, const char* question, const Message& cmd, uint32_t now);

  // Give it every ANSWER that arrives. Answers to old queries are ignored.
  void onAnswer(const Message& answer);

  // Forget any question in flight (used when a subsystem is aborted).
  void cancel();

  // Waiting until an answer or the timeout. After that, Yes or No once, then Waiting again.
  Result poll(uint32_t now);

 private:
  int32_t nextId_ = 1;
  int32_t queryId_ = -1;
  uint32_t sentAt_ = 0;
  bool waiting_ = false;
  bool answered_ = false;
  bool yes_ = false;
};

extern CameraClient camera;
