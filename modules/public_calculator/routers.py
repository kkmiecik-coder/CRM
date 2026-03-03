from flask import render_template, current_app, request, jsonify
from . import public_calculator_bp
from modules.calculator.models import Price
import json
from extensions import db, mail
from .models import PublicSession, CalculatorInquiry
from flask_mail import Message
import sys
from datetime import datetime

@public_calculator_bp.route("/kalkulator", methods=["GET"])
def public_calculator():
    """Publiczny kalkulator z mnożnikiem 1.3 dla klientów detalicznych"""
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
            "width_min": float(p.width_min) if p.width_min else 0,
            "width_max": float(p.width_max) if p.width_max else 999.99,
            "thickness_min": float(p.thickness_min),
            "thickness_max": float(p.thickness_max)
        }
        for p in prices
    ]
    
    # Przekazujemy mnożnik 1.3 dla klientów detalicznych
    return render_template("public_calculator.html",
                         prices_data=json.dumps(prices_data),
                         price_multiplier=1.3,
                         calculator_source="retail")

@public_calculator_bp.route("/kalkulatorb2b", methods=["GET"])
def public_calculator_b2b():
    """Kalkulator B2B z mnożnikiem 1.1 dla partnerów biznesowych"""
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
            "width_min": float(p.width_min) if p.width_min else 0,
            "width_max": float(p.width_max) if p.width_max else 999.99,
            "thickness_min": float(p.thickness_min),
            "thickness_max": float(p.thickness_max)
        }
        for p in prices
    ]
    
    # Przekazujemy mnożnik 1.1 dla partnerów B2B
    return render_template("public_calculator.html",
                         prices_data=json.dumps(prices_data),
                         price_multiplier=1.1,
                         calculator_source="b2b")

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


@public_calculator_bp.route("/send_inquiry", methods=["POST"])
def send_inquiry():
    """Wysyła zapytanie ofertowe z kalkulatora"""
    try:
        data = request.get_json()

        # Walidacja danych
        customer_name = data.get("customer_name", "").strip()
        customer_email = data.get("customer_email", "").strip()
        source = data.get("source", "retail")  # 'b2b' lub 'retail'
        dimensions = data.get("dimensions", {})
        finishing = data.get("finishing")
        finishing_variant = data.get("finishing_variant")
        finishing_color = data.get("finishing_color")
        calculations = data.get("calculations", [])

        if not customer_name:
            return jsonify({"status": "error", "message": "Imię jest wymagane"}), 400
        if not customer_email:
            return jsonify({"status": "error", "message": "Email jest wymagany"}), 400

        # Generuj unikalny numer zapytania
        inquiry_number = CalculatorInquiry.generate_inquiry_number()

        # Zapisz zapytanie w bazie
        inquiry = CalculatorInquiry(
            inquiry_number=inquiry_number,
            customer_name=customer_name,
            customer_email=customer_email,
            source=source,
            dimensions=json.dumps(dimensions),
            finishing=finishing,
            finishing_variant=finishing_variant,
            finishing_color=finishing_color,
            calculations=json.dumps(calculations),
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        db.session.add(inquiry)
        db.session.commit()

        # Przygotuj tytuł maila
        source_label = "B2B" if source == "b2b" else "detalicznego"
        subject_office = f"Zapytanie z kalkulatora {source_label} - {inquiry_number}"
        subject_customer = f"Potwierdzenie zapytania - {inquiry_number}"

        # Przygotuj dane do szablonów
        template_data = {
            "customer_name": customer_name,
            "customer_email": customer_email,
            "inquiry_number": inquiry_number,
            "dimensions": dimensions,
            "finishing": finishing,
            "finishing_variant": finishing_variant,
            "finishing_color": finishing_color,
            "calculations": calculations,
            "source_label": source_label
        }

        # Wyślij mail do biura
        msg_office = Message(
            subject_office,
            sender=current_app.config.get("MAIL_USERNAME"),
            recipients=["biuro@woodpower.pl"],
            reply_to=customer_email
        )
        # Dodaj explicit header Reply-To dla pewności
        msg_office.extra_headers = {"Reply-To": customer_email}
        msg_office.html = render_template(
            "public_calculator/inquiry_office_email.html",
            **template_data
        )
        mail.send(msg_office)

        # Wyślij mail do klienta
        msg_customer = Message(
            subject_customer,
            sender=current_app.config.get("MAIL_USERNAME"),
            recipients=[customer_email]
        )
        msg_customer.html = render_template(
            "public_calculator/inquiry_customer_email.html",
            **template_data
        )
        mail.send(msg_customer)

        print(f"[send_inquiry] Wysłano zapytanie {inquiry_number} od {customer_name} ({customer_email})", file=sys.stderr)

        return jsonify({
            "status": "ok",
            "inquiry_number": inquiry_number,
            "message": "Zapytanie zostało wysłane"
        }), 200

    except Exception as e:
        print(f"[send_inquiry] Błąd: {str(e)}", file=sys.stderr)
        db.session.rollback()
        return jsonify({"status": "error", "message": "Wystąpił błąd podczas wysyłania zapytania"}), 500
