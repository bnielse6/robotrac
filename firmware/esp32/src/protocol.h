// The message format on the USB serial link: one JSON object per line.
// The contract is docs/message_schema.md. The Python side is supervisor/roofbot/messages.py.
#pragma once

#include <Arduino.h>
#include "config.h"

// Only the types this board needs to read. Everything else is Unknown and ignored.
enum class MsgType : uint8_t { Unknown, CmdStart, CmdAbort, Heartbeat, Answer, Light };

struct Message {
  MsgType type = MsgType::Unknown;
  char src[16] = "";
  char dst[16] = "";
  int32_t id = -1;       // -1 means "not present"
  int32_t ref = -1;
  int32_t row = -1;
  int32_t spot = -1;
  int32_t attempt = -1;
  char step[8] = "";     // DRIVE, TURN, PLATE, SCREW, FASTEN
  float distanceMm = 0;  // params.distance_mm  (DRIVE)
  char direction[8] = "";// params.direction    (TURN): RIGHT or LEFT
  char sim[24] = "";     // params.sim          (development only, picks a fault in the simulated hardware)
  bool ok = false;       // params.ok           (ANSWER)
  char lightColor[8] = "";  // params.color     (LIGHT): GREEN, AMBER, RED or OFF
  char lightMode[8] = "";   // params.mode      (LIGHT): STEADY or FLASH
};

namespace protocol {

// Fills `out` from one line of JSON. False if the line is not a valid message for this board.
bool parse(const char* line, Message& out);

// Messages the board sends. All of them end with a newline and fit in MAX_LINE_BYTES.
void sendReady();
void sendDone(const char* node, const Message& cmd);
void sendFault(const char* node, const Message& cmd, const char* code);
void sendNeedRefill(const char* node, const Message& cmd, const char* item);  // "PLATES" or "SCREWS"
void sendQuery(const char* node, int32_t queryId, const char* question, const Message& cmd);

}  // namespace protocol

// Collects bytes from the serial port into lines. A line that is too long is dropped,
// and so is everything up to its newline, then it carries on.
class LineReader {
 public:
  // Reads what is available. True when one complete line is ready in line().
  // Call again until it returns false.
  bool poll(Stream& port);
  const char* line() const { return out_; }
  uint32_t dropped() const { return dropped_; }

 private:
  char buf_[MAX_LINE_BYTES];
  char out_[MAX_LINE_BYTES];
  size_t len_ = 0;
  bool discarding_ = false;
  uint32_t dropped_ = 0;
};
