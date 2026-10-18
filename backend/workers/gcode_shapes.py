"""
workers/gcode_shapes.py
------------------------
Generates synthetic G-code for sim mode visualisation.
Byte offsets computed identically to how the frontend's
TextEncoder counts them, so file_position aligns perfectly.

Shapes:
  "benchy" — 3DBenchy geometry, sliced from data/benchy_contours.json
             (baked offline from an actual 3DBenchy.stl via trimesh —
             see docs/DEVELOPMENT.md for how to regenerate it). Falls back
             to a crude procedural hull outline if that file is missing.
  "cube"   — 20×20×20mm calibration cube with infill
"""

import logging
import math
import os
import json
from config.loader import get_profile

_HERE = os.path.dirname(os.path.abspath(__file__))
_BENCHY_DATA_PATH = os.path.join(_HERE, "data", "benchy_contours.json")


# ── Calibration cube ──────────────────────────────────────────────────────────

def _cube_moves(cx, cy, layers, layer_h):
    """Yields (x, y, z, extruding) for a 20×20mm hollow cube."""
    half   = 10.0
    shells = 2
    for layer in range(layers):
        z = round((layer + 1) * layer_h, 3)
        for shell in range(shells):
            inset = shell * 0.4
            x0 = cx - half + inset;  x1 = cx + half - inset
            y0 = cy - half + inset;  y1 = cy + half - inset
            yield x0, y0, z, False     # travel to corner
            yield x1, y0, z, True
            yield x1, y1, z, True
            yield x0, y1, z, True
            yield x0, y0, z, True      # close
        # Infill on first and last layer only
        if layer == 0 or layer == layers - 1:
            x0 = cx - half + 0.8;  x1 = cx + half - 0.8
            y0 = cy - half + 0.8;  y1 = cy + half - 0.8
            y = y0;  toggle = False
            while y <= y1:
                xa, xb = (x1, x0) if toggle else (x0, x1)
                yield xa, y, z, False
                yield xb, y, z, True
                y = round(y + 0.4, 3);  toggle = not toggle


# ── Real Benchy (sliced from the actual STL) ───────────────────────────────────

_benchy_data_cache = None

def _load_benchy_data():
    global _benchy_data_cache
    if _benchy_data_cache is None:
        with open(_BENCHY_DATA_PATH, "r") as f:
            _benchy_data_cache = json.load(f)
    return _benchy_data_cache


def _synthetic_benchy_hull_fallback(cx, cy, layer, total_layers):
    """Crude sine-wave hull outline. Only used if benchy_contours.json is
    missing — real accuracy requires the baked STL data."""
    hull_l = 28.0;  hull_bow = 11.0
    taper  = 1.0 - (layer / total_layers) * 0.35
    w      = 14.0 * taper
    pts    = []
    steps  = 14
    for i in range(steps + 1):
        t = i / steps
        x = cx - hull_l + t * (hull_l * 2 - hull_bow)
        y = cy + w * math.sin(math.pi * t) * 0.88 + w * 0.12
        pts.append((round(x, 2), round(y, 2)))
    pts.append((round(cx + hull_l - hull_bow * 0.3, 2), round(cy, 2)))
    for i in range(steps, -1, -1):
        t = i / steps
        x = cx - hull_l + t * (hull_l * 2 - hull_bow)
        y = cy - w * math.sin(math.pi * t) * 0.88 - w * 0.12
        pts.append((round(x, 2), round(y, 2)))
    return pts


def _benchy_moves(cx, cy, layers, layer_h):
    """
    Real 3DBenchy toolpath, sliced offline from an actual STL (see
    data/benchy_contours.json). Each baked layer already carries its
    real Z height and one or more closed perimeter contours (hull,
    cabin, portholes, chimney — whatever the mesh actually has at that
    height), so cabin/chimney appear naturally instead of being bolted
    on at hardcoded layer thresholds like the old placeholder did.

    The source mesh was baked at 0.4 mm.  The simulation renders a 0.2 mm
    layer height, so each baked contour is repeated once at the intermediate
    Z plane.  This avoids the disconnected, "layer-shifted" look produced by
    skipping between 0.4–0.8 mm contours while keeping the real STL silhouette.
    `layers` is the number of displayed 0.2 mm simulation layers (240 is the
    full ~48 mm Benchy; lower values are an evenly sampled preview).
    """
    try:
        data = _load_benchy_data()
    except (FileNotFoundError, json.JSONDecodeError):
        logging.info("⚠️  benchy_contours.json missing/invalid — "
              "falling back to placeholder hull shape")
        for layer in range(layers):
            z = round((layer + 1) * layer_h, 3)
            pts = _synthetic_benchy_hull_fallback(cx, cy, layer, layers)
            yield pts[0][0], pts[0][1], z, False
            for x, y in pts[1:]:
                yield x, y, z, True
            yield pts[0][0], pts[0][1], z, True
        return

    baked = data["layers"]
    # A 120-slice source at 0.4 mm becomes a 240-layer print at 0.2 mm.
    n_available = len(baked) * 2
    n_use = max(20, min(layers, n_available))
    if n_use >= n_available:
        selected_indices = list(range(n_available))
    else:
        step = (n_available - 1) / (n_use - 1)
        selected_indices = sorted({round(i * step) for i in range(n_use)})

    for display_index in selected_indices:
        layer = baked[min(display_index // 2, len(baked) - 1)]
        # Never reuse the sparse source Z values: this is a rendered 0.2 mm
        # print, not a wireframe of the offline contour extraction.
        z = round(0.08 + display_index * layer_h, 3)
        for contour in layer["contours"]:
            if len(contour) < 3:
                continue
            x0, y0 = contour[0]
            yield cx + x0, cy + y0, z, False
            for x, y in contour[1:]:
                yield cx + x, cy + y, z, True
            yield cx + x0, cy + y0, z, True   # close the loop


# ── G-code builder ────────────────────────────────────────────────────────────

def build_gcode(shape: str = "benchy", layers: int = 30) -> tuple:
    import math
    profile   = get_profile()
    bed       = profile.get("bed", {})
    cx        = bed.get("size_x_mm", 235) / 2
    cy        = bed.get("size_y_mm", 235) / 2
    layer_h   = profile.get("print", {}).get("layer_height_mm", 0.2)
    ext_temp  = int(profile.get("hotend",     {}).get("max_temp_c",  260) * 0.83)
    bed_temp  = int(profile.get("bed_heater", {}).get("max_temp_c",  110) * 0.55)

    lines = [
        f"; Indus3D Sim - {shape.upper()}  ({layers} layers)",
        f"; Bed {bed.get('size_x_mm')}x{bed.get('size_y_mm')} mm",
        f"; Layer height: {layer_h} mm",
        "G90 ; Absolute",
        "M82 ; Extruder absolute",
        f"M104 S{ext_temp}",
        f"M140 S{bed_temp}",
        f"M109 S{ext_temp}",
        f"M190 S{bed_temp}",
        "G28 ; Home",
        "G1 Z5 F3000",
        f"G1 X{cx:.1f} Y{cy:.1f} F6000",
        "G92 E0",
    ]

    e          = 0.0
    nozzle_d   = profile.get("hotend", {}).get("nozzle_diameter_mm", 0.4)
    filament_d = profile.get("hotend", {}).get("filament_diameter_mm", 1.75)
    line_w     = profile.get("print", {}).get("line_width_mm", nozzle_d)
    bead_area  = max(0.001, (line_w - layer_h) * layer_h + math.pi * (layer_h / 2) ** 2)
    filament_area = math.pi * (filament_d / 2) ** 2
    e_per_mm   = bead_area / filament_area
    prev_x     = cx
    prev_y     = cy

    offsets = [(0, 0, "Benchy")] if shape != "multi_benchy" else [(-40, -20, "Benchy_1"), (0, 30, "Benchy_2"), (40, -10, "Benchy_3")]
    base_shape = "benchy" if "benchy" in shape else shape

    # Pre-declare objects for Exclude Objects
    if shape == "multi_benchy":
        for ox, oy, name in offsets:
            lines.append(f"EXCLUDE_OBJECT_DEFINE NAME={name} CENTER={cx+ox},{cy+oy} POLYGON=[[{cx+ox-20},{cy+oy-20}],[{cx+ox+20},{cy+oy-20}],[{cx+ox+20},{cy+oy+20}],[{cx+ox-20},{cy+oy+20}]]")

    # Generate all moves grouped by layer and object
    # A generator yields x, y, z, extruding. We can group by Z.
    from collections import defaultdict
    obj_layers = {name: defaultdict(list) for _, _, name in offsets}

    for ox, oy, name in offsets:
        gen = _benchy_moves(cx + ox, cy + oy, layers, layer_h) if base_shape == "benchy" else _cube_moves(cx + ox, cy + oy, layers, layer_h)
        for mx, my, mz, extruding in gen:
            obj_layers[name][mz].append((mx, my, mz, extruding))

    # Gather all unique Z heights sorted
    all_z = sorted(set(z for name in obj_layers for z in obj_layers[name]))

    for z in all_z:
        for ox, oy, name in offsets:
            pts = obj_layers[name].get(z, [])
            if not pts: continue

            if shape == "multi_benchy":
                lines.append(f"EXCLUDE_OBJECT_START NAME={name}")

            for mx, my, mz, extruding in pts:
                if extruding:
                    dist = math.sqrt((mx - prev_x)**2 + (my - prev_y)**2)
                    e   += dist * e_per_mm
                    lines.append(f"G1 X{mx:.3f} Y{my:.3f} Z{mz:.3f} E{e:.4f} F1500")
                else:
                    lines.append(f"G1 X{mx:.3f} Y{my:.3f} Z{mz:.3f} F6000")
                prev_x, prev_y = mx, my

            if shape == "multi_benchy":
                lines.append(f"EXCLUDE_OBJECT_END NAME={name}")

    lines += [
        "M104 S0",
        "M140 S0",
        "G28 X Y",
        "M84",
        "; END",
    ]

    gcode_str  = "\n".join(lines) + "\n"
    waypoints  = []
    byte       = 0

    import re
    current_obj = None
    for i, line in enumerate(lines):
        if line.startswith("EXCLUDE_OBJECT_START"):
            current_obj = line.split("NAME=")[1].strip()
        elif line.startswith("EXCLUDE_OBJECT_END"):
            current_obj = None

        line_bytes = len((line + "\n").encode("utf-8"))

        if line.startswith("G1") and "X" in line:
            mx_ = re.search(r"X([0-9.-]+)", line)
            my_ = re.search(r"Y([0-9.-]+)", line)
            mz_ = re.search(r"Z([0-9.-]+)", line)
            me_ = re.search(r"E([0-9.-]+)", line)
            if mx_ and my_ and mz_:
                waypoints.append({
                    "byte":      byte + line_bytes,
                    "x":         float(mx_.group(1)),
                    "y":         float(my_.group(1)),
                    "z":         float(mz_.group(1)),
                    "extruding": me_ is not None,
                    "object":    current_obj,
                })
        byte += line_bytes

    return gcode_str, waypoints


# ── Cache ─────────────────────────────────────────────────────────────────────
_cache: dict = {}

def get_shape_gcode(shape: str = "benchy", layers: int = 30) -> tuple:
    key = f"{shape}_{layers}"
    if key not in _cache:
        _cache[key] = build_gcode(shape, layers)
        gs, wps = _cache[key]
        logging.info(f"✅ gcode_shapes: {shape} {layers}L — "
              f"{len(wps)} waypoints, {len(gs)} bytes")
    return _cache[key]
