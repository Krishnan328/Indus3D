#!/usr/bin/env python3
"""Command line for the bed sensor hub daemon (stdlib only). Used by the Klipper shell-command
macros, but equally handy from a terminal:

    esp_hub_ctl.py status
    esp_hub_ctl.py reset-crash
    esp_hub_ctl.py set-threshold 2500
    esp_hub_ctl.py shaper-capture --duration 7 --rate 1600 [--analyze [--axis Y] [--apply-to printer.cfg]]

Exit status: 0 success, 1 the hub/daemon reported a failure, 2 the daemon is unreachable.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_URL = os.environ.get("INDUS3D_BED_HUB_URL", "http://127.0.0.1:7127")


def call(url: str, method="GET", body=None, timeout=10.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if method == "POST":
        req.add_header("X-Indus3D-Action", "1")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {"error": f"HTTP {e.code}"}


def describe(s: dict) -> str:
    ch, bed = s.get("chamber") or {}, s.get("bed_accel") or {}
    fmt = lambda v, u: "n/a" if v is None else f"{v}{u}"       # noqa: E731
    d = s.get("daemon", {})
    lines = [
        f"hub {'connected' if s.get('connected') else 'NOT CONNECTED'}"
        + (f" (last data {s['age_s']} s ago)" if s.get("age_s") is not None else " (no data yet)")
        + (f" — {d['last_error']}" if d.get("last_error") else ""),
        f"chamber: {fmt(ch.get('temp_c'), ' °C')}  {fmt(ch.get('humidity_pct'), ' %RH')}  {fmt(ch.get('pressure_hpa'), ' hPa')}",
        f"bed accel: x={bed.get('x_mg')} y={bed.get('y_mg')} z={bed.get('z_mg')} mg   jerk={bed.get('jerk_mg')} mg"
        f"   threshold={s.get('crash_threshold_mg', d.get('crash_threshold_mg'))} mg",
        f"crash latch: {'LATCHED' if s.get('crash_detected') else 'clear'}"
        + (f"  (peak {s['crash_info'].get('peak_jerk_mg')} mg)" if s.get("crash_info") else ""),
    ]
    lc = d.get("last_crash")
    if lc:
        lines.append(f"last crash: {lc.get('jerk_mg')} mg via {lc.get('source')} -> "
                     f"{(lc.get('action') or {}).get('result', 'handling')}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=DEFAULT_URL)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("reset-crash")
    t = sub.add_parser("set-threshold")
    t.add_argument("mg", type=int)
    c = sub.add_parser("shaper-capture")
    c.add_argument("--duration", type=int, default=7)
    c.add_argument("--rate", type=int, default=1600)
    c.add_argument("--baud", type=int, default=None)
    c.add_argument("--analyze", action="store_true", help="run the resonance analysis on the capture")
    c.add_argument("--axis", default="Y", choices=["X", "Y", "Z"])
    c.add_argument("--outdir", default="output")
    c.add_argument("--apply-to", metavar="PRINTER_CFG", help="write the recommended [input_shaper] into this file")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    base = args.url.rstrip("/")

    try:
        if args.cmd == "status":
            code, body = call(f"{base}/telemetry")
            print(describe(body))
            return 0 if body.get("connected") else 1
        if args.cmd == "reset-crash":
            code, body = call(f"{base}/reset_crash", "POST", {})
            print("crash latch cleared" if body.get("ok") else f"reset failed: {body.get('response') or body.get('error')}")
            return 0 if body.get("ok") else 1
        if args.cmd == "set-threshold":
            code, body = call(f"{base}/threshold", "POST", {"mg": args.mg})
            print(f"crash threshold set to {args.mg} mg" if body.get("ok") else f"failed: {body.get('response') or body.get('error')}")
            return 0 if body.get("ok") else 1
        if args.cmd == "shaper-capture":
            body_in = {"duration": args.duration, "rate": args.rate}
            if args.baud:
                body_in["baud"] = args.baud
            print(f"capturing {args.duration} s @ {args.rate} Hz (the hub switches baud for the session) ...", flush=True)
            code, body = call(f"{base}/shaper/capture", "POST", body_in, timeout=args.duration + 40)
            if not body.get("ok"):
                print(f"capture failed: {body.get('error')}")
                return 1
            print(f"captured {body['samples']} samples at {body['rate_hz']} Hz over {body['baud']} baud, "
                  f"loss {body['loss_pct']} % ({body['quality']}) -> {body['csv']}")
            if args.analyze:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import esp_shaper_analyzer as an
                return an.run_analysis(body["csv"], args.axis, args.outdir, apply_to=args.apply_to)
            return 0
    except (urllib.error.URLError, OSError) as e:
        print(f"cannot reach the hub daemon at {base}: {e}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
