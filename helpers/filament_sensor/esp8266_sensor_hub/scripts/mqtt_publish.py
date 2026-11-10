"""Minimal MQTT 3.1.1 publisher (QoS 0, stdlib only).

Lets the hub daemon feed Moonraker's [sensor] component (and so the Fluidd/Mainsail sensor cards)
without pulling in paho-mqtt. Publishing never blocks the caller: the latest message is handed to
a worker thread that (re)connects with back-off and drops anything it could not send, because for a
1 Hz status feed only the newest value matters.
"""

import logging
import socket
import threading
import time
from typing import Optional

log = logging.getLogger("bedhub.mqtt")


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _utf8(s: str) -> bytes:
    b = s.encode()
    return len(b).to_bytes(2, "big") + b


def connect_packet(client_id: str, keepalive: int = 60, username: str = "", password: str = "") -> bytes:
    flags = 0x02                                              # clean session
    payload = _utf8(client_id)
    if username:
        flags |= 0x80
        payload += _utf8(username)
        if password:
            flags |= 0x40
            payload += _utf8(password)
    var = _utf8("MQTT") + bytes([4, flags]) + keepalive.to_bytes(2, "big")
    body = var + payload
    return bytes([0x10]) + _varint(len(body)) + body


def publish_packet(topic: str, payload: bytes, retain: bool = False) -> bytes:
    body = _utf8(topic) + payload
    return bytes([0x30 | (1 if retain else 0)]) + _varint(len(body)) + body


PINGREQ = bytes([0xC0, 0x00])
DISCONNECT = bytes([0xE0, 0x00])


class MqttPublisher:
    def __init__(self, host: str, port: int = 1883, topic: str = "indus3d/bed_hub/state", client_id: str = "indus3d-bed-hub",
                 username: str = "", password: str = "", retain: bool = True, keepalive: int = 60, connect_fn=None):
        self.host, self.port, self.topic = host, port, topic
        self.client_id, self.username, self.password = client_id, username, password
        self.retain, self.keepalive = retain, keepalive
        self._connect_fn = connect_fn or (lambda: socket.create_connection((host, port), timeout=5))
        self._pending: Optional[bytes] = None
        self._cond = threading.Condition()
        self._stop = False
        self.connected = False
        self.sent = 0
        self.last_error: Optional[str] = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="mqtt-pub")

    def start(self) -> "MqttPublisher":
        self._thread.start()
        return self

    def stop(self):
        with self._cond:
            self._stop = True
            self._cond.notify_all()

    def publish(self, payload: bytes):
        """Queue the newest payload (replaces one that has not been sent yet)."""
        with self._cond:
            self._pending = payload
            self._cond.notify_all()

    # -- worker ---------------------------------------------------------------------------------
    def _run(self):
        backoff = 1.0
        while not self._stop:
            sock = None
            try:
                sock = self._connect_fn()
                sock.settimeout(5)
                sock.sendall(connect_packet(self.client_id, self.keepalive, self.username, self.password))
                ack = sock.recv(4)
                if len(ack) < 4 or ack[0] != 0x20 or ack[3] != 0:
                    raise OSError(f"broker refused the connection (CONNACK {ack.hex() or 'empty'})")
                self.connected, self.last_error, backoff = True, None, 1.0
                log.info("MQTT connected to %s:%s, publishing to %s", self.host, self.port, self.topic)
                last_tx = time.monotonic()
                while not self._stop:
                    with self._cond:
                        if self._pending is None:
                            self._cond.wait(timeout=self.keepalive / 2)
                        msg, self._pending = self._pending, None
                    if msg is not None:
                        sock.sendall(publish_packet(self.topic, msg, self.retain))
                        self.sent += 1
                        last_tx = time.monotonic()
                    elif time.monotonic() - last_tx >= self.keepalive / 2:
                        sock.sendall(PINGREQ)
                        last_tx = time.monotonic()
                        sock.settimeout(0.01)
                        try:
                            sock.recv(16)                     # swallow PINGRESP
                        except (socket.timeout, BlockingIOError):
                            pass
                        sock.settimeout(5)
            except OSError as e:
                self.last_error = str(e)
                if self.connected:
                    log.warning("MQTT link lost: %s", e)
                elif backoff <= 1.0:
                    log.warning("MQTT broker unreachable (%s): will keep retrying quietly", e)
                self.connected = False
                with self._cond:
                    self._pending = None
                    self._cond.wait(timeout=backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                if sock:
                    try:
                        sock.sendall(DISCONNECT) if self._stop else None
                        sock.close()
                    except OSError:
                        pass
        self.connected = False
