from flask import render_template, current_app, request, jsonify
from . import public_calculator_bp
from modules.calculator.models import Price
import json
from extensions import db
from .models import PublicSession
import sys
from datetime import datetime

@public_calculator_bp.route("/kalkulator", methods=["GET"])
def public_calculator():
    # Pobranie danych cennika z bazy
    prices = Price.query.order_by(Price.species, Price.technology, Price.wood_class).all()
    prices_data = [
        {
            "species": p.species,
            "technology": p.technology,
            "wood_class": p.wood_class,
            "price_per_m3": float(p.price_per_m3),
            "length_min": float(p.length_min),
            "length_max": float(p.length_max),
            "thickness_min": float(p.thickness_min),
            "thickness_max": float(p.thickness_max)
        }
        for p in prices
    ]
    return render_template("public_calculator.html", prices_data=json.dumps(prices_data))

@public_calculator_bp.route("/log_session_public", methods=["POST"])
def log_session_public():
    try:
        data_raw = request.data or request.get_data()
        data = json.loads(data_raw)
        print("[log_session_public] Otrzymane dane:", data, file=sys.stderr)

        session = PublicSession(
            inputs=json.dumps(data.get("inputs", {})),
            variant=data.get("variant"),
            finishing=data.get("finishing"),
            color=data.get("color"),
            duration_ms=int(data.get("duration_ms", 0)),
            user_agent=request.headers.get("User-Agent"),
            ip_address=request.remote_addr,
            timestamp=datetime.utcnow()
        )
        db.session.add(session)
        db.session.commit()
        print("[log_session_public] Zapisano sesję ID:", session.id, file=sys.stderr)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("[log_session_public] Błąd:", str(e), file=sys.stderr)
        return jsonify({"status": "error", "message": str(e)}), 500
