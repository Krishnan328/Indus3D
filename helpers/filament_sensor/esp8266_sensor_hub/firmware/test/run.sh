#!/usr/bin/env bash
# Compile and run the host-side firmware logic tests (needs only g++).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
g++ -std=c++11 -Wall -Wextra -I"$HERE/stubs" -I"$HERE/../include" \
    "$HERE/test_logic.cpp" "$HERE/../src/crash_detector.cpp" -o "$OUT/test_logic"
"$OUT/test_logic"
