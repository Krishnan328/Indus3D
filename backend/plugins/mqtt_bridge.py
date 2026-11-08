"""
plugins/mqtt_bridge.py  (E4)
-----------------------------
Publishes print state and controller events to an MQTT broker (Home
Assistant, Node-RED, ...). Needs no extra package: a minimal MQTT 3.1.1
publisher (QoS 0, optional username/password, last-will availability) is built
in. Disabled unless INDUS3D_MQTT_HOST is set.

INDUS3D_MQTT_HOST / _PORT (1883) / _USER / _PASSWORD
INDUS3D_MQTT_PREFIX    topic prefix, default "indus3d"
INDUS3D_MQTT_HA=0      disable Home Assistant discovery messages (default on)

Topics: <prefix>/availability (online/offline, retained, will)
        <prefix>/state   JSON every 5 s (print state, temps, progress, auto-pilot)
        <prefix>/event   JSON per applied/vetoed command
TLS is not supported (plain TCP): use it on a trusted LAN or via a local broker.

GET /api/v1/plugins/mqtt_bridge
"""

import json
import logging
import os
import queue
import socket
import threading
import time

from plugins._common import latest_telemetry

PLUGIN_INFO = {
    "title": "MQTT / Home Assistant bridge",
    "description": "Publishes state and controller events to an MQTT broker, with HA discovery. Opt-in.",
}

STATE_EVERY_S = 5.0


# -- minimal MQTT 3.1.1 ---------------------------------------------------------
def _len(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n % 128, n // 128
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _s(text: str) -> bytes:
    b = text.encode("utf-8")
    return len(b).to_bytes(2, "big") + b


def connect_packet(client_id, user=None, password=None, will_topic=None, will_payload=b"offline", keepalive=0):
    flags = 0x02                                       # clean session
    payload = _s(client_id)
    if will_topic:
        flags |= 0x04 | 0x20                           # will, retained, QoS 0
        payload += _s(will_topic) + len(will_payload).to_bytes(2, "big") + will_payload
    if user:
        flags |= 0x80
        payload += _s(user)
        if password:
            flags |= 0x40
            payload += _s(password)
    var = _s("MQTT") + bytes([4, flags]) + keepalive.to_bytes(2, "big")
    return b"\x10" + _len(len(var) + len(payload)) + var + payload


def publish_packet(topic, payload: bytes, retain=False):
    body = _s(topic) + payload
    return bytes([0x30 | (1 if retain else 0)]) + _len(len(body)) + body


class MqttBridge:
    def __init__(self, host=None, port=None, user=None, password=None, prefix=None, ha=None):
        e = os.environ.get
        self.host = e("INDUS3D_MQTT_HOST", "") if host is None else host
        self.port = int(e("INDUS3D_MQTT_PORT", 1883)) if port is None else port
        self.user = e("INDUS3D_MQTT_USER", "") if user is None else user
        self.password = e("INDUS3D_MQTT_PASSWORD", "") if password is None else password
        self.prefix = (e("INDUS3D_MQTT_PREFIX", "indus3d") if prefix is None else prefix).strip("/")
        self.ha = (e("INDUS3D_MQTT_HA", "1") != "0") if ha is None else ha
        self.q: "queue.Queue" = queue.Queue(maxsize=200)
        self.connected = False
        self.last_error = None
        self.published = 0
        self._last_state = 0.0
        self._started = False
        self._sock = None

    @property
    def enabled(self):
        return bool(self.host)

    def publish(self, topic, payload, retain=False):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        try:
            self.q.put_nowait((f"{self.prefix}/{topic}", data, retain))
        except queue.Full:                          # drop the newest rather than block the control loop
            pass

    # -- worker --------------------------------------------------------------
    def _connect(self):
        s = socket.create_connection((self.host, self.port), timeout=5)
        s.sendall(connect_packet(f"indus3d-{os.getpid()}", self.user or None, self.password or None,
                                 f"{self.prefix}/availability"))
        ack = s.recv(4)
        if len(ack) < 4 or ack[0] != 0x20 or ack[3] != 0:
            s.close()
            raise ConnectionError(f"broker refused the connection (CONNACK {ack!r})")
        self._sock = s
        self.connected, self.last_error = True, None
        s.sendall(publish_packet(f"{self.prefix}/availability", b"online", retain=True))
        if self.ha:
            for pkt in self._discovery():
                s.sendall(pkt)

    def _discovery(self):
        sensors = [("ext_temp", "Hotend temperature", "°C", "temperature"),
                   ("bed_temp", "Bed temperature", "°C", "temperature"),
                   ("progress", "Print progress", "%", None)]
        pkts = []
        for key, name, unit, dev in sensors:
            cfg = {"name": f"Indus3D {name}", "unique_id": f"indus3d_{key}", "state_topic": f"{self.prefix}/state",
                   "value_template": "{{ (value_json.%s) | round(1) }}" % key, "unit_of_measurement": unit,
                   "availability_topic": f"{self.prefix}/availability",
                   "device": {"identifiers": ["indus3d"], "name": "Indus3D"}}
            if dev:
                cfg["device_class"] = dev
            pkts.append(publish_packet(f"homeassistant/sensor/indus3d_{key}/config", json.dumps(cfg).encode(), True))
        state = {"name": "Indus3D print state", "unique_id": "indus3d_print_state", "state_topic": f"{self.prefix}/state",
                 "value_template": "{{ value_json.print_state }}", "device": {"identifiers": ["indus3d"], "name": "Indus3D"}}
        pkts.append(publish_packet("homeassistant/sensor/indus3d_print_state/config", json.dumps(state).encode(), True))
        return pkts

    def _loop(self):
        while True:
            try:
                if not self._sock:
                    self._connect()
                topic, data, retain = self.q.get(timeout=1.0)
                self._sock.sendall(publish_packet(topic, data, retain))
                self.published += 1
            except queue.Empty:
                continue
            except Exception as e:  # noqa: BLE001 — reconnect with backoff
                self.connected, self.last_error = False, f"{type(e).__name__}: {e}"
                if self._sock:
                    try:
                        self._sock.close()
                    except OSError:
                        pass
                    self._sock = None
                time.sleep(5)

    def _start(self):
        if not self._started and self.enabled:
            self._started = True
            threading.Thread(target=self._loop, daemon=True, name="mqtt-bridge").start()

    # -- hooks ---------------------------------------------------------------
    def tick(self, snap, ctx):
        if not self.enabled:
            return
        self._start()
        now = ctx.get("now", time.time())
        if now - self._last_state >= STATE_EVERY_S:
            self._last_state = now
            from digital_twin.quality_controller import quality_controller as qc
            self.publish("state", {
                "print_state": snap.get("print_state"), "filename": snap.get("filename"),
                "ext_temp": snap.get("ext_temp"), "ext_target": snap.get("ext_target"),
                "bed_temp": snap.get("bed_temp"), "bed_target": snap.get("bed_target"),
                "progress": round((snap.get("progress") or 0) * 100, 1),
                "autopilot": bool(qc.auto_pilot), "ts": now})

    def on_sent(self, results, ctx):
        if self.enabled:
            for r in results:
                self.publish("event", {"kind": "applied" if r["ok"] else "failed", "command": r["command"],
                                       "ts": r.get("ts")})

    def on_vetoed(self, vetoes, ctx):
        if self.enabled:
            for v in vetoes:
                self.publish("event", {"kind": "vetoed", "command": v["command"], "plugin": v["plugin"],
                                       "reason": v["reason"], "ts": ctx.get("now")})

    def status(self):
        return {"enabled": self.enabled, "host": self.host or None, "port": self.port, "prefix": self.prefix,
                "connected": self.connected, "published": self.published, "queued": self.q.qsize(),
                "last_error": self.last_error}


bridge = MqttBridge()


def register_hooks(hooks) -> None:
    hooks.on("tick", bridge.tick, priority=75)
    hooks.on("commands.sent", bridge.on_sent, priority=96)
    hooks.on("commands.vetoed", bridge.on_vetoed, priority=96)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_mqtt_bridge", __name__, url_prefix="/api/v1/plugins/mqtt_bridge")

    @bp.route("", methods=["GET"])
    def mqtt_status():
        return jsonify(bridge.status())

    app.register_blueprint(bp)
