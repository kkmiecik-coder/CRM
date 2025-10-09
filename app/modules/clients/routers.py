# modules/clients/routers.py
from flask import Blueprint, render_template, jsonify, request
from .models import Client
from modules.quotes.models import QuoteStatus
from extensions import db
from . import clients_bp
from modules.calculator.models import Quote
import requests
import os
from datetime import date
import re
import sys
import logging

logger = logging.getLogger(__name__)

@clients_bp.route('/')
def clients_home():
    return render_template("clients.html")

@clients_bp.route('/api/clients')
def get_all_clients():
    print("[API] /clients/api/clients zostalo wywolane")
    clients = Client.query.all()
    return jsonify([
        {
            "id": c.id,
            "client_number": c.client_number,
            "client_name": c.client_name,
            "email": c.email,
            "phone": c.phone
        } for c in clients
    ])


@clients_bp.route('/<int:client_id>/data', methods=['GET'])
def get_client_data(client_id):
    client = Client.query.get_or_404(client_id)
    return jsonify({
        "id": client.id,
        "client_number": client.client_number,
        "client_name": client.client_name,
        "client_delivery_name": client.client_delivery_name,
        "email": client.email,
        "phone": client.phone,
        "delivery": {
            "name": client.delivery_name,
            "company": client.delivery_company,
            "address": client.delivery_address,
            "zip": client.delivery_zip,
            "city": client.delivery_city,
            "region": client.delivery_region,
            "country": client.delivery_country,
        },
        "invoice": {
            "name": client.invoice_name,
            "company": client.invoice_company,
            "address": client.invoice_address,
            "zip": client.invoice_zip,
            "city": client.invoice_city,
            "nip": client.invoice_nip,
        },
        "source": client.source,
    })


@clients_bp.route('/<int:client_id>', methods=['PATCH'])
def update_client(client_id):
    client = Client.query.get_or_404(client_id)
    data = request.json

    client.client_name = data.get("client_name")
    client.email = data.get("email")
    client.phone = data.get("phone")
    client.source = data.get("source")

    delivery = data.get("delivery", {})
    client.delivery_name = delivery.get("name")
    client.delivery_company = delivery.get("company")
    client.delivery_address = delivery.get("address")
    client.delivery_zip = delivery.get("zip")
    client.delivery_city = delivery.get("city")
    client.delivery_region = delivery.get("region")
    client.delivery_country = delivery.get("country")

    invoice = data.get("invoice", {})
    client.invoice_name = invoice.get("name")
    client.invoice_company = invoice.get("company")
    client.invoice_address = invoice.get("address")
    client.invoice_zip = invoice.get("zip")
    client.invoice_city = invoice.get("city")
    client.invoice_nip = invoice.get("nip")

    db.session.commit()
    return jsonify({"success": True})

@clients_bp.route('/<int:client_id>/quotes')
def get_client_quotes(client_id):
    from modules.quotes.models import QuoteStatus
    
    quotes = Quote.query.filter_by(client_id=client_id).order_by(Quote.created_at.desc()).all()
    return jsonify([
        {
            "id": q.id,
            "date": q.created_at.strftime('%Y-%m-%d'),
            "status": q.quote_status.name if q.quote_status else "Nieznany",
            "status_color": q.quote_status.color_hex if q.quote_status else "#ccc",
            "total_price": f"{q.total_price:.2f} zł" if q.total_price else "0.00 zł"
        } for q in quotes
    ])

GUS_API_KEY = os.getenv("GUS_API_KEY")
GUS_BASE_URL = "https://wl-api.mf.gov.pl/api/search/nip/"

@clients_bp.route('/api/gus_lookup')
def gus_lookup():
    nip = request.args.get('nip')
    if not nip or not nip.isdigit() or len(nip) != 10:
        return jsonify({"error": "Nieprawidłowy NIP"}), 400

    try:
        today = date.today().isoformat()
        url = f"{GUS_BASE_URL}{nip}?date={today}"
        headers = {"Accept": "application/json"}

        logger.info(f"[GUS Lookup] Wysyłanie zapytania do GUS: {url}")
        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            logger.warning(f"[GUS Lookup] Błąd z GUS: status {response.status_code}")
            return jsonify({"error": "Brak danych"}), 404

        data = response.json()
        subject = data.get("result", {}).get("subject")
        if not subject:
            logger.warning(f"[GUS Lookup] Brak pola 'subject' w odpowiedzi: {data}")
            return jsonify({"error": "Nie znaleziono danych"}), 404

        logger.info(f"[GUS API] Odebrano dane dla NIP {nip}: {subject}")

        full_address = subject.get("residenceAddress") or ""
        zip_match = re.search(r"\d{2}-\d{3}", full_address)
        zip_code = zip_match.group(0) if zip_match else ""
        city = full_address.split()[-1] if full_address else ""

        return jsonify({
            "name": subject.get("name"),
            "company": subject.get("name"),
            "address": subject.get("workingAddress"),
            "zip": zip_code,
            "city": city
        })

    except Exception as e:
        logger.exception("[GUS Lookup Error] Wyjątek podczas przetwarzania")
        return jsonify({"error": "Błąd przetwarzania danych", "details": str(e)}), 500
