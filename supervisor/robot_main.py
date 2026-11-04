"""Run the real Supervisor on the Pi, talking to the ESP32 over USB serial.

    python robot_main.py --port COM5            (Windows)
    python robot_main.py --port /dev/ttyUSB0    (Pi)

Type a command and press Enter: start, resolved, skip, estop, reset, status, quit.

NOT TESTED AGAINST HARDWARE. Needs `pip install pyserial`.
The camera answers yes to everything until the vision code is plugged in
(see CameraService in roofbot/camera_service.py).
"""
from __future__ import annotations

import argparse
import queue
import sys
import threading
import time

from roofbot.messages import Message, MsgType
from roofbot.route import Route, RowPlan
from roofbot.router import Router
from roofbot.serial_link import SerialLink

COMMANDS = {"start": MsgType.START, "resolved": MsgType.RESOLVED, "skip": MsgType.SKIP_SPOT,
            "estop": MsgType.ESTOP, "reset": MsgType.RESET}


def stdin_reader(out: "queue.Queue[str]") -> None:
    for line in sys.stdin:
        out.put(line.strip().lower())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--rows", type=int, default=2)
    parser.add_argument("--spots", type=int, default=3)
    parser.add_argument("--spacing-mm", type=float, default=300.0)
    args = parser.parse_args()

    route = Route([RowPlan(args.spots, args.spacing_mm, 100.0 if i == 0 else 0.0) for i in range(args.rows)])
    incoming: "queue.Queue[Message]" = queue.Queue()
    link = SerialLink(args.port, on_message=incoming.put, on_error=lambda text: print(f"[link] {text}"),
                      baud=args.baud)

    def show_alert(msg: Message) -> None:
        p = msg.params
        print(f"[ALERT] row {msg.row} spot {msg.spot}: {p.get('subsystem')} {msg.code}"
              f" {p.get('detail', '')} (skip allowed: {p.get('allow_skip')})")

    router = Router(route, send_to_link=link.send, on_alert=show_alert)
    link.start()

    typed: "queue.Queue[str]" = queue.Queue()
    threading.Thread(target=stdin_reader, args=(typed,), daemon=True).start()
    print("Commands: start, resolved, skip, estop, reset, status, quit")

    last_state = None
    try:
        while True:
            now = time.monotonic()
            while not incoming.empty():
                router.on_link_message(incoming.get(), now)
            while not typed.empty():
                word = typed.get()
                if word == "quit":
                    return
                if word == "status":
                    s = router.supervisor
                    print(f"state={s.state.value} row={s.row} spot={s.spot} link={'up' if link.connected else 'DOWN'}")
                elif word in COMMANDS:
                    router.on_operator(COMMANDS[word], now)
                else:
                    print("unknown command")
            router.tick(now)
            if router.supervisor.state != last_state:
                last_state = router.supervisor.state
                print(f"[state] {last_state.value}")
            time.sleep(0.02)
    finally:
        link.stop()


if __name__ == "__main__":
    main()
