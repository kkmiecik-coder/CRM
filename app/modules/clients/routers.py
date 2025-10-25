# modules/clients/routers.py
from flask import Blueprint, render_template, jsonify, request, session
from .models import Client
from modules.quotes.models import QuoteStatus
from extensions import db
from . import clients_bp
from modules.calculator.models import Quote
from modules.users.models import User
from modules.users.decorators import require_module_access  # ✅ NOWY IMPORT
import requests
import os
from datetime import date
import re
import sys
import logging

logger = logging.getLogger(__name__)

# ✅ NOWA FUNKCJA - Filtrowanie per rola
def get_filtered_clients_query(base_query):
    """
    Filtruje klientów w zależności od roli użytkownika.
    Partner widzi TYLKO swoich klientów.
    
    Args:
        base_query: SQLAlchemy Query object (np. Client.query)
    
    Returns:
        Query object - gotowy do .all(), .paginate(), itp.
    """
    user_id = session.get('user_id')
    if not user_id:
        return base_query.filter(Client.id == -1)
    
    user = User.query.get(user_id)
    if not user:
        return base_query.filter(Client.id == -1)
    
    # Partner widzi TYLKO swoich klientów
    if user.role == 'partner':
        return base_query.filter(Client.created_by_user_id == user_id)
    
    # Admin i User widzą wszystkich
    return base_query


@clients_bp.route('/')
@require_module_access('clients')
def clients_home():
    return render_template("clients.html")


@clients_bp.route('/api/clients')
@require_module_access('clients')
def get_all_clients():
    print("[API] /clients/api/clients zostalo wywolane")
    
    # ✅ NOWE: Filtrowanie per rola
    base_query = Client.query
    clients = get_filtered_clients_query(base_query).all()
    
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
@require_module_access('clients')
def get_client_data(client_id):
    # ✅ NOWE: Sprawdź czy partner ma dostęp do tego klienta
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    client = Client.query.get_or_404(client_id)
    
    # Partner może widzieć TYLKO swoich klientów
    if user and user.role == 'partner':
        if client.created_by_user_id != user_id:
            return jsonify({"error": "Brak dostępu do tego klienta"}), 403
    
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
@require_module_access('clients')
def update_client(client_id):
    # ✅ NOWE: Sprawdź czy partner ma dostęp
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    client = Client.query.get_or_404(client_id)
    
    # Partner może edytować TYLKO swoich klientów
    if user and user.role == 'partner':
        if client.created_by_user_id != user_id:
            return jsonify({"error": "Brak dostępu do tego klienta"}), 403
    
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
@require_module_access('clients')
def get_client_quotes(client_id):
    from modules.quotes.models import QuoteStatus
    
    # ✅ NOWE: Sprawdź czy partner ma dostęp
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    client = Client.query.get_or_404(client_id)
    
    # Partner może widzieć wyceny TYLKO swoich klientów
    if user and user.role == 'partner':
        if client.created_by_user_id != user_id:
            return jsonify({"error": "Brak dostępu do tego klienta"}), 403
    
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

def get_voivodeship_from_zipcode(zip_code):
    """
    Mapuje kod pocztowy na województwo
    Bazuje na pierwszych 2 cyfrach kodu pocztowego
    """
    if not zip_code or len(zip_code) < 2:
        return None
    
    # Wyciągnij pierwsze 2 cyfry
    prefix = zip_code[:2]
    
    # Mapowanie przedziałów kodów pocztowych na województwa
    voivodeship_map = {
        # Dolnośląskie: 50-59
        **{str(i).zfill(2): 'dolnośląskie' for i in range(50, 60)},
        
        # Kujawsko-pomorskie: 85-87
        **{str(i).zfill(2): 'kujawsko-pomorskie' for i in range(85, 88)},
        
        # Lubelskie: 20-24
        **{str(i).zfill(2): 'lubelskie' for i in range(20, 25)},
        
        # Lubuskie: 65-68
        **{str(i).zfill(2): 'lubuskie' for i in range(65, 69)},
        
        # Łódzkie: 90-99
        **{str(i).zfill(2): 'łódzkie' for i in range(90, 100)},
        
        # Małopolskie: 30-34
        **{str(i).zfill(2): 'małopolskie' for i in range(30, 35)},
        
        # Mazowieckie: 00-09, 95-97 (Warszawa + okolice)
        **{str(i).zfill(2): 'mazowieckie' for i in range(0, 10)},
        **{str(i).zfill(2): 'mazowieckie' for i in range(95, 98)},
        **{str(i).zfill(2): 'mazowieckie' for i in [5, 6, 7, 8, 9]},  # 05-09
        
        # Opolskie: 45-49
        **{str(i).zfill(2): 'opolskie' for i in range(45, 50)},
        
        # Podkarpackie: 35-39
        **{str(i).zfill(2): 'podkarpackie' for i in range(35, 40)},
        
        # Podlaskie: 15-19
        **{str(i).zfill(2): 'podlaskie' for i in range(15, 20)},
        
        # Pomorskie: 80-84
        **{str(i).zfill(2): 'pomorskie' for i in range(80, 85)},
        
        # Śląskie: 40-44
        **{str(i).zfill(2): 'śląskie' for i in range(40, 45)},
        
        # Świętokrzyskie: 25-29
        **{str(i).zfill(2): 'świętokrzyskie' for i in range(25, 30)},
        
        # Warmińsko-mazurskie: 10-14
        **{str(i).zfill(2): 'warmińsko-mazurskie' for i in range(10, 15)},
        
        # Wielkopolskie: 60-64
        **{str(i).zfill(2): 'wielkopolskie' for i in range(60, 65)},
        
        # Zachodniopomorskie: 70-79
        **{str(i).zfill(2): 'zachodniopomorskie' for i in range(70, 80)},
    }
    
    return voivodeship_map.get(prefix, None)

@clients_bp.route('/api/gus_lookup')
@require_module_access('clients')
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

        # POPRAWKA: Użyj workingAddress (adres siedziby firmy) zamiast residenceAddress
        # residenceAddress jest dla osób fizycznych i często jest None dla firm
        full_address = subject.get("workingAddress") or subject.get("residenceAddress") or ""
        
        logger.info(f"[GUS Lookup] Przetwarzanie adresu: {full_address}")
        
        # Wyciągnij kod pocztowy z adresu
        zip_match = re.search(r"\d{2}-\d{3}", full_address)
        zip_code = zip_match.group(0) if zip_match else ""
        
        # Wyciągnij miasto (ostatnie słowo po kodzie pocztowym)
        city = ""
        if zip_code:
            # Wszystko po kodzie pocztowym to prawdopodobnie miasto
            parts = full_address.split(zip_code)
            if len(parts) > 1:
                city = parts[1].strip().strip(',').strip()
        
        if not city:
            # Fallback: ostatnie słowo
            city = full_address.split()[-1] if full_address else ""
        
        # Określ województwo na podstawie kodu pocztowego
        voivodeship = get_voivodeship_from_zipcode(zip_code) if zip_code else None
        
        logger.info(f"[GUS Lookup] Przetworzone dane: zip={zip_code}, city={city}, voivodeship={voivodeship}")

        return jsonify({
            "name": subject.get("name"),
            "company": subject.get("name"),
            "address": subject.get("workingAddress"),
            "zip": zip_code,
            "city": city,
            "voivodeship": voivodeship
        })

    except Exception as e:
        logger.exception("[GUS Lookup Error] Wyjątek podczas przetwarzania")
        return jsonify({"error": "Błąd przetwarzania danych", "details": str(e)}), 500