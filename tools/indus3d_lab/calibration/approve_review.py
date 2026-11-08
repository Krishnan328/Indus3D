#!/usr/bin/env python3
"""Record a human review; this script cannot upload or execute a test."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

ACKNOWLEDGEMENT = "I reviewed this artifact and completed the physical preflight"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--acknowledge", required=True, help=f'Exact text: "{ACKNOWLEDGEMENT}"')
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.acknowledge != ACKNOWLEDGEMENT or not args.file.name.endswith(".review"):
        raise SystemExit("Approval requires the exact acknowledgement and a retained .review artifact")
    output = args.output or args.file.with_name(args.file.name + ".approval.json")
    payload = {"schema": "indus3d-calibration-review-v1", "artifact": str(args.file),
               "sha256": hashlib.sha256(args.file.read_bytes()).hexdigest(), "reviewer": args.reviewer,
               "approved_at_unix": time.time(), "acknowledgement": ACKNOWLEDGEMENT,
               "scope": "approval record only; no upload, queue, or execution occurred"}
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Recorded manual approval: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
