"""Connects the Supervisor, the camera service, the ESP32 link and the operator.

The Supervisor knows nothing about serial ports. The Router sits on the Pi and
moves messages between the pieces:

    operator  --on_operator-->  Router  --> Supervisor
    ESP32 link --on_link----->  Router  --> Supervisor (DONE, FAULT, ...)
                                        --> CameraService (QUERY), answer goes back to the link
    Supervisor --send-------->  Router  --> ESP32 link (CMD_START, CMD_ABORT, HEARTBEAT)
                                        --> operator callback (ALERT)

It also feeds the Supervisor the camera heartbeat. For now that heartbeat says
what `camera_ok` says. When the real camera exists, `camera_ok` should return
whether frames are arriving and the image is usable.
"""
from __future__ import annotations

from typing import Callable, Optional

from .camera_service import CameraService
from .messages import Message, MsgType, Node
from .route import Route
from .supervisor import Config, Supervisor


class Router:
    def __init__(self, route: Route, send_to_link: Callable[[Message], object],
                 on_alert: Optional[Callable[[Message], None]] = None,
                 camera: Optional[CameraService] = None,
                 camera_ok: Optional[Callable[[], bool]] = None,
                 config: Optional[Config] = None,
                 camera_heartbeat_s: float = 0.25):
        self.send_to_link = send_to_link
        self.on_alert = on_alert or (lambda msg: None)
        self.camera = camera or CameraService()
        self.camera_ok = camera_ok or (lambda: True)
        self.camera_heartbeat_s = camera_heartbeat_s
        self.supervisor = Supervisor(route, config, send=self._from_supervisor)
        self._last_camera_beat: Optional[float] = None

    def on_link_message(self, msg: Message, now: float) -> None:
        """A message arrived from the ESP32."""
        if msg.type is MsgType.QUERY:
            self.send_to_link(self.camera.handle(msg))
        else:
            self.supervisor.on_message(msg, now)

    def on_operator(self, mtype: MsgType, now: float) -> None:
        src = Node.ESTOP if mtype is MsgType.ESTOP else Node.OPERATOR
        self.supervisor.on_message(Message(mtype, src, Node.SUPERVISOR), now)

    def tick(self, now: float) -> None:
        if self._last_camera_beat is None or now - self._last_camera_beat >= self.camera_heartbeat_s:
            self._last_camera_beat = now
            self.supervisor.on_message(
                Message(MsgType.HEARTBEAT, Node.CAMERA, Node.SUPERVISOR, params={"ok": bool(self.camera_ok())}), now)
        self.supervisor.tick(now)

    def _from_supervisor(self, msg: Message) -> None:
        if msg.dst == Node.OPERATOR.value:
            self.on_alert(msg)
        else:
            self.send_to_link(msg)
