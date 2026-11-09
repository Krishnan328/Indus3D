"""Host / Moonraker administration helpers behind the System page (``api/routes/system.py``) and the
``host_alerts`` plugin.

Everything here talks to Moonraker through ONE function, :func:`call`. In simulator mode ``call`` answers
from a small in-memory stand-in for Moonraker (:func:`_sim_call`) instead, so the page works offline and the
normalisers below are exercised by the same code path in both modes.

Moonraker endpoints used (checked against https://moonraker.readthedocs.io, "latest", Nov 2026):

====================================  =====================================================================
GET  /machine/system_info             OS, CPU model, memory, services and their states, network, CAN
GET  /machine/proc_stats              CPU/memory/temperature, ``throttled_state`` (Raspberry Pi only), uptime
GET  /printer/info                    hostname, Klipper state and version
GET  /server/info                     Moonraker version, API version, ``failed_components``
GET  /printer/objects/list|query      the ``mcu`` / ``mcu <name>`` objects: version, constants, ``last_stats``
POST /machine/services/<action>       {"service": name}; action = restart | start | stop
GET  /machine/update/status           update_manager state (``busy``, ``version_info``)
POST /machine/update/upgrade          {"name": ...} (API 1.5.0+; omit name = everything). Older Moonraker:
                                      /machine/update/{full,system,klipper,moonraker,client}
POST /machine/update/recover          {"name", "hard"}
GET  /server/database/list            {"namespaces", "backups"}   (``backups`` absent on old Moonraker)
POST /server/database/backup          {"filename"?}
POST /server/database/restore         {"filename"}  (Moonraker restarts right after)
DELETE /server/database/backup        ?filename=
GET  /machine/peripherals/{usb,serial,video,canbus}
GET  /server/announcements/list
====================================  =====================================================================

A missing endpoint (404/405) raises :class:`Unsupported`; an unreachable Moonraker raises
:class:`Unreachable`; any other refusal raises :class:`Refused`. Nothing in here accepts raw G-code or a raw
Moonraker path from a client.
"""

import os
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote

import requests

from api import moonraker_util as mu

TIMEOUT_S = 8
LONG_TIMEOUT_S = 900          # Moonraker answers an upgrade only when it has finished
CACHE_TTL_S = 4.0

# Oldest Moonraker the System page is written for. v0.9.0 is where the sqlite database (and with it the
# backup/restore API) and the ``machine/update/upgrade`` endpoint became the norm; older versions still
# work (every call degrades), they just get a warning. Override with INDUS3D_MIN_MOONRAKER, e.g. "v0.8.0".
DEFAULT_MIN_MOONRAKER = "v0.9.0"

# Services that are never touched while a print runs (stop/restart would kill the print).
_PRINT_CRITICAL = re.compile(r"^(klipper|klipper_mcu|moonraker)([-_][A-Za-z0-9_.-]*)?$", re.I)
_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_BACKUP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.db$")
_IFACE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,14}$")


class Unsupported(Exception):
    """Moonraker has no such endpoint (404/405)."""


class Unreachable(RuntimeError):
    """Moonraker did not answer."""


class Refused(RuntimeError):
    """Moonraker answered with an error."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ── Moonraker access ───────────────────────────────────────────────────────────────────────────────────
def is_sim() -> bool:
    try:
        import workers
        return workers.is_simulator(workers._active_worker)
    except Exception:  # noqa: BLE001
        return False


def _error_message(res) -> str:
    try:
        body = res.json()
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err)
        if err:
            return str(err)
    except Exception:  # noqa: BLE001
        pass
    return f"Moonraker answered {res.status_code}"


def call(method: str, path: str, body: Any = None, timeout: float = TIMEOUT_S) -> Any:
    """One Moonraker request, result unwrapped. Raises Unsupported / Unreachable / Refused."""
    if is_sim():
        return _sim_call(method, path, body)
    try:
        res = requests.request(method, mu.url(path), json=body, timeout=timeout)
    except requests.RequestException as e:
        raise Unreachable(f"Moonraker unreachable: {e}") from e
    if res.status_code in (404, 405):
        raise Unsupported(path.split("?")[0])
    if not res.ok:
        raise Refused(res.status_code, _error_message(res))
    try:
        data = res.json()
    except ValueError as e:
        raise Refused(res.status_code, "Moonraker sent invalid JSON") from e
    return data.get("result", data) if isinstance(data, dict) else data


_lock = threading.Lock()
_cache: Dict[str, Tuple[float, Any]] = {}


def reset_cache() -> None:
    with _lock:
        _cache.clear()


def cached(key: str, fetch: Callable[[], Any], ttl: float = CACHE_TTL_S) -> Any:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fetch()
    with _lock:
        _cache[key] = (time.monotonic(), value)
    return value


def print_active() -> bool:
    """A print is running or paused (never trust 'not sure' to mean 'busy': Moonraker refuses anyway)."""
    try:
        import workers
        w = workers._active_worker
        state = (getattr(w, "latest", None) or {}).get("print_state")
    except Exception:  # noqa: BLE001
        state = None
    if state:
        return state in ("printing", "paused")
    if is_sim():
        return False
    try:
        st = call("GET", "/printer/objects/query?print_stats").get("status", {}).get("print_stats", {})
        return st.get("state") in ("printing", "paused")
    except Exception:  # noqa: BLE001
        return False


# ── Raw sections ────────────────────────────────────────────────────────────────────────────────────────
def _mcu_section() -> dict:
    names = [o for o in call("GET", "/printer/objects/list").get("objects", []) if o == "mcu" or o.startswith("mcu ")]
    if not names:
        return {"status": {}}
    return call("GET", "/printer/objects/query?" + "&".join(quote(n, safe="") for n in names))


def _announcements_section() -> dict:
    return call("GET", "/server/announcements/list?include_dismissed=false")


SECTIONS: Dict[str, Callable[[], Any]] = {
    "system_info": lambda: call("GET", "/machine/system_info"),
    "proc_stats": lambda: call("GET", "/machine/proc_stats"),
    "printer_info": lambda: call("GET", "/printer/info"),
    "server_info": lambda: call("GET", "/server/info"),
    "mcus": _mcu_section,
    "updates": lambda: call("GET", "/machine/update/status"),
    "backups": lambda: call("GET", "/server/database/list"),
    "announcements": _announcements_section,
}


def fetch_sections(names: List[str], use_cache: bool = True) -> Dict[str, dict]:
    """``{name: {"ok": bool, "data": raw, "unsupported": bool, "error": str|None}}``. Moonraker being down
    for every section raises Unreachable (one failed connect short-circuits the rest)."""
    out: Dict[str, dict] = {}
    down = None
    for name in names:
        if down:
            out[name] = {"ok": False, "data": None, "unsupported": False, "error": down}
            continue
        try:
            fetch = SECTIONS[name]
            data = cached(f"sec:{name}", fetch) if use_cache else fetch()
            out[name] = {"ok": True, "data": data, "unsupported": False, "error": None}
        except Unsupported as e:
            out[name] = {"ok": False, "data": None, "unsupported": True,
                         "error": f"{e} is not available on this Moonraker"}
        except Unreachable as e:
            down = str(e)
            out[name] = {"ok": False, "data": None, "unsupported": False, "error": down}
        except Refused as e:
            out[name] = {"ok": False, "data": None, "unsupported": False, "error": str(e)}
    if down and all(s["error"] == down for s in out.values()):
        raise Unreachable(down)
    return out


def section_status(secs: Dict[str, dict]) -> dict:
    return {n: {"ok": s["ok"], "unsupported": s["unsupported"], "error": s["error"]} for n, s in secs.items()}


# ── Normalisers (pure) ──────────────────────────────────────────────────────────────────────────────────
THROTTLE_NOW = {0: "Under-voltage", 1: "Frequency capped", 2: "Throttled", 3: "Temperature limit"}
THROTTLE_PAST = {16: "Under-voltage", 17: "Frequency capped", 18: "Throttled", 19: "Temperature limit"}


def throttle_view(ts: Any) -> dict:
    if not isinstance(ts, dict):
        return {"supported": False, "bits": 0, "now": [], "since_boot": [], "flags": []}
    bits = int(ts.get("bits") or 0)
    return {
        "supported": True, "bits": bits, "flags": list(ts.get("flags") or []),
        "now": [label for b, label in THROTTLE_NOW.items() if bits >> b & 1],
        "since_boot": [label for b, label in THROTTLE_PAST.items() if bits >> b & 1],
    }


def parse_version(text: Any) -> Optional[Tuple[int, ...]]:
    m = re.match(r"^v?(\d+)\.(\d+)(?:\.(\d+))?", str(text or "").strip())
    if not m:
        return None
    return tuple(int(x or 0) for x in m.groups())


def min_moonraker() -> str:
    return os.environ.get("INDUS3D_MIN_MOONRAKER", "").strip() or DEFAULT_MIN_MOONRAKER


def _first(*vals):
    return next((v for v in vals if v not in (None, "")), None)


def host_view(secs: Dict[str, dict]) -> dict:
    def data(name):
        s = secs.get(name)
        return (s or {}).get("data") if (s or {}).get("ok") else None

    si = (data("system_info") or {}).get("system_info", {})
    proc = data("proc_stats") or {}
    pinfo = data("printer_info") or {}
    sinfo = data("server_info") or {}
    cpu, dist = si.get("cpu_info", {}), si.get("distribution", {})
    sm = proc.get("system_memory") or {}
    total = _first(sm.get("total"), cpu.get("total_memory"))
    avail = sm.get("available")
    used = _first(sm.get("used"), (total - avail) if isinstance(total, (int, float)) and isinstance(avail, (int, float)) else None)
    mem_pct = round(100.0 * used / total, 1) if isinstance(used, (int, float)) and total else None
    net_info = si.get("network") or {}
    network = []
    for name, usage in (proc.get("network") or {}).items():
        if name == "lo":
            continue
        ips = [a.get("address") for a in (net_info.get(name) or {}).get("ip_addresses", []) if isinstance(a, dict)]
        ip4 = next((a for a in ips if a and ":" not in a), None)
        network.append({"name": name, "ip": ip4 or (ips[0] if ips else None),
                        "bandwidth_bps": usage.get("bandwidth"), "rx_bytes": usage.get("rx_bytes"),
                        "tx_bytes": usage.get("tx_bytes")})
    cpu_usage = (proc.get("system_cpu_usage") or {}).get("cpu")
    return {
        "hostname": pinfo.get("hostname"),
        "os": dist.get("name"), "os_id": dist.get("id"), "arch": cpu.get("processor"),
        "model": _first(cpu.get("model"), cpu.get("hardware_desc"), cpu.get("cpu_desc")),
        "cpu_count": cpu.get("cpu_count"), "cpu_desc": cpu.get("cpu_desc"),
        "cpu_usage_pct": cpu_usage, "cpu_temp_c": proc.get("cpu_temp"),
        "memory_total_kb": total, "memory_used_kb": used, "memory_available_kb": avail, "memory_used_pct": mem_pct,
        "uptime_s": proc.get("system_uptime"), "websocket_connections": proc.get("websocket_connections"),
        "throttle": throttle_view(proc.get("throttled_state")),
        "network": network,
        "python": ".".join(str(x) for x in (si.get("python", {}).get("version") or [])[:3]) or None,
        "virtualization": (si.get("virtualization") or {}).get("virt_type"),
        "sd_card": ({"product": (si.get("sd_info") or {}).get("product_name"),
                     "capacity": (si.get("sd_info") or {}).get("capacity")} if si.get("sd_info") else None),
        "klipper": {"state": pinfo.get("state"), "message": pinfo.get("state_message"),
                    "version": pinfo.get("software_version"), "log_file": pinfo.get("log_file"),
                    "config_file": pinfo.get("config_file")} if pinfo else None,
        "moonraker": {"version": sinfo.get("moonraker_version"), "api_version": sinfo.get("api_version_string"),
                      "klippy_state": sinfo.get("klippy_state"), "klippy_connected": sinfo.get("klippy_connected"),
                      "failed_components": list(sinfo.get("failed_components") or []),
                      "warnings": list(sinfo.get("warnings") or [])} if sinfo else None,
        "min_moonraker": min_moonraker(),
    }


def mcus_view(raw: Optional[dict]) -> List[dict]:
    out = []
    for name, st in ((raw or {}).get("status") or {}).items():
        if not isinstance(st, dict):
            continue
        stats = st.get("last_stats") or {}
        const = st.get("mcu_constants") or {}
        awake = stats.get("mcu_awake")
        out.append({
            "name": "main" if name == "mcu" else name.split(" ", 1)[1] if " " in name else name,
            "object": name,
            "version": st.get("mcu_version"), "build_versions": st.get("mcu_build_versions"),
            "chip": const.get("MCU"), "clock_freq": const.get("CLOCK_FREQ"),
            "awake_pct": round(100.0 * awake, 1) if isinstance(awake, (int, float)) else None,
            "task_avg_us": round(stats["mcu_task_avg"] * 1e6, 1) if isinstance(stats.get("mcu_task_avg"), (int, float)) else None,
            "freq": stats.get("freq"),
            "bytes_retransmit": stats.get("bytes_retransmit"), "bytes_invalid": stats.get("bytes_invalid"),
            "srtt": stats.get("srtt"), "stats": stats,
        })
    out.sort(key=lambda m: (m["object"] != "mcu", m["object"]))
    return out


def self_service_prefixes() -> List[str]:
    raw = os.environ.get("INDUS3D_SELF_SERVICE", "indus3d")
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def is_self_service(name: str) -> bool:
    n = (name or "").lower()
    return any(n.startswith(p) for p in self_service_prefixes())


def services_view(raw: Optional[dict]) -> dict:
    si = (raw or {}).get("system_info", {})
    provider = si.get("provider")
    states = si.get("service_state") or {}
    services = []
    for name in si.get("available_services") or []:
        st = states.get(name) or {}
        services.append({"name": name, "active_state": st.get("active_state"), "sub_state": st.get("sub_state"),
                         "is_self": is_self_service(name), "print_critical": bool(_PRINT_CRITICAL.match(name))})
    return {"provider": provider, "manageable": bool(provider) and provider != "none", "services": services}


def _update_pending(u: dict) -> bool:
    kind = u.get("configured_type")
    if kind == "system" or "package_count" in u:
        return int(u.get("package_count") or 0) > 0
    behind = u.get("commits_behind_count")
    if isinstance(behind, int) and behind > 0:
        return True
    if u.get("commits_behind"):
        return True
    cur, rem = u.get("version"), u.get("remote_version")
    if rem and rem not in ("?", "unknown") and cur and cur != rem:
        return True
    return u.get("remote_hash") == "update-available"


def updates_view(raw: Optional[dict]) -> dict:
    raw = raw or {}
    comps = []
    for name, u in (raw.get("version_info") or {}).items():
        if not isinstance(u, dict):
            continue
        u = dict(u, name=u.get("name") or name)
        comps.append({
            "name": name, "type": u.get("configured_type"), "channel": u.get("channel"),
            "version": u.get("version"), "remote_version": u.get("remote_version"),
            "rollback_version": u.get("rollback_version"),
            "update_available": _update_pending(u),
            "commits_behind": len(u.get("commits_behind") or []) if not isinstance(u.get("commits_behind_count"), int)
            else u["commits_behind_count"],
            "recent_commits": [{"subject": c.get("subject"), "author": c.get("author"), "tag": c.get("tag")}
                               for c in (u.get("commits_behind") or [])[:5] if isinstance(c, dict)],
            "is_valid": u.get("is_valid", True), "is_dirty": u.get("is_dirty"), "corrupt": u.get("corrupt"),
            "detached": u.get("detached"), "warnings": list(u.get("warnings") or []),
            "anomalies": list(u.get("anomalies") or []),
            "package_count": u.get("package_count"), "package_list": list(u.get("package_list") or [])[:50],
            "recoverable": u.get("configured_type") == "git_repo",
        })
    comps.sort(key=lambda c: (c["name"] != "system", c["name"] not in ("klipper", "moonraker"), c["name"]))
    return {"busy": bool(raw.get("busy")), "components": comps,
            "pending": [c["name"] for c in comps if c["update_available"]],
            "github": {"limit": raw.get("github_rate_limit"), "remaining": raw.get("github_requests_remaining"),
                       "reset": raw.get("github_limit_reset_time")}}


def backups_view(raw: Optional[dict]) -> dict:
    raw = raw or {}
    if "backups" not in raw:
        return {"supported": False, "backups": []}
    return {"supported": True, "backups": [{"filename": f} for f in sorted(raw.get("backups") or [], reverse=True)]}


def announcements_view(raw: Optional[dict]) -> List[dict]:
    out = []
    for e in (raw or {}).get("entries") or []:
        if not isinstance(e, dict) or e.get("dismissed"):
            continue
        out.append({"id": e.get("entry_id"), "title": e.get("title"), "description": str(e.get("description") or "")[:512],
                    "priority": e.get("priority") or "normal", "url": e.get("url"), "date": e.get("date"),
                    "feed": e.get("feed")})
    return out


# ── Alerts ──────────────────────────────────────────────────────────────────────────────────────────────
def _alert(aid, severity, title, detail, source, notify):
    return {"id": aid, "severity": severity, "title": title, "detail": detail, "source": source, "notify": notify}


def compute_alerts(secs: Dict[str, dict]) -> List[dict]:
    """Active conditions from the raw sections. ``notify`` says whether the host_alerts plugin pushes it as a
    notification (the page shows every alert). Ids are stable while a condition lasts."""
    alerts: List[dict] = []
    host = host_view(secs)
    th = host["throttle"]
    if "Under-voltage" in th["now"]:
        alerts.append(_alert("throttle:undervoltage", "critical", "Under-voltage right now",
                             "The host reports a supply voltage below spec: use a better power supply or shorter, thicker cable. "
                             "This causes random disconnects and corrupt prints.", "host", True))
    capped = [x for x in th["now"] if x != "Under-voltage"]
    if capped:
        alerts.append(_alert("throttle:throttled", "warning", "Host is throttled", ", ".join(capped) + " (right now)", "host", True))
    if th["since_boot"] and not th["now"]:
        alerts.append(_alert("throttle:history", "info", "Throttling since boot",
                             ", ".join(th["since_boot"]) + " happened since the host booted", "host", False))

    mr = (host.get("moonraker") or {}).get("version")
    have, need = parse_version(mr), parse_version(min_moonraker())
    if have and need and have < need:
        alerts.append(_alert("moonraker:outdated", "warning", "Moonraker is outdated",
                             f"Running {mr}; the System page expects {min_moonraker()} or newer. Some features are unavailable.",
                             "moonraker", True))

    for name in (host.get("moonraker") or {}).get("failed_components") or []:
        alerts.append(_alert(f"component:{name}", "warning", f"Moonraker component failed: {name}",
                             "Check moonraker.log; this component did not start.", "moonraker", True))

    upd = (secs.get("updates") or {})
    if upd.get("ok"):
        for c in updates_view(upd["data"])["components"]:
            if not c["update_available"]:
                continue
            tail = c["remote_version"] or ""
            if c["name"] == "system":
                aid, detail = "update:system", f"{c.get('package_count') or '?'} system package(s) can be upgraded"
            else:
                aid = f"update:{c['name']}:{tail}"
                detail = f"{c['version'] or '?'} → {tail or 'newer commit'}"
                if c["commits_behind"]:
                    detail += f" ({c['commits_behind']} commit(s) behind)"
            alerts.append(_alert(aid, "info", f"Update available: {c['name']}", detail, "updates", True))

    ann = secs.get("announcements") or {}
    if ann.get("ok"):
        for a in announcements_view(ann["data"]):
            high = a["priority"] == "high"
            alerts.append(_alert(f"announcement:{a['id']}", "warning" if high else "info", a["title"] or "Moonraker announcement",
                                 a["description"], "announcements", high))
    return alerts


# ── Simulator stand-in for Moonraker ────────────────────────────────────────────────────────────────────
_SIM: Dict[str, Any] = {}


def sim_reset() -> None:
    _SIM.clear()
    _SIM.update({
        "backups": ["sqldb-backup-20260301-101500.db", "before-klipper-update.db"],
        "updated": set(), "services": {"klipper": "active", "klipper_mcu": "active", "moonraker": "active",
                                       "crowsnest": "active", "indus3d": "active"},
    })


sim_reset()


def _sim_system_info() -> dict:
    return {"system_info": {
        "provider": "systemd_dbus",
        "cpu_info": {"cpu_count": 4, "bits": "64bit", "processor": "aarch64", "cpu_desc": "Cortex-A72",
                     "hardware_desc": "BCM2711", "model": "Raspberry Pi 4 Model B Rev 1.4", "total_memory": 3885000,
                     "memory_units": "kB"},
        "sd_info": {"product_name": "SD32G", "capacity": "29.7 GiB"},
        "distribution": {"name": "Debian GNU/Linux 12 (bookworm)", "id": "debian", "version": "12"},
        "available_services": list(_SIM["services"]),
        "service_state": {n: {"active_state": s, "sub_state": "running" if s == "active" else "dead"}
                          for n, s in _SIM["services"].items()},
        "virtualization": {"virt_type": "none"}, "python": {"version": [3, 11, 2, "final", 0]},
        "network": {"wlan0": {"mac_address": "00:00:00:00:00:00", "ip_addresses": [{"family": "ipv4", "address": "192.168.1.50"}]}},
    }}


def _sim_proc_stats() -> dict:
    return {"moonraker_stats": [], "throttled_state": {"bits": 0, "flags": []}, "cpu_temp": 47.8,
            "network": {"lo": {"bandwidth": 0.0}, "wlan0": {"rx_bytes": 48471767, "tx_bytes": 113430843, "bandwidth": 4455.9}},
            "system_cpu_usage": {"cpu": 6.4}, "system_uptime": 187432.0, "websocket_connections": 2,
            "system_memory": {"total": 3885000, "available": 3100000, "used": 785000}}


def _sim_updates() -> dict:
    def git(name, ver, rem, behind):
        done = name in _SIM["updated"]
        return {"name": name, "configured_type": "git_repo", "channel": "dev", "is_valid": True, "is_dirty": False,
                "version": rem if done else ver, "remote_version": rem, "rollback_version": ver,
                "commits_behind": [] if done else [{"subject": "stm32: example fix", "author": "Dev", "tag": None}] * min(behind, 3),
                "commits_behind_count": 0 if done else behind, "warnings": [], "anomalies": []}
    info = {
        "system": {"name": "system", "configured_type": "system", "package_count": 0 if "system" in _SIM["updated"] else 4,
                   "package_list": [] if "system" in _SIM["updated"] else ["libtiff5", "rpi-eeprom", "tzdata", "curl"]},
        "klipper": git("klipper", "v0.12.0-310-g1a2b3c4", "v0.12.0-355-g9f8e7d6", 45),
        "moonraker": git("moonraker", "v0.9.3-60-gabc1234", "v0.9.3-60-gabc1234", 0),
        "mainsail": {"name": "mainsail", "configured_type": "web", "channel": "stable", "version": "v2.12.0",
                     "remote_version": "v2.12.0", "is_valid": True, "warnings": [], "anomalies": []},
    }
    return {"busy": False, "github_rate_limit": 60, "github_requests_remaining": 55, "github_limit_reset_time": 0,
            "version_info": info}


def _sim_call(method: str, path: str, body: Any) -> Any:
    route, _, query = path.partition("?")
    body = body if isinstance(body, dict) else {}
    if method == "GET":
        if route == "/machine/system_info":
            return _sim_system_info()
        if route == "/machine/proc_stats":
            return _sim_proc_stats()
        if route == "/printer/info":
            return {"state": "ready", "state_message": "Printer is ready", "hostname": "indus3d-sim",
                    "software_version": "v0.12.0-310-g1a2b3c4", "log_file": "/home/pi/printer_data/logs/klippy.log",
                    "config_file": "/home/pi/printer_data/config/printer.cfg"}
        if route == "/server/info":
            return {"klippy_connected": True, "klippy_state": "ready", "moonraker_version": "v0.9.3-60-gabc1234",
                    "api_version_string": "1.5.0", "failed_components": [], "warnings": []}
        if route == "/printer/objects/list":
            return {"objects": ["mcu", "mcu toolhead", "extruder", "heater_bed", "toolhead"]}
        if route == "/printer/objects/query":
            names = [unquote(x) for x in query.split("&") if x]
            sim = {
                "mcu": {"mcu_version": "v0.12.0-310-g1a2b3c4", "mcu_build_versions": "gcc: (15:10.3-2021.07-4) 10.3.1",
                        "mcu_constants": {"MCU": "stm32f446xx", "CLOCK_FREQ": 180000000},
                        "last_stats": {"mcu_awake": 0.012, "mcu_task_avg": 0.000004, "freq": 179999712,
                                       "bytes_retransmit": 0, "bytes_invalid": 0, "srtt": 0.001}},
                "mcu toolhead": {"mcu_version": "v0.12.0-310-g1a2b3c4", "mcu_build_versions": "gcc: 10.3.1",
                                 "mcu_constants": {"MCU": "rp2040", "CLOCK_FREQ": 12000000},
                                 "last_stats": {"mcu_awake": 0.004, "mcu_task_avg": 0.000003, "freq": 12000032,
                                                "bytes_retransmit": 0, "bytes_invalid": 0, "srtt": 0.002}},
                "print_stats": {"state": "standby"},
            }
            return {"status": {n: sim[n] for n in names if n in sim}}
        if route == "/machine/update/status":
            return _sim_updates()
        if route == "/server/database/list":
            return {"namespaces": ["moonraker", "webcams"], "backups": list(_SIM["backups"])}
        if route == "/machine/peripherals/usb":
            return {"usb_devices": [
                {"bus_num": 1, "device_num": 2, "usb_location": "1:2", "vendor_id": "1a40", "product_id": "0101",
                 "manufacturer": "Terminus Technology Inc.", "product": "USB 2.0 Hub", "class": "Hub",
                 "description": "Terminus Technology Inc. Hub"},
                {"bus_num": 1, "device_num": 4, "usb_location": "1:4", "vendor_id": "1d50", "product_id": "614e",
                 "manufacturer": "Klipper", "product": "stm32f446xx", "class": "Communications",
                 "description": "OpenMoko, Inc. Klipper 3d-Printer Firmware"}]}
        if route == "/machine/peripherals/serial":
            return {"serial_devices": [
                {"device_type": "usb", "device_path": "/dev/ttyACM0", "device_name": "ttyACM0", "driver_name": "cdc_acm",
                 "path_by_hardware": "/dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.2:1.0",
                 "path_by_id": "/dev/serial/by-id/usb-Klipper_stm32f446xx_0A1B2C3D-if00", "usb_location": "1:4"},
                {"device_type": "hardware_uart", "device_path": "/dev/ttyAMA0", "device_name": "ttyAMA0",
                 "driver_name": "uart-pl011", "path_by_hardware": None, "path_by_id": None, "usb_location": None}]}
        if route == "/machine/peripherals/video":
            return {"v4l2_devices": [{"device_name": "video0", "device_path": "/dev/video0", "camera_name": "UVC Camera",
                                      "driver_name": "uvcvideo", "hardware_bus": "usb-xhci-1.1",
                                      "path_by_id": "/dev/v4l/by-id/usb-Cam-video-index0", "modes": []}]}
        if route == "/machine/peripherals/canbus":
            return {"can_uuids": []}
        if route == "/server/announcements/list":
            return {"entries": [], "feeds": ["moonraker", "klipper"]}
    elif method == "POST":
        if route.startswith("/machine/services/"):
            svc = body.get("service")
            if svc in _SIM["services"]:
                action = route.rsplit("/", 1)[1]
                _SIM["services"][svc] = "inactive" if action == "stop" else "active"
                return "ok"
            raise Refused(400, f"Service '{svc}' not allowed")
        if route.startswith("/machine/update/"):
            what = body.get("name") or route.rsplit("/", 1)[1]
            _SIM["updated"].update(["klipper", "moonraker", "system", "mainsail"] if what in ("full", None) else [what])
            return "ok"
        if route == "/server/database/backup":
            name = body.get("filename") or time.strftime("sqldb-backup-%Y%m%d-%H%M%S.db")
            _SIM["backups"].append(name)
            return {"backup_path": f"/home/pi/printer_data/backup/database/{name}"}
        if route == "/server/database/restore":
            if body.get("filename") not in _SIM["backups"]:
                raise Refused(400, "unknown backup")
            return {"restored_tables": ["namespace_store"], "restored_namespaces": ["moonraker"]}
    elif method == "DELETE" and route == "/server/database/backup":
        name = unquote(query.partition("=")[2])
        if name in _SIM["backups"]:
            _SIM["backups"].remove(name)
            return {"backup_path": f"/home/pi/printer_data/backup/database/{name}"}
        raise Refused(400, "unknown backup")
    raise Unsupported(route)
