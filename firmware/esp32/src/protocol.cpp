#include "protocol.h"

#include <ArduinoJson.h>
#include <string.h>

namespace {

void copyStr(char* dst, size_t size, const char* src) {
  snprintf(dst, size, "%s", src ? src : "");
}

// Serialise and write one line. A message that does not fit is dropped.
void emit(const JsonDocument& doc) {
  char buf[MAX_LINE_BYTES];
  size_t n = serializeJson(doc, buf, sizeof(buf) - 1);
  if (n == 0 || n >= sizeof(buf) - 1) return;
  buf[n++] = '\n';
  Serial.write(reinterpret_cast<const uint8_t*>(buf), n);
}

void sendReply(const char* type, const char* node, const Message& cmd, const char* code, const char* item) {
  JsonDocument doc;
  doc["v"] = PROTOCOL_VERSION;
  doc["type"] = type;
  doc["src"] = node;
  doc["dst"] = "SUP";
  doc["ref"] = cmd.id;  // the id of the CMD_START being answered
  if (cmd.row >= 0) doc["row"] = cmd.row;
  if (cmd.spot >= 0) doc["spot"] = cmd.spot;
  if (cmd.attempt >= 0) doc["attempt"] = cmd.attempt;
  if (cmd.step[0]) doc["step"] = cmd.step;
  if (code) doc["code"] = code;
  if (item) doc["params"]["item"] = item;
  doc["t"] = millis() / 1000.0;
  emit(doc);
}

}  // namespace

namespace protocol {

bool parse(const char* line, Message& m) {
  JsonDocument doc;
  if (deserializeJson(doc, line)) return false;
  if ((doc["v"] | 0) != PROTOCOL_VERSION) return false;

  const char* type = doc["type"] | "";
  if (!strcmp(type, "CMD_START")) m.type = MsgType::CmdStart;
  else if (!strcmp(type, "CMD_ABORT")) m.type = MsgType::CmdAbort;
  else if (!strcmp(type, "HEARTBEAT")) m.type = MsgType::Heartbeat;
  else if (!strcmp(type, "ANSWER")) m.type = MsgType::Answer;
  else if (!strcmp(type, "LIGHT")) m.type = MsgType::Light;
  else m.type = MsgType::Unknown;

  copyStr(m.src, sizeof(m.src), doc["src"] | "");
  copyStr(m.dst, sizeof(m.dst), doc["dst"] | "");
  m.id = doc["id"] | -1;
  m.ref = doc["ref"] | -1;
  m.row = doc["row"] | -1;
  m.spot = doc["spot"] | -1;
  m.attempt = doc["attempt"] | -1;
  copyStr(m.step, sizeof(m.step), doc["step"] | "");

  JsonObjectConst p = doc["params"].as<JsonObjectConst>();
  if (!p.isNull()) {
    m.distanceMm = p["distance_mm"] | 0.0f;
    copyStr(m.direction, sizeof(m.direction), p["direction"] | "");
    copyStr(m.sim, sizeof(m.sim), p["sim"] | "");
    m.ok = p["ok"] | false;
    copyStr(m.lightColor, sizeof(m.lightColor), p["color"] | "");
    copyStr(m.lightMode, sizeof(m.lightMode), p["mode"] | "");
  }

  // The fields each type must carry (same rules as messages.py).
  if (m.type == MsgType::CmdStart && (m.id < 0 || !m.step[0])) return false;
  if (m.type == MsgType::Answer && m.ref < 0) return false;
  if (m.type == MsgType::Light && (!m.lightColor[0] || !m.lightMode[0])) return false;
  return true;
}

void sendReady() {
  JsonDocument doc;
  doc["v"] = PROTOCOL_VERSION;
  doc["type"] = "READY";
  doc["src"] = "LOCOMOTION";  // the whole board, but the schema needs a subsystem name
  doc["dst"] = "SUP";
  doc["t"] = millis() / 1000.0;
  emit(doc);
}

void sendDone(const char* node, const Message& cmd) { sendReply("DONE", node, cmd, nullptr, nullptr); }

void sendFault(const char* node, const Message& cmd, const char* code) {
  sendReply("FAULT", node, cmd, code, nullptr);
}

void sendNeedRefill(const char* node, const Message& cmd, const char* item) {
  sendReply("NEED_REFILL", node, cmd, nullptr, item);
}

void sendQuery(const char* node, int32_t queryId, const char* question, const Message& cmd) {
  JsonDocument doc;
  doc["v"] = PROTOCOL_VERSION;
  doc["type"] = "QUERY";
  doc["src"] = node;
  doc["dst"] = "CAMERA";
  doc["id"] = queryId;
  if (cmd.row >= 0) doc["row"] = cmd.row;
  if (cmd.spot >= 0) doc["spot"] = cmd.spot;
  doc["params"]["question"] = question;
  doc["t"] = millis() / 1000.0;
  emit(doc);
}

}  // namespace protocol

bool LineReader::poll(Stream& port) {
  while (port.available() > 0) {
    int c = port.read();
    if (c < 0) break;
    if (c == '\n') {
      bool complete = !discarding_ && len_ > 0;
      if (complete) {
        memcpy(out_, buf_, len_);
        out_[len_] = '\0';
      }
      len_ = 0;
      discarding_ = false;
      if (complete) return true;
    } else if (discarding_ || c == '\r') {
      continue;
    } else if (len_ >= MAX_LINE_BYTES - 1) {
      len_ = 0;
      discarding_ = true;
      dropped_++;
    } else {
      buf_[len_++] = static_cast<char>(c);
    }
  }
  return false;
}
