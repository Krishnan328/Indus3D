"""MQTT feed for Moonraker's [sensor]: wire format, non-blocking behaviour, payload mapping."""
import json
import socket
import threading
import time

import esp_bed_monitor_daemon as dm
import mqtt_publish as mp


class FakeBroker:
    def __init__(self, refuse=False):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(2)
        self.port = self.srv.getsockname()[1]
        self.received = []                      # raw packets after CONNECT
        self.connects = []
        self.refuse = refuse
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(c,), daemon=True).start()

    def _client(self, c):
        head = c.recv(1)
        ln = 0
        shift = 0
        while True:
            b = c.recv(1)[0]
            ln |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
        body = b""
        while len(body) < ln:
            body += c.recv(ln - len(body))
        self.connects.append((head[0], body))
        c.sendall(bytes([0x20, 2, 0, 5 if self.refuse else 0]))
        if self.refuse:
            c.close()
            return
        while True:
            try:
                data = c.recv(4096)
            except OSError:
                return
            if not data:
                return
            self.received.append(data)

    def close(self):
        self.srv.close()


def wait_for(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_packets_are_valid_mqtt_311():
    pkt = mp.connect_packet("cid", 60, "u", "p")
    assert pkt[0] == 0x10 and b"MQTT" in pkt and pkt[8] == 4          # protocol level 4 = 3.1.1
    assert pkt[9] & 0xC0 == 0xC0                                        # username + password flags
    pub = mp.publish_packet("a/b", b"xyz", retain=True)
    assert pub[0] == 0x31 and pub[1] == 2 + 3 + 3 and pub.endswith(b"xyz")
    big = mp.publish_packet("t", b"x" * 300)
    assert big[1] & 0x80 and big[2] == 2                                # 2-byte remaining length


def test_publishes_latest_payload_to_broker():
    b = FakeBroker()
    p = mp.MqttPublisher("127.0.0.1", b.port, "indus3d/bed_hub/state").start()
    try:
        assert wait_for(lambda: p.connected)
        p.publish(b'{"crash_latched": 0}')
        assert wait_for(lambda: any(b"crash_latched" in r for r in b.received))
        assert any(b"indus3d/bed_hub/state" in r for r in b.received)
        assert b.connects[0][0] == 0x10
    finally:
        p.stop()
        b.close()


def test_unreachable_broker_never_blocks_the_caller():
    p = mp.MqttPublisher("127.0.0.1", 1, connect_fn=lambda: (_ for _ in ()).throw(OSError("refused"))).start()
    t0 = time.time()
    for _ in range(1000):
        p.publish(b"{}")
    assert time.time() - t0 < 0.5
    assert wait_for(lambda: p.last_error is not None)
    assert not p.connected
    p.stop()


def test_refused_connack_is_reported():
    b = FakeBroker(refuse=True)
    p = mp.MqttPublisher("127.0.0.1", b.port).start()
    try:
        assert wait_for(lambda: p.last_error and "refused" in p.last_error)
    finally:
        p.stop()
        b.close()


def test_payload_is_numeric_and_omits_missing_chamber_values():
    full = dm.mqtt_payload({"bed_accel": {"jerk_mg": 12}, "chamber": {"temp_c": 26.5, "humidity_pct": 40.1, "pressure_hpa": 1001.2},
                            "crash_detected": False, "crash_threshold_mg": 2000})
    assert full == {"crash_latched": 0, "bed_jerk_mg": 12, "crash_threshold_mg": 2000,
                    "chamber_temp_c": 26.5, "chamber_humidity_pct": 40.1, "chamber_pressure_hpa": 1001.2}
    dead = dm.mqtt_payload({"bed_accel": {"jerk_mg": 3}, "chamber": None, "crash_detected": True,
                            "crash_info": {"peak_jerk_mg": 2450}})
    assert "chamber_temp_c" not in dead and dead["crash_latched"] == 1 and dead["crash_peak_jerk_mg"] == 2450
    assert all(isinstance(v, (int, float)) for v in dead.values())


def test_daemon_publishes_each_telemetry_line(hub, moon, clock, tmp_path):
    got = []

    class Pub:
        def publish(self, payload):
            got.append(json.loads(payload))

    d = dm.HubDaemon(port="/dev/fake", opener=lambda p, b: hub, finder=lambda a, o: "/dev/fake", http=moon, clock=clock,
                     sleep=lambda s: None, data_dir=tmp_path, csv_log=False, async_actions=False, publisher=Pub())
    d.handle_line(json.dumps({"bed_accel": {"jerk_mg": 5}, "chamber": {"temp_c": 27.0}, "crash_detected": False}))
    assert got and got[0]["chamber_temp_c"] == 27.0
