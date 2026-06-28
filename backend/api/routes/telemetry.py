from flask import Blueprint, jsonify
from core.logger import get_logs
telemetry_bp=Blueprint("telemetry",__name__)

@telemetry_bp.route("/environment",methods=["GET"])
def environment():
    import workers; w=workers._active_worker; d=w.latest if w else {}
    return jsonify({"temperature":d.get("ext_temp",0),"humidity":0})

@telemetry_bp.route("/odometry",methods=["GET"])
def odometry():
    from digital_twin.kinematic_model import kinematic_model
    return jsonify(kinematic_model.get_lifetime_odometry())

@telemetry_bp.route("/logs",methods=["GET"])
def logs(): return jsonify(get_logs())
