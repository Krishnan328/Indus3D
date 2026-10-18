"""
tools/precompute_benchy_contours.py
------------------------------------
Dev-machine-only. Slices an STL into per-height 2D contours and bakes them
into workers/data/benchy_contours.json for sim mode to use at runtime with
no trimesh/shapely dependency on the Pi.

Usage:
    pip install trimesh shapely --break-system-packages
    python tools/precompute_benchy_contours.py path/to/3DBenchy.stl
    python tools/precompute_benchy_contours.py path/to/model.stl --slices 120 --tolerance 0.15

Why this exists instead of slicing at runtime: the real STL is dense
(a stock 3DBenchy remesh can be 200k+ triangles) and trimesh/shapely are
build-time conveniences, not something you want pulled onto a Raspberry Pi
just to draw a demo shape. Slice once here, ship the ~80KB JSON instead.
"""

import logging
import argparse
import json
import os
import sys

import numpy as np
import trimesh


def slice_stl(stl_path: str, n_slices: int, tolerance: float) -> dict:
    mesh = trimesh.load(stl_path)
    bounds = mesh.bounds
    xmin, ymin, zmin = bounds[0]
    xmax, ymax, zmax = bounds[1]
    cx0 = (xmin + xmax) / 2.0
    cy0 = (ymin + ymax) / 2.0

    footprint = {
        "x": round(xmax - xmin, 2),
        "y": round(ymax - ymin, 2),
        "z": round(zmax - zmin, 2),
    }
    logging.info(f"Loaded {os.path.basename(stl_path)}: "
          f"{footprint['x']}×{footprint['y']}×{footprint['z']}mm, "
          f"{len(mesh.faces)} triangles, watertight={mesh.is_watertight}")

    eps = 0.08
    zs = np.linspace(zmin + eps, zmax - eps, n_slices)

    layers, total_pts, empty = [], 0, 0
    for z in zs:
        sec = mesh.section(plane_origin=[0, 0, float(z)], plane_normal=[0, 0, 1])
        contours = []
        if sec is not None:
            planar, _ = sec.to_2D()
            for poly in planar.polygons_closed:
                if poly.is_empty or poly.exterior is None:
                    continue
                simp = poly.simplify(tolerance, preserve_topology=True)
                if simp.is_empty or simp.exterior is None:
                    continue
                coords = list(simp.exterior.coords)
                if len(coords) > 1 and coords[0] == coords[-1]:
                    coords = coords[:-1]
                if len(coords) < 3:
                    continue
                pts = [[round(px - cx0, 2), round(py - cy0, 2)] for px, py in coords]
                contours.append(pts)
                total_pts += len(pts)
        if not contours:
            empty += 1
        layers.append({"z": round(float(z), 3), "contours": contours})

    if empty:
        logging.info(f"⚠️  {empty}/{n_slices} slices produced no contours — "
              f"check the STL is a single solid body, not multiple parts")
    logging.info(f"Sliced {n_slices} layers, {total_pts} total perimeter points")

    return {
        "source": f"{os.path.basename(stl_path)} (sliced by precompute_benchy_contours.py)",
        "footprint_mm": footprint,
        "simplify_tolerance_mm": tolerance,
        "layers": layers,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stl_path")
    ap.add_argument("--slices", type=int, default=120,
                     help="number of Z cross-sections to bake (default 120)")
    ap.add_argument("--tolerance", type=float, default=0.15,
                     help="Shapely simplify tolerance in mm (default 0.15)")
    ap.add_argument("--out", default=None,
                     help="output path (default: workers/data/benchy_contours.json)")
    args = ap.parse_args()

    if not os.path.isfile(args.stl_path):
        logging.info(f"No such file: {args.stl_path}"); sys.exit(1)

    out_path = args.out or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..",
        "workers", "data", "benchy_contours.json"
    )
    out_path = os.path.normpath(out_path)

    data = slice_stl(args.stl_path, args.slices, args.tolerance)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, separators=(",", ":"))

    size_kb = os.path.getsize(out_path) / 1024
    logging.info(f"Wrote {out_path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
