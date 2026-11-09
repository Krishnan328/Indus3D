"""Shared fake Moonraker for the route tests."""
import json


class Resp:
    def __init__(self, status=200, body=None, content=b"", headers=None):
        self.status_code = status
        self.ok = status < 400
        self._body = body
        self.content = content
        self.text = json.dumps(body) if body is not None else content.decode("utf-8", "replace")
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def iter_content(self, n=65536):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]

    def close(self):
        pass


def ok(result):
    return Resp(200, {"result": result})


def err(status, message):
    return Resp(status, {"error": {"code": status, "message": message}})


class FakeMR:
    """Records every request; ``routes`` maps (METHOD, path) to a Resp or a callable(kwargs)."""

    def __init__(self, roots=None):
        self.calls = []
        self.routes = {
            ("GET", "/server/files/roots"): ok(roots or [
                {"name": "gcodes", "path": "/g", "permissions": "rw"},
                {"name": "config", "path": "/c", "permissions": "rw"},
                {"name": "config_examples", "path": "/e", "permissions": "r"},
                {"name": "logs", "path": "/l", "permissions": "r"},
                {"name": "database", "path": "/d", "permissions": "rw"},      # reserved: must be hidden
                {"name": "my root", "path": "/x", "permissions": "rw"},        # bad name: must be hidden
                {"name": "shared", "path": "/s", "permissions": "rw"},         # custom but listed: visible
            ]),
        }

    def __call__(self, method, url, **kw):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        self.calls.append((method, path, kw))
        r = self.routes.get((method, path))
        if r is None:
            return err(404, "Not Found")
        return r(kw) if callable(r) else r

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]
