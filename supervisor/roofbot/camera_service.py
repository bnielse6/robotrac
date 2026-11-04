"""The camera, from the point of view of the ESP32 subsystems.

The real camera and its vision code run on the Pi. A subsystem on the ESP32
sends a QUERY ("did the plate arrive?"), and this service sends back an ANSWER.

Today the answers are scripted or fixed, so the rest of the system can be
tested without a camera. When the vision code exists, pass it in as `decide`.
"""
from __future__ import annotations

from collections import deque
from typing import Callable, Optional

from .messages import CAMERA_QUESTIONS, Message, MsgType, Node


class CameraService:
    def __init__(self, decide: Optional[Callable[[str, Message], bool]] = None):
        """decide(question, query) returns True for yes. The default says yes to everything."""
        self.decide = decide or (lambda question, query: True)
        self._script: dict[str, deque] = {q: deque() for q in CAMERA_QUESTIONS}
        self.queries: list[Message] = []

    def queue(self, question: str, *answers: bool) -> "CameraService":
        """Scripted answers for a question, used one per query before `decide` is asked."""
        self._script[question].extend(answers)
        return self

    def handle(self, query: Message) -> Message:
        """Turn a QUERY into the ANSWER to send back."""
        question = query.params["question"]
        self.queries.append(query)
        scripted = self._script[question]
        ok = scripted.popleft() if scripted else bool(self.decide(question, query))
        return Message(MsgType.ANSWER, Node.CAMERA, query.src, ref=query.id,
                       row=query.row, spot=query.spot, params={"ok": ok, "question": question})
