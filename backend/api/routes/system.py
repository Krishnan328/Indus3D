"""
api/routes/system.py
---------------------
The System page: thin, validated proxies to Moonraker's host administration APIs
(see ``api/system_host.py`` for the endpoint list and the data shaping).

  GET    /api/v1/system/info                         host, Klipper/Moonraker, MCUs, throttling
  GET    /api/v1/system/services                     systemd services Moonraker may manage
  POST   /api/v1/system/services/<name>/<action>     restart | start | stop   (confirmed; self-stop: confirm_self)
  GET    /api/v1/system/updates                      update_manager status + our own job state
  POST   /api/v1/system/updates/<component>          upgrade one component, ``system`` or ``full`` (confirmed)
  POST   /api/v1/system/updates/<component>/recover  git recovery ({"hard": bool}; confirmed)
  GET    /api/v1/system/backups                      Moonraker database backups
  POST   /api/v1/system/backups                      create a backup ({"filename"?: "x.db"})
  POST   /api/v1/system/backups/<file>/restore       restore (confirmed; Moonraker restarts afterwards)
  DELETE /api/v1/system/backups/<file>               delete (confirmed)
  GET    /api/v1/system/peripherals                  usb / serial / video (+ canbus on request) + usb_link_health
  GET    /api/v1/system/announcements                Moonraker announcements (not dismissed)
  GET    /api/v1/system/alerts                       throttling, pending updates, old Moonraker, announcements, failed components

Conventions: behind the auth gate like every /api route; 502 when Moonraker is unreachable or refuses; 404
``{"unsupported": true}`` when this Moonraker lacks the endpoint; state-changing calls need ``"confirmed": true``
and are refused with 409 while a print is active; in simulator mode everything answers from stub data. Client
input never reaches Moonraker unless it names a service/component/backup Moonraker itself just listed.
POST/DELETE here fall in the strict ``hardware_cmd`` rate-limit category (see api/rate_limiter.py).
"""

import threading
import time
from functools import wraps
from typing import Callable, Optional

from flask import Blueprint, jsonify, request
from urllib.parse import quote

from api import system_host as sh
from config.settings import settings

system_bp = Blueprint("system", __name__)

_ACTIONS = ("restart", "start", "stop")


# ── response helpers ───────────────────────────────────────────────────────────────────────────────────
def _guard(fn):
    """Map the three Moonraker failure modes onto HTTP statuses."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except sh.Unreachable as e:
            return jsonify({"ok": False, "error": str(e), "moonraker": settings.moonraker_url}), 502
        except sh.Unsupported as e:
            return jsonify({"ok": False, "unsupported": True,
                            "error": f"{e} is not available on this Moonraker"}), 404
        except sh.Refused as e:
            return jsonify({"ok": False, "error": str(e), "upstream_status": e.status}), 502
    return wrapper


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _needs(flag: str, message: str):
    return jsonify({"ok": False, "error": message, "needs": flag}), 400


def _confirmed(message: str):
    """None when the body carries ``"confirmed": true``, else the 400 response to return."""
    if _body().get("confirmed") is not True:
        return _needs("confirmed", message)
    return None


def _busy(reason: str, message: str):
    return jsonify({"ok": False, "busy": True, "reason": reason, "error": message}), 409


def _stamp(payload: dict) -> dict:
    payload["ok"] = True
    payload["ts"] = time.time()
    payload["simulated"] = sh.is_sim()
    return payload


# ── info / alerts ──────────────────────────────────────────────────────────────────────────────────────
@system_bp.route("/info", methods=["GET"])
@_guard
def info():
    secs = sh.fetch_sections(["system_info", "proc_stats", "printer_info", "server_info", "mcus"])
    host = sh.host_view(secs)
    mcus = sh.mcus_view(secs["mcus"]["data"]) if secs["mcus"]["ok"] else []
    return jsonify(_stamp({"host": host, "mcus": mcus, "sections": sh.section_status(secs)}))


@system_bp.route("/alerts", methods=["GET"])
@_guard
def alerts():
    secs = sh.fetch_sections(["proc_stats", "server_info", "updates", "announcements"])
    items = sh.compute_alerts(secs)
    counts = {s: sum(1 for a in items if a["severity"] == s) for s in ("critical", "warning", "info")}
    return jsonify(_stamp({"alerts": items, "counts": counts, "sections": sh.section_status(secs),
                           "min_moonraker": sh.min_moonraker()}))


@system_bp.route("/announcements", methods=["GET"])
@_guard
def announcements():
    secs = sh.fetch_sections(["announcements"])
    if secs["announcements"]["unsupported"]:
        raise sh.Unsupported("/server/announcements/list")
    if not secs["announcements"]["ok"]:
        raise sh.Refused(502, secs["announcements"]["error"] or "announcements unavailable")
    return jsonify(_stamp({"announcements": sh.announcements_view(secs["announcements"]["data"])}))


# ── services ───────────────────────────────────────────────────────────────────────────────────────────
def _service_list() -> dict:
    secs = sh.fetch_sections(["system_info"], use_cache=False)
    s = secs["system_info"]
    if s["unsupported"]:
        raise sh.Unsupported("/machine/system_info")
    if not s["ok"]:
        raise sh.Refused(502, s["error"] or "system_info unavailable")
    return sh.services_view(s["data"])


@system_bp.route("/services", methods=["GET"])
@_guard
def services():
    secs = sh.fetch_sections(["system_info"])
    s = secs["system_info"]
    if s["unsupported"]:
        raise sh.Unsupported("/machine/system_info")
    if not s["ok"]:
        raise sh.Refused(502, s["error"] or "system_info unavailable")
    return jsonify(_stamp(sh.services_view(s["data"])))


@system_bp.route("/services/<name>/<action>", methods=["POST"])
@_guard
def service_action(name, action):
    if action not in _ACTIONS:
        return jsonify({"ok": False, "error": f"action must be one of {', '.join(_ACTIONS)}"}), 400
    gate = _confirmed(f"{action} {name}: send \"confirmed\": true")
    if gate:
        return gate
    view = _service_list()
    known = {s["name"]: s for s in view["services"]}
    if name not in known:                                   # only what Moonraker itself reports
        return jsonify({"ok": False, "error": f"unknown service: {name}", "services": sorted(known)}), 404
    if not view["manageable"]:
        return jsonify({"ok": False, "unsupported": True,
                        "error": "Moonraker has no service provider (systemd) so it cannot manage services"}), 404
    svc = known[name]
    if svc["is_self"] and action == "stop" and _body().get("confirm_self") is not True:
        return _needs("confirm_self", f"{name} serves Indus3D itself: stopping it takes this page offline "
                                      "and it cannot be restarted from here. Send \"confirm_self\": true to proceed")
    if svc["print_critical"] and action != "start" and sh.print_active():
        return _busy("print", f"A print is active: {action} of {name} would kill it")
    sh.call("POST", f"/machine/services/{action}", {"service": name})
    sh.reset_cache()
    return jsonify({"ok": True, "service": name, "action": action, "self": svc["is_self"]})


# ── updates ────────────────────────────────────────────────────────────────────────────────────────────
_job_lock = threading.Lock()
_job: dict = {}


def reset_job() -> None:
    with _job_lock:
        _job.clear()


def _spawn(fn: Callable[[], None]) -> None:
    """Run ``fn`` on a daemon thread (tests replace this with a direct call)."""
    threading.Thread(target=fn, daemon=True, name="system-update").start()


_LEGACY_UPDATE = {"full": "full", "system": "system", "klipper": "klipper", "moonraker": "moonraker"}


def _do_upgrade(component: str) -> None:
    """The blocking Moonraker request; Moonraker answers only when the update is over. Prefers the
    API 1.5.0 ``upgrade`` endpoint, falls back to the legacy per-component ones."""
    body = {} if component == "full" else {"name": component}
    try:
        sh.call("POST", "/machine/update/upgrade", body, timeout=sh.LONG_TIMEOUT_S)
    except sh.Unsupported:
        if component in _LEGACY_UPDATE:
            sh.call("POST", f"/machine/update/{_LEGACY_UPDATE[component]}", None, timeout=sh.LONG_TIMEOUT_S)
        else:
            sh.call("POST", "/machine/update/client", {"name": component}, timeout=sh.LONG_TIMEOUT_S)


def _run_job(action: str, component: str, work: Callable[[], None]) -> None:
    try:
        work()
        state, message = "done", f"{action} of {component} finished"
    except sh.Unreachable:
        # Updating Klipper/Moonraker restarts them mid-request: the status endpoint tells the truth.
        state, message = "unknown", "Connection lost (Moonraker probably restarted); check the update status"
    except (sh.Unsupported, sh.Refused) as e:
        state, message = "error", str(e)
    except Exception as e:  # noqa: BLE001
        state, message = "error", str(e)
    with _job_lock:
        _job.update({"state": state, "message": message, "finished": time.time()})
    sh.reset_cache()


def _start_job(action: str, component: str, work: Callable[[], None]) -> Optional[tuple]:
    """Claim the single update slot, or return the 409 response."""
    with _job_lock:
        if _job.get("state") == "running":
            return _busy("update", f"{_job.get('action')} of {_job.get('component')} is still running")
        _job.clear()
        _job.update({"state": "running", "action": action, "component": component, "started": time.time(),
                     "message": None, "finished": None})
    _spawn(lambda: _run_job(action, component, work))
    return None


def _updates_status() -> dict:
    secs = sh.fetch_sections(["updates"], use_cache=False)
    s = secs["updates"]
    if s["unsupported"]:
        raise sh.Unsupported("/machine/update/status")
    if not s["ok"]:
        raise sh.Refused(502, s["error"] or "update status unavailable")
    return s["data"]


@system_bp.route("/updates", methods=["GET"])
@_guard
def updates():
    secs = sh.fetch_sections(["updates"])
    s = secs["updates"]
    if s["unsupported"]:
        raise sh.Unsupported("/machine/update/status")
    if not s["ok"]:
        raise sh.Refused(502, s["error"] or "update status unavailable")
    view = sh.updates_view(s["data"])
    with _job_lock:
        view["job"] = dict(_job) if _job else None
    return jsonify(_stamp(view))


def _update_preflight(component: str):
    """(raw_status, error_response). Validates the name against update_manager's own list."""
    if not sh._COMPONENT.match(component):
        return None, (jsonify({"ok": False, "error": "invalid component name"}), 400)
    raw = _updates_status()
    known = set((raw.get("version_info") or {}).keys())
    if component != "full" and component not in known:
        return None, (jsonify({"ok": False, "error": f"unknown component: {component}",
                               "components": sorted(known)}), 404)
    if sh.print_active():
        return None, _busy("print", "A print is active: updates are refused until it ends")
    if raw.get("busy"):
        return None, _busy("update", "Moonraker is already running an update")
    return raw, None


@system_bp.route("/updates/<component>", methods=["POST"])
@_guard
def update_component(component):
    gate = _confirmed(f"update {component}: send \"confirmed\": true")
    if gate:
        return gate
    _, err = _update_preflight(component)
    if err:
        return err
    err = _start_job("upgrade", component, lambda: _do_upgrade(component))
    if err:
        return err
    return jsonify({"ok": True, "started": True, "component": component}), 202


@system_bp.route("/updates/<component>/recover", methods=["POST"])
@_guard
def recover_component(component):
    gate = _confirmed(f"recover {component}: send \"confirmed\": true")
    if gate:
        return gate
    if component == "full":
        return jsonify({"ok": False, "error": "recover works on one git repository at a time"}), 400
    raw, err = _update_preflight(component)
    if err:
        return err
    if (raw["version_info"].get(component) or {}).get("configured_type") != "git_repo":
        return jsonify({"ok": False, "error": f"{component} is not a git repository: nothing to recover"}), 400
    hard = _body().get("hard") is True
    err = _start_job("recover", component, lambda: sh.call(
        "POST", "/machine/update/recover", {"name": component, "hard": hard}, timeout=sh.LONG_TIMEOUT_S))
    if err:
        return err
    return jsonify({"ok": True, "started": True, "component": component, "hard": hard}), 202


# ── database backups ───────────────────────────────────────────────────────────────────────────────────
def _backup_list() -> list:
    secs = sh.fetch_sections(["backups"], use_cache=False)
    s = secs["backups"]
    if s["unsupported"]:
        raise sh.Unsupported("/server/database/list")
    if not s["ok"]:
        raise sh.Refused(502, s["error"] or "backup list unavailable")
    view = sh.backups_view(s["data"])
    if not view["supported"]:
        raise sh.Unsupported("/server/database/backup")
    return [b["filename"] for b in view["backups"]]


@system_bp.route("/backups", methods=["GET"])
@_guard
def backups():
    secs = sh.fetch_sections(["backups"])
    s = secs["backups"]
    if s["unsupported"]:
        raise sh.Unsupported("/server/database/list")
    if not s["ok"]:
        raise sh.Refused(502, s["error"] or "backup list unavailable")
    view = sh.backups_view(s["data"])
    if not view["supported"]:
        return jsonify(_stamp({"supported": False, "backups": [],
                               "note": "this Moonraker has no database backup API (upgrade Moonraker)"}))
    return jsonify(_stamp(view))


@system_bp.route("/backups", methods=["POST"])
@_guard
def backup_create():
    filename = _body().get("filename")
    if filename is not None and (not isinstance(filename, str) or not sh._BACKUP_NAME.match(filename)):
        return jsonify({"ok": False, "error": "filename must be letters, digits, '_', '-', '.' and end in .db"}), 400
    existing = _backup_list()
    if filename and filename in existing:
        return jsonify({"ok": False, "error": f"{filename} already exists"}), 409
    if sh.print_active():
        return _busy("print", "Moonraker refuses database backups while a print is active")
    res = sh.call("POST", "/server/database/backup", {"filename": filename} if filename else {}, timeout=30)
    sh.reset_cache()
    return jsonify({"ok": True, "backup_path": (res or {}).get("backup_path")}), 201


def _valid_backup(filename: str):
    if not sh._BACKUP_NAME.match(filename):
        return None, (jsonify({"ok": False, "error": "invalid backup name"}), 400)
    if filename not in _backup_list():                      # only a file Moonraker itself listed
        return None, (jsonify({"ok": False, "error": f"unknown backup: {filename}"}), 404)
    return filename, None


@system_bp.route("/backups/<filename>/restore", methods=["POST"])
@_guard
def backup_restore(filename):
    gate = _confirmed(f"restore {filename}: send \"confirmed\": true. Moonraker restarts and the current database is replaced")
    if gate:
        return gate
    _, err = _valid_backup(filename)
    if err:
        return err
    if sh.print_active():
        return _busy("print", "A print is active: restoring the database is refused until it ends")
    try:
        res = sh.call("POST", "/server/database/restore", {"filename": filename}, timeout=60)
    except sh.Unreachable:
        res = {"restarting": True}              # Moonraker restarts straight after a restore
    sh.reset_cache()
    return jsonify({"ok": True, "filename": filename, "result": res})


@system_bp.route("/backups/<filename>", methods=["DELETE"])
@_guard
def backup_delete(filename):
    gate = _confirmed(f"delete {filename}: send \"confirmed\": true")
    if gate:
        return gate
    _, err = _valid_backup(filename)
    if err:
        return err
    sh.call("DELETE", f"/server/database/backup?filename={quote(filename, safe='')}")
    sh.reset_cache()
    return jsonify({"ok": True, "filename": filename})


# ── peripherals ────────────────────────────────────────────────────────────────────────────────────────
def _optional(path: str, key: str) -> dict:
    """One peripheral listing that may be missing or fail without affecting the others."""
    try:
        data = sh.call("GET", path)
        return {"available": True, "items": list((data or {}).get(key) or [])}
    except sh.Unsupported:
        return {"available": False, "unsupported": True, "items": [], "error": "not available on this Moonraker"}
    except sh.Refused as e:
        return {"available": False, "items": [], "error": str(e)}


def _link_health() -> Optional[dict]:
    try:
        from plugins.usb_link_health import monitor
        st = monitor.status()
        return {"kernel_log": st.get("kernel_log"), "suspects": st.get("suspects", []),
                "events": st.get("events", [])[:10], "pending_drops": st.get("pending_drops", [])}
    except Exception:  # noqa: BLE001  plugin disabled or failed to load
        return None


def _recommend_path(dev: dict) -> Optional[str]:
    """The path to put in a Klipper ``serial:`` option: by-id survives re-plugging, by-path is the fallback."""
    return dev.get("path_by_id") or dev.get("path_by_hardware") or dev.get("device_path")


@system_bp.route("/peripherals", methods=["GET"])
@_guard
def peripherals():
    out = {"usb": _optional("/machine/peripherals/usb", "usb_devices"),
           "serial": _optional("/machine/peripherals/serial", "serial_devices"),
           "video": _optional("/machine/peripherals/video", "v4l2_devices")}
    for dev in out["serial"]["items"]:
        dev["recommended_path"] = _recommend_path(dev)
        dev["recommended_kind"] = "by-id" if dev.get("path_by_id") else ("by-path" if dev.get("path_by_hardware") else "device")
    for dev in out["video"]["items"]:
        dev["recommended_path"] = dev.get("path_by_id") or dev.get("path_by_hardware") or dev.get("device_path")
    iface = request.args.get("canbus")
    if iface:
        if not sh._IFACE.match(iface):
            return jsonify({"ok": False, "error": "invalid CAN interface name"}), 400
        out["canbus"] = _optional(f"/machine/peripherals/canbus?interface={quote(iface, safe='')}", "can_uuids")
        out["canbus"]["interface"] = iface
    else:                               # querying a CAN bus can disturb it (see Moonraker docs): opt in only
        out["canbus"] = {"available": True, "queried": False, "items": [],
                         "note": "Not queried. Querying unassigned CAN nodes can put them in bus-off: ask explicitly."}
    out["link_health"] = _link_health()
    return jsonify(_stamp(out))
