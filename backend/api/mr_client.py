"""Thin Moonraker HTTP client shared by the file and queue routes.

``call`` returns the ``result`` member of Moonraker's JSON envelope and turns every failure into one of
three exceptions the routes translate uniformly:

* ``MoonrakerError``      (from moonraker_util) Moonraker unreachable            -> HTTP 502
* ``Unsupported``         the endpoint does not exist on this Moonraker version  -> HTTP 501 + ``unsupported``
* ``MoonrakerHTTPError``  Moonraker understood the request and refused it        -> its own status code

All Moonraker traffic of the file/queue routes goes through ``requests.request`` in this module, which is
the single place tests patch.
"""

from typing import Optional

import requests
from flask import jsonify

from api.moonraker_util import MoonrakerError, url

TIMEOUT_S = 8


class Unsupported(RuntimeError):
    """The Moonraker on the other end has no such endpoint (404 'Not Found' / 405 / 501)."""


class MoonrakerHTTPError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _error_message(res) -> str:
    try:
        body = res.json()
    except ValueError:
        return (getattr(res, "text", "") or "").strip()[:200]
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return str(err.get("message", ""))
    return str(err or "")


def check(res, what: str = ""):
    """Raise the right exception for a non-2xx Moonraker response."""
    if res.ok:
        return
    message = _error_message(res)
    # Tornado answers an unknown route with a bare "Not Found"; Moonraker's own "file/dir does not exist"
    # errors always carry a longer message, so that is how a missing endpoint is told from a missing file.
    if res.status_code in (405, 501) or (res.status_code == 404 and message.strip().lower() in ("", "not found")):
        raise Unsupported(f"{what or 'endpoint'} is not available on this Moonraker")
    raise MoonrakerHTTPError(res.status_code, message or f"Moonraker answered {res.status_code}")


def raw(method: str, path: str, *, timeout: float = TIMEOUT_S, what: str = "", **kw):
    """Perform the request and return the checked ``requests.Response`` (for streams and bodies)."""
    try:
        res = requests.request(method, url(path), timeout=timeout, **kw)
    except requests.RequestException as e:
        raise MoonrakerError(f"Moonraker unreachable: {e}") from e
    check(res, what)
    return res


def call(method: str, path: str, *, timeout: float = TIMEOUT_S, what: str = "", **kw) -> dict:
    res = raw(method, path, timeout=timeout, what=what, **kw)
    try:
        body = res.json()
    except ValueError:
        return {}
    return body.get("result", body) if isinstance(body, dict) else {}


def error_response(e: Exception, context: Optional[str] = None):
    """The uniform JSON error for the exceptions above (anything else is re-raised)."""
    if isinstance(e, MoonrakerError):
        return jsonify({"error": str(e), "code": "moonraker_unreachable"}), 502
    if isinstance(e, Unsupported):
        return jsonify({"error": str(e), "code": "unsupported", "unsupported": True}), 501
    if isinstance(e, MoonrakerHTTPError):
        status = e.status if e.status in (400, 403, 404, 409, 413, 415, 422) else 502
        return jsonify({"error": e.message, "code": "moonraker_refused", "moonraker_status": e.status}), status
    raise e
