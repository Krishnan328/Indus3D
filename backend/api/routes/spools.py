from flask import Blueprint, jsonify, request
from db.models import get_connection

spools_bp = Blueprint("spools", __name__)

@spools_bp.route("", methods=["GET"])
def get_spools():
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT id, name, material, color_hex, starting_weight_g, used_weight_g, is_active, lot_number, manufacturer, material_grade, cert_url FROM spools ORDER BY id DESC")
        cols = [desc[0] for desc in c.description]
        spools = [dict(zip(cols, row)) for row in c.fetchall()]
        conn.close()
        return jsonify(spools)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@spools_bp.route("", methods=["POST"])
def create_spool():
    data = request.json
    name = data.get("name", "New Spool")
    material = data.get("material", "PLA")
    color = data.get("color_hex", "#ffffff")
    weight = float(data.get("starting_weight_g", 1000.0))
    
    lot_number = data.get("lot_number", None)
    manufacturer = data.get("manufacturer", None)
    material_grade = data.get("material_grade", None)
    cert_url = data.get("cert_url", None)
    
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO spools (name, material, color_hex, starting_weight_g, lot_number, manufacturer, material_grade, cert_url) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, material, color, weight, lot_number, manufacturer, material_grade, cert_url))
        new_id = c.lastrowid
        
        # If it's the only spool, make it active
        c.execute("SELECT COUNT(*) FROM spools")
        if c.fetchone()[0] == 1:
            c.execute("UPDATE spools SET is_active = 1 WHERE id = ?", (new_id,))
            
        conn.commit()
        conn.close()
        return jsonify({"id": new_id, "status": "created"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@spools_bp.route("/<int:spool_id>/active", methods=["POST"])
def set_active_spool(spool_id):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE spools SET is_active = 0")
        c.execute("UPDATE spools SET is_active = 1 WHERE id = ?", (spool_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@spools_bp.route("/<int:spool_id>", methods=["DELETE"])
def delete_spool(spool_id):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM spools WHERE id = ?", (spool_id,))
        
        # Ensure there is always one active spool if possible
        c.execute("SELECT COUNT(*) FROM spools WHERE is_active = 1")
        if c.fetchone()[0] == 0:
            c.execute("UPDATE spools SET is_active = 1 WHERE id = (SELECT id FROM spools ORDER BY id DESC LIMIT 1)")
            
        conn.commit()
        conn.close()
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
