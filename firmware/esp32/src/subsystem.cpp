#include "subsystem.h"

void Subsystem::start(const Message& cmd, uint32_t now) {
  if (busy_) makeSafe();
  cmd_ = cmd;
  busy_ = true;
  onStart(now);
}

void Subsystem::abort() {
  makeSafe();
  busy_ = false;
}

void Subsystem::finishDone() {
  if (!busy_) return;
  makeSafe();
  busy_ = false;
  protocol::sendDone(name_, cmd_);
}

void Subsystem::finishDoneWithError(float lateralMm, float alongMm) {
  if (!busy_) return;
  makeSafe();
  busy_ = false;
  protocol::sendDoneWithError(name_, cmd_, lateralMm, alongMm);
}

void Subsystem::finishFault(const char* code) {
  if (!busy_) return;
  makeSafe();
  busy_ = false;
  protocol::sendFault(name_, cmd_, code);
}

void Subsystem::finishRefill(const char* item) {
  if (!busy_) return;
  makeSafe();
  busy_ = false;
  protocol::sendNeedRefill(name_, cmd_, item);
}
