#include "camera_client.h"

#include "subsystem.h"  // reached()

CameraClient camera;

void CameraClient::ask(const char* node, const char* question, const Message& cmd, uint32_t now) {
  queryId_ = nextId_++;
  sentAt_ = now;
  waiting_ = true;
  answered_ = false;
  protocol::sendQuery(node, queryId_, question, cmd);
}

void CameraClient::onAnswer(const Message& answer) {
  if (waiting_ && answer.ref == queryId_) {
    waiting_ = false;
    answered_ = true;
    yes_ = answer.ok;
  }
}

void CameraClient::cancel() {
  waiting_ = false;
  answered_ = false;
}

CameraClient::Result CameraClient::poll(uint32_t now) {
  if (answered_) {
    answered_ = false;
    return yes_ ? Result::Yes : Result::No;
  }
  if (waiting_ && reached(now, sentAt_ + CAMERA_ANSWER_TIMEOUT_MS)) {
    waiting_ = false;
    return Result::No;
  }
  return Result::Waiting;
}
