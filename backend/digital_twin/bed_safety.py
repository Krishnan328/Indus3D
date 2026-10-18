"""
digital_twin/bed_safety.py
--------------------------
Printer bed geometry, OrcaSlicer profile parser, and collision safety engine.

Protects against:
1. Nozzle crashes into physical bed screws, bed clamps/clips, purge buckets, or wipe brushes.
2. Dangerous negative Z-offset runaway commands from closed-loop quality controller.
3. Out-of-bounds toolhead moves and manual jog commands.
4. Provides 2D polygon & 3D mesh metadata for Three.js visualizer.
"""

import os
import json
import math
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

_HERE = Path(__file__).parent.parent
DATA_BED_DIR = _HERE / "data" / "bed"
CUSTOM_BED_FILE = DATA_BED_DIR / "custom_bed.json"
CUSTOM_STL_FILE = DATA_BED_DIR / "bed_model.stl"


def _ensure_data_dir():
    DATA_BED_DIR.mkdir(parents=True, exist_ok=True)


class BedSafetyEngine:
    def __init__(self):
        # Default Cartesian 300x300x400
        self.size_x_mm: float = 300.0
        self.size_y_mm: float = 300.0
        self.size_z_mm: float = 400.0
        self.origin_center: bool = False
        self.min_x: float = 0.0
        self.max_x: float = 300.0
        self.min_y: float = 0.0
        self.max_y: float = 300.0
        self.min_z: float = 0.0
        self.max_z: float = 400.0

        # Printable area polygon (list of [x, y] coordinates in order)
        self.printable_area: List[List[float]] = [
            [0.0, 0.0],
            [300.0, 0.0],
            [300.0, 300.0],
            [0.0, 300.0],
        ]

        # List of exclusion polygons: [ [ [x, y], [x, y], ... ], ... ]
        # Each polygon represents a physical obstacle like bed leveling screws, clamps, clips.
        self.bed_exclude_area: List[List[List[float]]] = []

        # Clearance height (mm): above this Z height, exclusion zones are safe for rapid transit
        self.clearance_height_mm: float = 10.0

        # Custom 3D STL model state
        self.has_custom_model: bool = False
        self.custom_model_filename: Optional[str] = None
        self.source_name: str = "default"

        # Load persisted custom bed if present
        self.load()

    def load(self) -> bool:
        """Loads custom bed settings from JSON storage if exists."""
        try:
            if CUSTOM_BED_FILE.is_file():
                with open(CUSTOM_BED_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._apply_dict(data)
                self.has_custom_model = CUSTOM_STL_FILE.is_file()
                if self.has_custom_model:
                    self.custom_model_filename = CUSTOM_STL_FILE.name
                logging.info(f"✅ Bed safety engine loaded custom bed ({self.source_name}, {self.size_x_mm}x{self.size_y_mm}x{self.size_z_mm}mm, {len(self.bed_exclude_area)} exclusion zones)")
                return True
        except Exception as e:
            logging.warning(f"⚠️ Failed to load custom bed config: {e}")
        return False

    def save(self):
        """Persists custom bed settings to disk."""
        _ensure_data_dir()
        payload = self.to_dict()
        with open(CUSTOM_BED_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        logging.info("💾 Saved custom bed geometry and exclusion zones to disk.")

    def reset_to_default(self, bed_cfg: Optional[Dict[str, Any]] = None):
        """Resets to printer.cfg or default rectangular bed."""
        if bed_cfg:
            sx = float(bed_cfg.get("size_x_mm", 300.0))
            sy = float(bed_cfg.get("size_y_mm", 300.0))
            sz = float(bed_cfg.get("size_z_mm", 400.0))
            orig_c = bool(bed_cfg.get("origin_center", False))
        else:
            sx, sy, sz, orig_c = 300.0, 300.0, 400.0, False

        self.size_x_mm = sx
        self.size_y_mm = sy
        self.size_z_mm = sz
        self.origin_center = orig_c

        if orig_c:
            hx, hy = sx / 2.0, sy / 2.0
            self.min_x, self.max_x = -hx, hx
            self.min_y, self.max_y = -hy, hy
        else:
            self.min_x, self.max_x = 0.0, sx
            self.min_y, self.max_y = 0.0, sy

        self.min_z, self.max_z = 0.0, sz
        self.printable_area = [
            [self.min_x, self.min_y],
            [self.max_x, self.min_y],
            [self.max_x, self.max_y],
            [self.min_x, self.max_y],
        ]
        self.bed_exclude_area = []
        self.source_name = "printer.cfg"
        if CUSTOM_BED_FILE.is_file():
            CUSTOM_BED_FILE.unlink(missing_ok=True)
        if CUSTOM_STL_FILE.is_file():
            CUSTOM_STL_FILE.unlink(missing_ok=True)
        self.has_custom_model = False
        self.custom_model_filename = None

    def _apply_dict(self, data: Dict[str, Any]):
        self.size_x_mm = float(data.get("size_x_mm", self.size_x_mm))
        self.size_y_mm = float(data.get("size_y_mm", self.size_y_mm))
        self.size_z_mm = float(data.get("size_z_mm", self.size_z_mm))
        self.origin_center = bool(data.get("origin_center", self.origin_center))
        self.min_x = float(data.get("min_x", 0.0))
        self.max_x = float(data.get("max_x", self.size_x_mm))
        self.min_y = float(data.get("min_y", 0.0))
        self.max_y = float(data.get("max_y", self.size_y_mm))
        self.min_z = float(data.get("min_z", 0.0))
        self.max_z = float(data.get("max_z", self.size_z_mm))
        self.clearance_height_mm = float(data.get("clearance_height_mm", 10.0))
        self.source_name = str(data.get("source_name", "custom"))

        pa = data.get("printable_area")
        if pa and isinstance(pa, list):
            self.printable_area = [[float(p[0]), float(p[1])] for p in pa if len(p) >= 2]

        ex = data.get("bed_exclude_area")
        if ex and isinstance(ex, list):
            self.bed_exclude_area = []
            for poly in ex:
                if isinstance(poly, list) and len(poly) >= 3:
                    self.bed_exclude_area.append([[float(p[0]), float(p[1])] for p in poly if len(p) >= 2])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "size_x_mm": round(self.size_x_mm, 2),
            "size_y_mm": round(self.size_y_mm, 2),
            "size_z_mm": round(self.size_z_mm, 2),
            "origin_center": self.origin_center,
            "min_x": round(self.min_x, 2),
            "max_x": round(self.max_x, 2),
            "min_y": round(self.min_y, 2),
            "max_y": round(self.max_y, 2),
            "min_z": round(self.min_z, 2),
            "max_z": round(self.max_z, 2),
            "printable_area": self.printable_area,
            "bed_exclude_area": self.bed_exclude_area,
            "clearance_height_mm": round(self.clearance_height_mm, 2),
            "has_custom_model": CUSTOM_STL_FILE.is_file(),
            "custom_model_filename": self.custom_model_filename if CUSTOM_STL_FILE.is_file() else None,
            "source_name": self.source_name,
        }

    # ── OrcaSlicer / PrusaSlicer / BambuStudio Parser ─────────────────────────
    def parse_orca_profile(self, data: Dict[str, Any], profile_name: str = "OrcaSlicer Profile") -> Dict[str, Any]:
        """
        Extracts printable area polygon, height, bed exclusion areas, and custom models
        from an OrcaSlicer machine profile JSON.
        """
        # 1. Printable Area
        raw_pa = data.get("printable_area")
        parsed_pa = self._parse_coordinate_polygon(raw_pa)

        # 2. Printable Height
        raw_height = data.get("printable_height", data.get("max_print_height", 250.0))
        try:
            height = float(raw_height)
        except (ValueError, TypeError):
            height = 250.0

        # 3. Exclusion Areas (bed screws, clips, wipe towers, purge lines)
        # Orca uses "bed_exclude_area" (list or comma string) and "color_bed_exclude_area"
        exclude_polys = []
        for key in ("bed_exclude_area", "color_bed_exclude_area"):
            raw_ex = data.get(key)
            if raw_ex:
                polys = self._parse_exclusion_polygons(raw_ex)
                exclude_polys.extend(polys)

        if not parsed_pa:
            # Fallback to standard 220x220 if missing
            parsed_pa = [[0.0, 0.0], [220.0, 0.0], [220.0, 220.0], [0.0, 220.0]]

        # Compute bounding dimensions
        xs = [p[0] for p in parsed_pa]
        ys = [p[1] for p in parsed_pa]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        size_x = max_x - min_x
        size_y = max_y - min_y

        # Detect centered origin (e.g. delta or center 0,0)
        origin_center = (abs(min_x + max_x) < 5.0 and abs(min_y + max_y) < 5.0)

        # Update engine state
        self.size_x_mm = round(size_x, 1)
        self.size_y_mm = round(size_y, 1)
        self.size_z_mm = round(height, 1)
        self.origin_center = origin_center
        self.min_x = round(min_x, 1)
        self.max_x = round(max_x, 1)
        self.min_y = round(min_y, 1)
        self.max_y = round(max_y, 1)
        self.min_z = 0.0
        self.max_z = round(height, 1)
        self.printable_area = parsed_pa
        self.bed_exclude_area = exclude_polys
        self.source_name = f"OrcaSlicer ({profile_name})"

        # Check for model reference
        custom_model_ref = data.get("bed_custom_model") or data.get("bed_model")
        if custom_model_ref and isinstance(custom_model_ref, str) and os.path.isfile(custom_model_ref):
            # If the user has a local file on this machine, we can copy it into our storage
            try:
                _ensure_data_dir()
                with open(custom_model_ref, "rb") as src_f, open(CUSTOM_STL_FILE, "wb") as dst_f:
                    dst_f.write(src_f.read())
                self.has_custom_model = True
                self.custom_model_filename = os.path.basename(custom_model_ref)
            except Exception as e:
                logging.warning(f"Could not copy custom bed model from path {custom_model_ref}: {e}")

        self.save()
        return self.to_dict()

    @staticmethod
    def _parse_coordinate_polygon(raw_coords) -> List[List[float]]:
        """Parses coordinate pairs like '0x0', '250x0' or '0x0,250x0,...' or [[0,0], [250,0]]"""
        if not raw_coords:
            return []
        
        pairs = []
        if isinstance(raw_coords, str):
            # e.g. "0x0,250x0,250x250,0x250"
            tokens = [t.strip() for t in raw_coords.split(",") if t.strip()]
            for token in tokens:
                if "x" in token.lower():
                    parts = token.lower().split("x")
                    try:
                        pairs.append([float(parts[0]), float(parts[1])])
                    except ValueError:
                        pass
        elif isinstance(raw_coords, list):
            for item in raw_coords:
                if isinstance(item, str) and "x" in item.lower():
                    parts = item.lower().split("x")
                    try:
                        pairs.append([float(parts[0]), float(parts[1])])
                    except ValueError:
                        pass
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    try:
                        pairs.append([float(item[0]), float(item[1])])
                    except (ValueError, TypeError):
                        pass
        return pairs

    def _parse_exclusion_polygons(self, raw_data) -> List[List[List[float]]]:
        """
        Parses exclusion areas into a list of polygons.
        OrcaSlicer bed_exclude_area is either a single polygon or a list of coordinates
        delimited by '0x0' resets or multiple comma-separated items.
        """
        coords = self._parse_coordinate_polygon(raw_data)
        if not coords:
            return []

        # If it contains 3 or more points and doesn't have internal resets
        if len(coords) >= 3:
            # Check if it starts/ends with same point (closed)
            if coords[0] == coords[-1]:
                coords = coords[:-1]
            if len(coords) >= 3:
                return [coords]
        return []

    # ── Manual Presets & Screw Zone Setup ─────────────────────────────────────
    def add_corner_screws(self, inset_x: float = 30.0, inset_y: float = 30.0, radius: float = 12.0):
        """Adds 4 standard leveling screw keepout zones (e.g. for Ender 3, Neptune, Prusa, Voron)."""
        x_left = self.min_x + inset_x
        x_right = self.max_x - inset_x
        y_front = self.min_y + inset_y
        y_back = self.max_y - inset_y

        screws = [
            (x_left, y_front),   # Front Left
            (x_right, y_front),  # Front Right
            (x_right, y_back),   # Back Right
            (x_left, y_back),    # Back Left
        ]

        for cx, cy in screws:
            self.add_exclusion_box(cx - radius, cy - radius, cx + radius, cy + radius)

        self.save()

    def add_exclusion_box(self, x1: float, y1: float, x2: float, y2: float):
        """Adds a rectangular exclusion zone (box)."""
        min_x, max_x = min(x1, x2), max(x1, x2)
        min_y, max_y = min(y1, y2), max(y1, y2)
        poly = [
            [round(min_x, 2), round(min_y, 2)],
            [round(max_x, 2), round(min_y, 2)],
            [round(max_x, 2), round(max_y, 2)],
            [round(min_x, 2), round(max_y, 2)],
        ]
        self.bed_exclude_area.append(poly)

    def clear_exclusion_zones(self):
        self.bed_exclude_area = []
        self.save()

    # ── Point-in-Polygon & Trajectory Intersection Math ────────────────────────
    @staticmethod
    def point_in_polygon(x: float, y: float, poly: List[List[float]]) -> bool:
        """Ray-casting algorithm to test if point (x, y) is inside polygon."""
        if len(poly) < 3:
            return False
        inside = False
        n = len(poly)
        j = n - 1
        for i in range(n):
            xi, yi = poly[i][0], poly[i][1]
            xj, yj = poly[j][0], poly[j][1]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
                inside = not inside
            j = i
        return inside

    def is_in_exclusion_zone(self, x: float, y: float, z: Optional[float] = None) -> Tuple[bool, Optional[int]]:
        """
        Returns (True, zone_index) if (x, y) is inside any bed screw or hardware exclusion zone.
        If z is specified and z >= clearance_height_mm, returns (False, None) (safe overfly).
        """
        if z is not None and z >= self.clearance_height_mm:
            return False, None

        for idx, poly in enumerate(self.bed_exclude_area):
            if self.point_in_polygon(x, y, poly):
                return True, idx
        return False, None

    def is_in_printable_bounds(self, x: float, y: float, z: Optional[float] = None) -> bool:
        """Verifies (x, y, z) is within the machine's printable envelope."""
        if z is not None and (z < -0.5 or z > self.size_z_mm + 5.0):
            return False
        
        # Check polygon printable area if defined
        if len(self.printable_area) >= 3:
            if not self.point_in_polygon(x, y, self.printable_area):
                return False
        else:
            if not (self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y):
                return False
        return True

    def validate_move(self, from_x: float, from_y: float, from_z: float,
                      to_x: float, to_y: float, to_z: float) -> Tuple[bool, str]:
        """
        Validates a linear move from (from_xyz) to (to_xyz).
        Returns (is_safe, error_reason).
        """
        # 1. Bounds check target
        if not self.is_in_printable_bounds(to_x, to_y, to_z):
            return False, f"Target ({to_x:.1f}, {to_y:.1f}, {to_z:.1f}) exceeds printable bed envelope"

        # 2. Check if target or intermediate path lands in an exclusion zone at low Z
        min_move_z = min(from_z, to_z)
        if min_move_z < self.clearance_height_mm and self.bed_exclude_area:
            # Check target directly
            in_zone, z_idx = self.is_in_exclusion_zone(to_x, to_y, min_move_z)
            if in_zone:
                return False, f"Move target ({to_x:.1f}, {to_y:.1f}) is inside bed screw/exclusion zone #{z_idx + 1}"

            # Check discrete steps along trajectory for intersection with screw zones
            dx = to_x - from_x
            dy = to_y - from_y
            dist = math.hypot(dx, dy)
            if dist > 5.0:
                steps = max(2, int(dist / 5.0)) # check every 5mm
                for step in range(1, steps):
                    frac = step / float(steps)
                    cx = from_x + dx * frac
                    cy = from_y + dy * frac
                    cz = from_z + (to_z - from_z) * frac
                    in_zone_inter, z_idx_inter = self.is_in_exclusion_zone(cx, cy, cz)
                    if in_zone_inter:
                        return False, f"Move path crosses bed screw/exclusion zone #{z_idx_inter + 1} at ({cx:.1f}, {cy:.1f}, Z={cz:.1f})"

        return True, "Safe"

    def clamp_z_offset(self, current_total_offset: float, desired_adjustment: float,
                       x: Optional[float] = None, y: Optional[float] = None) -> float:
        """
        Safety guardrail for QualityController SET_GCODE_OFFSET.
        Prevents cumulative negative Z runaway crashes into the bed plate or screws.
        Hard limits: total offset clamped to [-0.25mm, +0.50mm].
        If current position (x, y) is over an exclusion zone, forbid ANY downward adjustment.
        """
        # If over a bed screw or clip, strictly forbid lowering Z
        if x is not None and y is not None:
            in_zone, _ = self.is_in_exclusion_zone(x, y, 1.0)
            if in_zone and desired_adjustment < 0:
                logging.warning(f"🛡️ BedSafety blocked negative Z adjustment ({desired_adjustment:.3f}mm) while nozzle is over exclusion zone at ({x:.1f}, {y:.1f})")
                return 0.0

        projected = current_total_offset + desired_adjustment
        # Hard limits
        min_allowed = -0.25  # Max 0.25mm downward squish
        max_allowed = +0.50  # Max 0.50mm upward clearance

        if projected < min_allowed:
            clamped_adj = min_allowed - current_total_offset
            return round(clamped_adj, 3)
        elif projected > max_allowed:
            clamped_adj = max_allowed - current_total_offset
            return round(clamped_adj, 3)
        return round(desired_adjustment, 3)


# Global singleton instance
bed_safety = BedSafetyEngine()
