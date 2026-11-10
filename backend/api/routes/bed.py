"""
api/routes/bed.py
-----------------
API endpoints for printer bed adaptation, OrcaSlicer profile import,
bed STL 3D model upload/serving, and bed exclusion zone collision checks.
"""

import os
import json
import logging
from pathlib import Path
from flask import Blueprint, jsonify, request, send_file
from werkzeug.utils import secure_filename

from digital_twin.bed_safety import bed_safety, CUSTOM_STL_FILE, _ensure_data_dir
from config.loader import reload, _refresh_module_attrs

bed_bp = Blueprint("bed", __name__)


@bed_bp.route("/config", methods=["GET"])
def get_bed_config():
    """Returns the active bed dimensions, printable area polygon, exclusion zones, and STL model status."""
    return jsonify(bed_safety.to_dict())


@bed_bp.route("/config", methods=["POST"])
def update_bed_config():
    """Manual update of bed geometry, dimensions, origin, and exclusion zones."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        bed_safety._apply_dict(data)
        bed_safety.save()
        reload()
        _refresh_module_attrs()
        return jsonify({
            "status": "ok",
            "message": "Bed configuration updated and saved",
            "bed": bed_safety.to_dict()
        })
    except Exception as e:
        logging.error(f"Error updating bed config: {e}")
        return jsonify({"error": str(e)}), 500


@bed_bp.route("/import-orca", methods=["POST"])
def import_orca_profile():
    """
    Import an OrcaSlicer / PrusaSlicer / BambuStudio machine profile.
    Can accept either a multipart JSON file upload, or a raw JSON body.
    """
    try:
        profile_data = None
        source_name = "OrcaSlicer Import"

        # Check if file upload
        if "file" in request.files:
            uploaded_file = request.files["file"]
            if uploaded_file.filename:
                source_name = uploaded_file.filename
                content = uploaded_file.read().decode("utf-8", errors="replace")
                profile_data = json.loads(content)
        else:
            profile_data = request.get_json(force=True, silent=True)
            if profile_data and "name" in profile_data:
                source_name = profile_data["name"]

        if not profile_data or not isinstance(profile_data, dict):
            return jsonify({"error": "Valid JSON file or JSON payload is required"}), 400

        updated_bed = bed_safety.parse_orca_profile(profile_data, profile_name=source_name)
        reload()
        _refresh_module_attrs()

        return jsonify({
            "status": "ok",
            "message": f"Successfully imported bed profile from {source_name}",
            "bed": updated_bed
        })
    except Exception as e:
        logging.error(f"Error importing OrcaSlicer profile: {e}")
        return jsonify({"error": str(e)}), 500


@bed_bp.route("/upload-stl", methods=["POST"])
def upload_bed_stl():
    """
    Uploads a 3D STL file of the printer bed plate.
    Stored persistently and served to Three.js for true physical bed visualization.
    """
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file part in request"}), 400
        
        file = request.files["file"]
        if not file or not file.filename:
            return jsonify({"error": "No file selected"}), 400

        filename = secure_filename(file.filename)
        if not filename.lower().endswith(".stl"):
            return jsonify({"error": "Only .stl 3D files are supported"}), 400

        _ensure_data_dir()
        file.save(str(CUSTOM_STL_FILE))
        
        bed_safety.has_custom_model = True
        bed_safety.custom_model_filename = filename
        bed_safety.save()
        reload()
        _refresh_module_attrs()

        return jsonify({
            "status": "ok",
            "message": f"Bed 3D model '{filename}' uploaded successfully",
            "bed": bed_safety.to_dict()
        })
    except Exception as e:
        logging.error(f"Error uploading bed STL: {e}")
        return jsonify({"error": str(e)}), 500


@bed_bp.route("/model", methods=["GET"])
def get_bed_stl():
    """Streams the custom bed STL file to the frontend 3D visualizer."""
    if not CUSTOM_STL_FILE.is_file():
        return jsonify({"error": "No custom bed STL model uploaded"}), 404
    
    return send_file(
        str(CUSTOM_STL_FILE),
        mimetype="model/stl",
        as_attachment=False,
        download_name="bed_model.stl"
    )


@bed_bp.route("/model", methods=["DELETE"])
def delete_bed_stl():
    """Removes the custom STL model and reverts to procedural grid."""
    if CUSTOM_STL_FILE.is_file():
        CUSTOM_STL_FILE.unlink(missing_ok=True)
    bed_safety.has_custom_model = False
    bed_safety.custom_model_filename = None
    bed_safety.save()
    reload()
    _refresh_module_attrs()
    return jsonify({
        "status": "ok",
        "message": "Custom bed model removed",
        "bed": bed_safety.to_dict()
    })


@bed_bp.route("/add-corner-screws", methods=["POST"])
def add_corner_screws():
    """Preset to add 4 corner leveling screws / clips keepout zones."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        inset_x = float(data.get("inset_x", 30.0))
        inset_y = float(data.get("inset_y", 30.0))
        radius = float(data.get("radius", 12.0))

        bed_safety.add_corner_screws(inset_x=inset_x, inset_y=inset_y, radius=radius)
        reload()
        _refresh_module_attrs()
        return jsonify({
            "status": "ok",
            "message": "4 corner leveling screw zones added",
            "bed": bed_safety.to_dict()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bed_bp.route("/clear-exclusions", methods=["POST"])
def clear_exclusions():
    """Clears all bed screw and hardware exclusion zones."""
    try:
        bed_safety.clear_exclusion_zones()
        reload()
        _refresh_module_attrs()
        return jsonify({
            "status": "ok",
            "message": "All exclusion zones cleared",
            "bed": bed_safety.to_dict()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bed_bp.route("/reset", methods=["POST"])
def reset_bed():
    """Resets bed settings back to printer.cfg defaults."""
    from config.loader import get_bed
    bed_safety.reset_to_default(get_bed())
    reload()
    _refresh_module_attrs()
    return jsonify({
        "status": "ok",
        "message": "Bed reset to printer.cfg defaults",
        "bed": bed_safety.to_dict()
    })


@bed_bp.route("/validate", methods=["POST"])
def validate_coordinate():
    """Tests if a coordinate is safe or intersects any bed screws / exclusion zones."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        x = float(data.get("x", 0.0))
        y = float(data.get("y", 0.0))
        z = float(data.get("z", 0.0))

        in_zone, zone_idx = bed_safety.is_in_exclusion_zone(x, y, z)
        in_bounds = bed_safety.is_in_printable_bounds(x, y, z)
        safe = in_bounds and not in_zone

        reason = "Safe"
        if not in_bounds:
            reason = "Coordinate is outside printable bed envelope"
        elif in_zone:
            reason = f"Coordinate is inside bed screw / hardware exclusion zone #{zone_idx + 1}"

        return jsonify({
            "safe": safe,
            "in_bounds": in_bounds,
            "in_exclusion_zone": in_zone,
            "zone_index": zone_idx,
            "reason": reason
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
