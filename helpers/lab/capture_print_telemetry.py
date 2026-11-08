#!/usr/bin/env python3
"""Record safe GET-only Indus3D telemetry as JSON Lines.

The allow-list is intentionally fixed to health and telemetry endpoints.  This
tool cannot send G-code, alter temperatures, or call Moonraker directly.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

SAFE_PATHS = ("/api/v1/health", "/api/v1/telemetry")


def _password_from_file(path: Path) -> str:
    """Read only the Indus3D password from a mode-0600 EnvironmentFile."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key == "INDUS3D_PASSWORD" and value:
                return value
    except OSError as exc:
        raise ValueError(f"could not read password file: {exc}") from exc
    raise ValueError("INDUS3D_PASSWORD was not found in the password file")


def get_json(url: str, timeout: float, password: str | None = None) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "Indus3D-Lab/1"}
    if password:
        # Indus3D accepts this documented API credential without the tool
        # creating a browser session or persisting a cookie.
        headers["Authorization"] = f"Bearer {password}"
    request = Request(url, method="GET", headers=headers)
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is allow-listed below
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5001", help="Indus3D HTTP origin")
    parser.add_argument("--duration", type=float, required=True, help="capture length in seconds")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between samples (minimum 0.25)")
    parser.add_argument("--timeout", type=float, default=3.0, help="HTTP request timeout in seconds")
    parser.add_argument(
        "--password-file", type=Path,
        help="optional EnvironmentFile containing INDUS3D_PASSWORD (never recorded in output)",
    )
    parser.add_argument("--output", type=Path, required=True, help="JSONL capture output")
    args = parser.parse_args()
    if args.duration <= 0 or args.interval < 0.25 or args.timeout <= 0:
        parser.error("duration and timeout must be positive; interval must be at least 0.25 seconds")
    base = args.base_url.rstrip("/")
    if not (base.startswith("http://") or base.startswith("https://")):
        parser.error("base URL must begin with http:// or https://")
    try:
        password = _password_from_file(args.password_file) if args.password_file else None
    except ValueError as exc:
        parser.error(str(exc))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.duration
    count = 0
    with args.output.open("w", encoding="utf-8") as stream:
        while True:
            start = time.monotonic()
            record: dict = {"schema": "indus3d-lab-telemetry-v1", "captured_at": datetime.now(timezone.utc).isoformat(), "monotonic_seconds": start}
            for path in SAFE_PATHS:
                key = path.rsplit("/", 1)[-1]
                try:
                    record[key] = get_json(base + path, args.timeout, password)
                except (URLError, TimeoutError, ValueError, json.JSONDecodeError, OSError) as exc:
                    record.setdefault("errors", {})[key] = str(exc)
            stream.write(json.dumps(record, separators=(",", ":")) + "\n")
            stream.flush()
            count += 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(args.interval - (time.monotonic() - start), remaining) if time.monotonic() - start < args.interval else 0)
    print(f"wrote {count} samples to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
