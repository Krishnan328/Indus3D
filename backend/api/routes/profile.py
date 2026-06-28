"""
api/routes/profile.py
----------------------
Exposes the parsed printer profile to the frontend and provides
a reload endpoint so changes to printer.cfg take effect without restart.
"""

from flask import Blueprint, jsonify

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/", methods=["GET"])
def get_profile():
    """Full profile dict — frontend reads this on mount."""
    from config.loader import get_profile
    return jsonify(get_profile())


@profile_bp.route("/reload", methods=["POST"])
def reload_profile():
    """
    Re-parse printer.cfg from Moonraker (or local file).
    Call this after editing printer.cfg so Indus3D picks up the changes
    without a full restart.
    """
    try:
        from config.loader import reload, _refresh_module_attrs, get_profile
        reload()
        _refresh_module_attrs()
        p = get_profile()
        return jsonify({
            "status":  "ok",
            "source":  p.get("_source", "unknown"),
            "printer": p.get("printer_name", "unknown"),
            "bed":     p.get("bed", {}),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@profile_bp.route("/summary", methods=["GET"])
def summary():
    """Human-readable summary string — useful for debug."""
    from config.loader import get_profile
    from config.cfg_parser import profile_summary
    return profile_summary(get_profile()), 200, {"Content-Type": "text/plain"}
