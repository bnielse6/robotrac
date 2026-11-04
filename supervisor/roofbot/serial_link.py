"""USB serial link to the ESP32. Needs `pip install pyserial`.

NOT TESTED AGAINST REAL HARDWARE. LineFramer is unit tested. SerialLink is a
first version to be exercised with a virtual serial pair and then the ESP32.

Opening the port resets most ESP32 boards. Expect a READY message from the
board after every (re)connect.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from .messages import MAX_LINE_BYTES, Message, MessageError, decode, encode


class LineFramer:
    """Turns arbitrary chunks of bytes into complete lines.

    A line longer than MAX_LINE_BYTES is dropped (including the rest of it, up to its newline).
    """

    def __init__(self, max_line: int = MAX_LINE_BYTES):
        self.max_line = max_line
        self._buf = bytearray()
        self._discarding = False
        self.dropped = 0

    def feed(self, data: bytes) -> list[bytes]:
        lines: list[bytes] = []
        for byte in data:
            if byte == 0x0A:  # newline
                if self._discarding:
                    self._discarding = False
                elif self._buf:
                    lines.append(bytes(self._buf))
                self._buf.clear()
            elif self._discarding:
                continue
            elif byte != 0x0D:  # ignore carriage returns
                self._buf.append(byte)
                if len(self._buf) > self.max_line:
                    self._buf.clear()
                    self._discarding = True
                    self.dropped += 1
        return lines


class SerialLink:
    def __init__(self, port: str, on_message: Callable[[Message], None],
                 on_error: Optional[Callable[[str], None]] = None,
                 baud: int = 115200, reconnect_s: float = 1.0):
        self.port = port
        self.baud = baud
        self.reconnect_s = reconnect_s
        self._on_message = on_message
        self._on_error = on_error or (lambda text: None)
        self._serial = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.connected = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="serial-link", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def send(self, msg: Message) -> bool:
        """False if the port is down. The caller (the Supervisor timeouts) deals with lost commands."""
        data = encode(msg)
        with self._lock:
            if not self.connected or self._serial is None:
                return False
            try:
                self._serial.write(data)
                return True
            except Exception as exc:  # port vanished
                self._on_error(f"write failed: {exc}")
                self.connected = False
                return False

    def _run(self) -> None:
        import serial  # imported here so the rest of the package works without pyserial

        while not self._stop.is_set():
            framer = LineFramer()
            try:
                port = serial.Serial(self.port, self.baud, timeout=0.1)
            except Exception as exc:
                self._on_error(f"cannot open {self.port}: {exc}")
                self._stop.wait(self.reconnect_s)
                continue
            with self._lock:
                self._serial = port
                self.connected = True
            try:
                while not self._stop.is_set():
                    chunk = port.read(256)
                    for line in framer.feed(chunk):
                        try:
                            self._on_message(decode(line))
                        except MessageError as exc:
                            self._on_error(f"bad line {line[:60]!r}: {exc}")
            except Exception as exc:
                self._on_error(f"read failed: {exc}")
            finally:
                with self._lock:
                    self.connected = False
                    self._serial = None
                try:
                    port.close()
                except Exception:
                    pass
            time.sleep(self.reconnect_s)
