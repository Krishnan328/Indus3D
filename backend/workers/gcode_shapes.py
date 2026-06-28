"""
workers/gcode_shapes.py
------------------------
Generates synthetic G-code for sim mode visualisation.
Byte offsets computed identically to how the frontend's
TextEncoder counts them, so file_position aligns perfectly.

Shapes:
  "benchy" — simplified boat hull, cabin, chimney
  "cube"   — 20×20×20mm calibration cube with infill
"""

import math
import io
from config.loader import get_profile


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


# ── Benchy-like boat ──────────────────────────────────────────────────────────

def _benchy_hull(cx, cy, layer, total_layers):
    """Returns list of (x,y) perimeter points for one hull layer."""
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
    cabin_start  = int(layers * 0.45)
    chimney_start= int(layers * 0.80)
    for layer in range(layers):
        z   = round((layer + 1) * layer_h, 3)
        pts = _benchy_hull(cx, cy, layer, layers)
        yield pts[0][0], pts[0][1], z, False
        for x, y in pts[1:]:
            yield x, y, z, True
        yield pts[0][0], pts[0][1], z, True
        if layer >= cabin_start:
            cl = 7.0;  cw = 4.5;  off = -4.5
            cp = [(cx+off-cl,cy-cw),(cx+off+cl,cy-cw),
                  (cx+off+cl,cy+cw),(cx+off-cl,cy+cw)]
            yield cp[0][0], cp[0][1], z, False
            for x, y in cp[1:]:
                yield x, y, z, True
            yield cp[0][0], cp[0][1], z, True
        if layer >= chimney_start:
            chx = cx - 2.0;  chy = cy;  r = 1.8
            yield chx + r, chy, z, False
            for deg in range(0, 361, 30):
                rad = math.radians(deg)
                yield round(chx + r * math.cos(rad), 2), round(chy + r * math.sin(rad), 2), z, True


# ── G-code builder ────────────────────────────────────────────────────────────

def build_gcode(shape: str = "benchy", layers: int = 30) -> tuple:
    """
    Returns (gcode_str, waypoints_list).
    waypoints_list: [{byte, x, y, z, extruding}]
    byte = cumulative bytes AFTER this G1 line (matches TextEncoder in frontend).
    """
    profile   = get_profile()
    bed       = profile.get("bed", {})
    cx        = bed.get("size_x_mm", 235) / 2
    cy        = bed.get("size_y_mm", 235) / 2
    layer_h   = profile.get("print", {}).get("layer_height_mm", 0.2)
    ext_temp  = int(profile.get("hotend",     {}).get("max_temp_c",  260) * 0.83)
    bed_temp  = int(profile.get("bed_heater", {}).get("max_temp_c",  110) * 0.55)

    lines = [
        f"; Indus3D Sim — {shape.upper()}  ({layers} layers)",
        f"; Bed {bed.get('size_x_mm')}×{bed.get('size_y_mm')} mm",
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
    e_per_mm   = 0.045
    prev_x     = cx
    prev_y     = cy

    gen = _benchy_moves(cx, cy, layers, layer_h) if shape == "benchy" \
          else _cube_moves(cx, cy, layers, layer_h)

    for mx, my, mz, extruding in gen:
        if extruding:
            dist = math.sqrt((mx - prev_x)**2 + (my - prev_y)**2)
            e   += dist * e_per_mm
            lines.append(f"G1 X{mx:.3f} Y{my:.3f} Z{mz:.3f} E{e:.4f} F1500")
        else:
            lines.append(f"G1 X{mx:.3f} Y{my:.3f} Z{mz:.3f} F6000")
        prev_x, prev_y = mx, my

    lines += [
        "M104 S0",
        "M140 S0",
        "G28 X Y",
        "M84",
        "; END",
    ]

    # ── Build string and byte-accurate waypoint list ──────────────────────────
    # Every line gets \n, matching how TextEncoder counts in the frontend.
    gcode_str  = "\n".join(lines) + "\n"
    waypoints  = []
    byte       = 0

    import re
    for i, line in enumerate(lines):
        # Match frontend: all lines except last get +\n, last gets nothing
        # But since gcode_str ends with \n (the `+"\n"`), all lines effectively
        # have a newline. We replicate that here.
        line_bytes = len((line + "\n").encode("utf-8"))

        if line.startswith("G1") and "X" in line:
            mx_ = re.search(r"X([0-9.-]+)", line)
            my_ = re.search(r"Y([0-9.-]+)", line)
            mz_ = re.search(r"Z([0-9.-]+)", line)
            me_ = re.search(r"E([0-9.-]+)", line)
            if mx_ and my_ and mz_:
                waypoints.append({
                    "byte":      byte + line_bytes,   # byte AFTER this line
                    "x":         float(mx_.group(1)),
                    "y":         float(my_.group(1)),
                    "z":         float(mz_.group(1)),
                    "extruding": me_ is not None,
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
        print(f"✅ gcode_shapes: {shape} {layers}L — "
              f"{len(wps)} waypoints, {len(gs)} bytes")
    return _cache[key]
