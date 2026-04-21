# modules/clients/routers.py
from flask import Blueprint, render_template, jsonify, request, session, current_app
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

    # Parametry paginacji i wyszukiwania
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str).strip()

    # Walidacja parametrów
    if page < 1:
        page = 1
    if per_page < 1 or per_page > 200:
        per_page = 20

    # ✅ NOWE: Filtrowanie per rola
    base_query = Client.query
    filtered_query = get_filtered_clients_query(base_query)

    # Wyszukiwanie jeśli podano frazę
    if search:
        search_filter = (
            (Client.client_number.ilike(f"%{search}%")) |
            (Client.client_name.ilike(f"%{search}%")) |
            (Client.email.ilike(f"%{search}%")) |
            (Client.phone.ilike(f"%{search}%"))
        )
        filtered_query = filtered_query.filter(search_filter)

    # Sortowanie po nazwie klienta
    filtered_query = filtered_query.order_by(Client.client_number.asc())

    # Policz całkowitą liczbę rekordów
    total_count = filtered_query.count()

    # Pobierz stronę wyników
    clients = filtered_query.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        "clients": [
            {
                "id": c.id,
                "client_number": c.client_number,
                "client_name": c.client_name,
                "email": c.email,
                "phone": c.phone,
                "notes": c.notes
            } for c in clients
        ],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
            "total_pages": (total_count + per_page - 1) // per_page
        }
    })


@clients_bp.route('/api/add_client', methods=['POST'])
@require_module_access('clients')
def add_client():
    """Dodaje nowego klienta do bazy danych."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Brak autoryzacji"}), 401

    try:
        data = request.json

        # Walidacja wymaganych pól
        client_name = data.get("client_name", "").strip()
        if not client_name:
            return jsonify({"error": "Nazwa klienta jest wymagana"}), 400

        # Walidacja email (opcjonalny, ale jeśli podany to musi być poprawny)
        email = data.get("email", "").strip() or None
        if email:
            import re
            if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
                return jsonify({"error": "Nieprawidłowy format email"}), 400
            # Sprawdź unikalność emaila
            existing = Client.query.filter_by(email=email).first()
            if existing:
                return jsonify({"error": f"Email {email} jest już przypisany do innego klienta"}), 409

        # Generuj nowy numer klienta (client_number)
        # Format: K-RRRRMMDD-NNN (np. K-20251210-001)
        today = date.today()
        prefix = f"K-{today.strftime('%Y%m%d')}-"

        # Znajdź najwyższy numer z dzisiejszego dnia
        last_client = Client.query.filter(
            Client.client_number.like(f"{prefix}%")
        ).order_by(Client.client_number.desc()).first()

        if last_client and last_client.client_number:
            try:
                last_num = int(last_client.client_number.split('-')[-1])
                new_num = last_num + 1
            except (ValueError, IndexError):
                new_num = 1
        else:
            new_num = 1

        client_number = f"{prefix}{str(new_num).zfill(3)}"

        # Pobierz dane dostawy
        delivery = data.get("delivery", {})
        invoice = data.get("invoice", {})

        # Utwórz nowego klienta
        new_client = Client(
            client_number=client_number,
            client_name=data.get("client_delivery_name", "").strip() or client_name,  # Imię i nazwisko
            email=email,
            phone=data.get("phone", "").strip() or None,
            notes=data.get("notes", "").strip() or None,
            # Adres dostawy
            delivery_name=delivery.get("name", "").strip() or None,
            delivery_company=delivery.get("company", "").strip() or None,
            delivery_address=delivery.get("address", "").strip() or None,
            delivery_zip=delivery.get("zip", "").strip() or None,
            delivery_city=delivery.get("city", "").strip() or None,
            delivery_region=delivery.get("region", "").strip() or None,
            delivery_country=delivery.get("country", "").strip() or None,
            # Dane do faktury
            invoice_name=invoice.get("name", "").strip() or None,
            invoice_company=invoice.get("company", "").strip() or None,
            invoice_address=invoice.get("address", "").strip() or None,
            invoice_zip=invoice.get("zip", "").strip() or None,
            invoice_city=invoice.get("city", "").strip() or None,
            invoice_nip=invoice.get("nip", "").strip() or None,
            # Właściciel
            created_by_user_id=user_id
        )

        # UWAGA: Mapowanie pól (tak jak w update_client):
        # - client_name (z frontu) → to jest "Nazwa klienta" w formularzu
        # - client_delivery_name (z frontu) → to jest "Imię i nazwisko"
        # W bazie: client_number = "Nazwa klienta", client_name = "Imię i nazwisko"
        new_client.client_number = client_name  # "Nazwa klienta" (np. nazwa firmy)

        db.session.add(new_client)
        db.session.commit()

        logger.info(f"[add_client] Utworzono nowego klienta: {client_number} (ID: {new_client.id}) przez user_id={user_id}")

        return jsonify({
            "success": True,
            "client_id": new_client.id,
            "client_number": new_client.client_number
        })

    except Exception as e:
        db.session.rollback()
        logger.exception("[add_client] Błąd podczas tworzenia klienta")
        return jsonify({"error": f"Błąd podczas tworzenia klienta: {str(e)}"}), 500


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
        "email": client.email,
        "phone": client.phone,
        "notes": client.notes,
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
    # Sprawdź czy partner ma dostęp
    user_id = session.get('user_id')
    user = User.query.get(user_id)

    client = Client.query.get_or_404(client_id)

    # Partner może edytować TYLKO swoich klientów
    if user and user.role == 'partner':
        if client.created_by_user_id != user_id:
            return jsonify({"error": "Brak dostępu do tego klienta"}), 403

    try:
        data = request.json

        # Walidacja wymaganych pól
        client_name = data.get("client_name", "").strip()  # To jest "Nazwa klienta" z UI
        client_delivery_name = data.get("client_delivery_name", "").strip()  # To jest "Imię i nazwisko"
        email = data.get("email", "").strip()

        # Fallback: jeśli brak client_name, użyj delivery.name lub client_delivery_name
        if not client_name:
            delivery_data = data.get("delivery", {})
            client_name = delivery_data.get("name", "").strip() or client_delivery_name

        if not client_name:
            return jsonify({"error": "Nazwa klienta jest wymagana"}), 400

        # Email jest opcjonalny, ale jeśli podany to musi być unikalny i poprawny
        if email:
            # Sprawdź czy email jest unikalny (jeśli zmieniony i nie pusty)
            if email != client.email:
                existing_client = Client.query.filter(
                    Client.email == email,
                    Client.id != client_id
                ).first()

                if existing_client:
                    return jsonify({
                        "error": f"Email {email} jest już przypisany do innego klienta",
                        "error_code": "EMAIL_EXISTS",
                        "existing_client": {
                            "id": existing_client.id,
                            "name": existing_client.client_name or existing_client.delivery_name or existing_client.client_number or "Nieznany",
                            "email": existing_client.email
                        }
                    }), 409  # 409 Conflict - lepszy kod dla tego przypadku

        # Aktualizuj dane klienta
        # MAPOWANIE:
        # - client_name (z frontu) → client_number (w bazie) - "Nazwa klienta"
        # - client_delivery_name (z frontu) → client_name (w bazie) - "Imię i nazwisko" w sekcji Dane klienta
        # UWAGA: editClientDeliveryName (nazwa pola w HTML) jest myląca, ale zapisuje do client_name!
        client.client_number = client_name  # "Nazwa klienta" (np. "Wood Power Sp. z o.o.")
        client.client_name = client_delivery_name  # "Imię i nazwisko" (np. "Konrad Kmiecik")
        client.email = email if email else None  # Zapisz NULL jeśli email pusty
        client.phone = data.get("phone", "").strip()
        client.notes = data.get("notes", "").strip() or None
        client.source = data.get("source", "").strip()

        # Aktualizuj adres dostawy
        delivery = data.get("delivery", {})
        client.delivery_name = delivery.get("name", "").strip()
        client.delivery_company = delivery.get("company", "").strip()
        client.delivery_address = delivery.get("address", "").strip()
        client.delivery_zip = delivery.get("zip", "").strip()
        client.delivery_city = delivery.get("city", "").strip()
        client.delivery_region = delivery.get("region", "").strip()
        client.delivery_country = delivery.get("country", "").strip()

        # Aktualizuj dane do faktury
        invoice = data.get("invoice", {})
        client.invoice_name = invoice.get("name", "").strip()
        client.invoice_company = invoice.get("company", "").strip()
        client.invoice_address = invoice.get("address", "").strip()
        client.invoice_zip = invoice.get("zip", "").strip()
        client.invoice_city = invoice.get("city", "").strip()
        client.invoice_nip = invoice.get("nip", "").strip()

        db.session.commit()
        return jsonify({"success": True})

    except Exception as e:
        db.session.rollback()
        logger.exception(f"[update_client] Błąd podczas aktualizacji klienta {client_id}")
        return jsonify({"error": f"Błąd podczas zapisywania danych: {str(e)}"}), 500


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


# Biała Lista VAT (Ministerstwo Finansów) - używana jako fallback drugi w kolejności
MF_WL_BASE_URL = "https://wl-api.mf.gov.pl/api/search/nip/"

# Publiczny testowy klucz GUS (endpoint testowy)
GUS_BIR_TEST_KEY = "abcde12345abcde12345"

# Endpointy produkcyjny i testowy usługi BIR 1.2
GUS_BIR_PROD_URL = "https://wyszukiwarkaregon.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc"
GUS_BIR_TEST_URL = "https://wyszukiwarkaregontest.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc"

# Namespace WCF (WS-Addressing + SOAP) używany przez usługę BIR
GUS_BIR_NAMESPACE = "http://CIS/BIR/PUBL/2014/07"
GUS_BIR_SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
GUS_BIR_WSA_NS = "http://www.w3.org/2005/08/addressing"

CEIDG_BASE_URL = "https://dane.biznes.gov.pl/api/ceidg/v2/firmy"
CEIDG_JWT_TOKEN = "eyJraWQiOiJjZWlkZyIsImFsZyI6IkhTNTEyIn0.eyJnaXZlbl9uYW1lIjoiS29ucmFkIiwicGVzZWwiOiI5OTA0MTUwNzgxOCIsImlhdCI6MTc2Nzc5NTMxMiwiZmFtaWx5X25hbWUiOiJLbWllY2lrIiwiY2xpZW50X2lkIjoiVVNFUi05OTA0MTUwNzgxOC1LT05SQUQtS01JRUNJSyJ9.EL9sUGdXmwLsaaNhXRyHrRZ4hYIuPSwfSx5B7izK16k_IQUdiuZbokUYYbo3tkR_vs1EkouSGxtNh7Lk8Yfygg"

def transform_ceidg_to_gus_format(ceidg_data):
    """
    Przekształca odpowiedź CEIDG API na format zgodny z GUS API.

    Args:
        ceidg_data: Odpowiedź z CEIDG API (dict)

    Returns:
        dict: Dane w formacie zgodnym z GUS API lub None
    """
    if not ceidg_data.get("firma") or len(ceidg_data["firma"]) == 0:
        return None

    firma = ceidg_data["firma"][0]
    wlasciciel = firma.get("wlasciciel", {})
    adres = firma.get("adresDzialalnosci", {})

    # Składanie adresu w format GUS (string)
    adres_parts = []
    if adres.get("ulica"):
        adres_parts.append(adres["ulica"])
        if adres.get("budynek"):
            adres_parts[-1] += f" {adres['budynek']}"
        if adres.get("lokal"):
            adres_parts[-1] += f"/{adres['lokal']}"

    if adres.get("kod") and adres.get("miasto"):
        adres_parts.append(f"{adres['kod']} {adres['miasto']}")

    working_address = ", ".join(adres_parts) if adres_parts else None

    # Nazwa firmy - priorytet: nazwa > imię+nazwisko
    name = firma.get("nazwa")
    if not name and wlasciciel:
        imie = wlasciciel.get("imie", "")
        nazwisko = wlasciciel.get("nazwisko", "")
        name = f"{imie} {nazwisko}".strip()

    # Wyciągnij kod pocztowy i miasto
    zip_code = adres.get("kod", "")
    city = adres.get("miasto", "")

    # Określ województwo - CEIDG już zwraca województwo!
    voivodeship_raw = adres.get("wojewodztwo", "")
    # Zamień na małe litery dla spójności
    voivodeship = voivodeship_raw.lower() if voivodeship_raw else None

    return {
        "name": name,
        "company": name,
        "address": working_address,
        "zip": zip_code,
        "city": city,
        "voivodeship": voivodeship,
        "_source": "CEIDG"
    }


def query_ceidg_api(nip):
    """
    Odpytuje CEIDG API o dane firmy po NIP.

    Args:
        nip: Numer NIP (string, 10 cyfr)

    Returns:
        dict: Dane firmy w formacie GUS lub None
    """
    if not CEIDG_JWT_TOKEN:
        logger.warning("[CEIDG Lookup] Brak tokenu JWT dla CEIDG API")
        return None

    try:
        url = f"{CEIDG_BASE_URL}?nip={nip}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {CEIDG_JWT_TOKEN}"
        }

        logger.info(f"[CEIDG Lookup] Wysyłanie zapytania do CEIDG: {url}")
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 401:
            logger.error("[CEIDG Lookup] Błąd autoryzacji - nieprawidłowy token JWT")
            return None

        if response.status_code == 429:
            logger.warning("[CEIDG Lookup] Przekroczono limit zapytań do CEIDG API")
            return None

        if response.status_code == 204:
            logger.info(f"[CEIDG Lookup] Brak danych dla NIP {nip} (status 204)")
            return None

        if response.status_code != 200:
            logger.warning(f"[CEIDG Lookup] Błąd z CEIDG: status {response.status_code}")
            return None

        data = response.json()
        logger.info(f"[CEIDG API] Odebrano dane dla NIP {nip}")

        # Transformacja do formatu GUS
        transformed = transform_ceidg_to_gus_format(data)
        return transformed

    except requests.exceptions.Timeout:
        logger.error(f"[CEIDG Lookup] Timeout przy zapytaniu dla NIP {nip}")
        return None
    except Exception as e:
        logger.error(f"[CEIDG Lookup] Wyjątek: {e}")
        return None


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

# ============================================================
# Integracja z API GUS REGON BIR 1.2 (SOAP)
# ============================================================


def _get_gus_bir_config():
    """
    Zwraca tuple (klucz_api, url_endpointu) dla usługi BIR 1.2.

    Odczytuje klucz z konfiguracji Flask (config/core.json, pole
    'gus_bir_api_key'). Gdy klucz jest pusty albo równy kluczowi
    testowemu, używa endpointu testowego GUS; w przeciwnym razie
    produkcyjnego.
    """
    api_key = ""
    try:
        api_key = (current_app.config.get("gus_bir_api_key") or "").strip()
    except RuntimeError:
        # Brak kontekstu aplikacji (np. w testach) - użyj klucza testowego
        api_key = ""

    if not api_key or api_key == GUS_BIR_TEST_KEY:
        return GUS_BIR_TEST_KEY, GUS_BIR_TEST_URL

    return api_key, GUS_BIR_PROD_URL


def _build_soap_envelope(action, body_inner_xml, endpoint_url, sid=None):
    """
    Buduje kopertę SOAP 1.2 z WS-Addressing wymaganą przez usługę BIR.

    Args:
        action: nazwa akcji SOAP (np. 'Zaloguj', 'DaneSzukajPodmioty')
        body_inner_xml: zawartość sekcji <soap:Body> (XML fragment)
        endpoint_url: pełny URL endpointu BIR (dla nagłówka <wsa:To>)
        sid: opcjonalny identyfikator sesji (jest dodawany w nagłówku HTTP,
             nie tutaj, ale metoda została zachowana w sygnaturze dla
             spójności wywołań)

    Returns:
        String z gotowym XML SOAP envelope.
    """
    action_url = f"http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/{action}"
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="{soap_ns}" xmlns:wsa="{wsa_ns}" '
        'xmlns:ns="{bir_ns}">'
        '<soap:Header>'
        '<wsa:To>{to}</wsa:To>'
        '<wsa:Action>{action}</wsa:Action>'
        '</soap:Header>'
        '<soap:Body>{body}</soap:Body>'
        '</soap:Envelope>'
    ).format(
        soap_ns=GUS_BIR_SOAP_NS,
        wsa_ns=GUS_BIR_WSA_NS,
        bir_ns=GUS_BIR_NAMESPACE,
        to=endpoint_url,
        action=action_url,
        body=body_inner_xml,
    )
    return envelope


def _soap_request(endpoint_url, action, body_inner_xml, sid=None, timeout=15):
    """
    Wykonuje zapytanie SOAP do usługi BIR 1.2 i zwraca surową odpowiedź (str).
    """
    envelope = _build_soap_envelope(action, body_inner_xml, endpoint_url, sid=sid)
    headers = {
        "Content-Type": 'application/soap+xml; charset=utf-8',
    }
    if sid:
        headers["sid"] = sid

    response = requests.post(endpoint_url, data=envelope.encode("utf-8"),
                             headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def _extract_soap_result(response_text, result_tag):
    """
    Wyciąga zawartość znacznika XML <{result_tag}Result> ze zwróconej
    odpowiedzi SOAP. BIR zwraca najczęściej string z zagnieżdżonym XML
    (np. '<root><dane>...</dane></root>') jako wartość tego znacznika.
    """
    # Używamy wyszukiwania po nazwie lokalnej, bez namespaces
    pattern = r"<[^>]*:?" + re.escape(result_tag) + r"Result[^>]*>(.*?)</[^>]*:?" + re.escape(result_tag) + r"Result>"
    match = re.search(pattern, response_text, flags=re.DOTALL)
    if match:
        return match.group(1)
    return ""


def _unescape_xml(text):
    """Konwertuje encje HTML na znaki XML (BIR zwraca dane jako escaped string)."""
    return (
        text.replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&apos;", "'")
            .replace("&amp;", "&")
    )


def _gus_bir_login(endpoint_url, api_key):
    """Loguje się do usługi BIR i zwraca SID, albo None w razie błędu."""
    body = (
        '<ns:Zaloguj>'
        '<ns:pKluczUzytkownika>{key}</ns:pKluczUzytkownika>'
        '</ns:Zaloguj>'
    ).format(key=api_key)

    logger.info("[GUS BIR] Logowanie do usługi BIR 1.2")
    response_text = _soap_request(endpoint_url, "Zaloguj", body)
    raw = _extract_soap_result(response_text, "Zaloguj")
    sid = raw.strip() if raw else ""

    if not sid:
        logger.warning("[GUS BIR] Logowanie nie zwróciło SID")
        return None

    return sid


def _gus_bir_logout(endpoint_url, sid):
    """Wylogowuje sesję z BIR (best-effort, błędy są tylko logowane)."""
    try:
        body = (
            '<ns:Wyloguj>'
            '<ns:pIdentyfikatorSesji>{sid}</ns:pIdentyfikatorSesji>'
            '</ns:Wyloguj>'
        ).format(sid=sid)
        _soap_request(endpoint_url, "Wyloguj", body, sid=sid, timeout=5)
        logger.info("[GUS BIR] Sesja wylogowana")
    except Exception:
        # Nie przeszkadzamy użytkownikowi - sesja i tak wygaśnie po 60 min
        logger.warning("[GUS BIR] Nie udało się wylogować sesji (pomijam)")


def _gus_bir_search_by_nip(endpoint_url, sid, nip):
    """
    Wywołuje DaneSzukajPodmioty z kryterium NIP.
    Zwraca słownik z polami: Regon, Typ (P/F/LP/LF), SilosID, Nazwa.
    """
    # Zauważ podwójny escape - wewnętrzny XML musi być escape-owany,
    # ponieważ BIR oczekuje go jako string w parametrze
    inner = (
        '&lt;ns1:ParametryWyszukiwania xmlns:ns1="{ns}"&gt;'
        '&lt;ns1:Nip&gt;{nip}&lt;/ns1:Nip&gt;'
        '&lt;/ns1:ParametryWyszukiwania&gt;'
    ).format(ns=GUS_BIR_NAMESPACE, nip=nip)

    body = (
        '<ns:DaneSzukajPodmioty>'
        '<ns:pParametryWyszukiwania>{inner}</ns:pParametryWyszukiwania>'
        '</ns:DaneSzukajPodmioty>'
    ).format(inner=inner)

    logger.info(f"[GUS BIR] Wyszukiwanie podmiotu po NIP {nip}")
    response_text = _soap_request(endpoint_url, "DaneSzukajPodmioty", body, sid=sid)
    raw_result = _extract_soap_result(response_text, "DaneSzukajPodmioty")

    if not raw_result:
        return None

    # Wynik bywa escape'owany w HTML entities - rozpakuj
    unescaped = _unescape_xml(raw_result)

    # Wyciągnij pola z pierwszego <dane>...</dane>
    dane_match = re.search(r"<dane>(.*?)</dane>", unescaped, flags=re.DOTALL)
    if not dane_match:
        return None

    dane_xml = dane_match.group(1)

    def _field(tag):
        m = re.search(r"<{0}>(.*?)</{0}>".format(tag), dane_xml, flags=re.DOTALL)
        return m.group(1).strip() if m else ""

    return {
        "regon": _field("Regon"),
        "nip": _field("Nip"),
        "typ": _field("Typ"),
        "silos_id": _field("SilosID"),
        "nazwa": _field("Nazwa"),
        "wojewodztwo": _field("Wojewodztwo"),
        "powiat": _field("Powiat"),
        "gmina": _field("Gmina"),
        "miejscowosc": _field("Miejscowosc"),
        "kod_pocztowy": _field("KodPocztowy"),
        "ulica": _field("Ulica"),
    }


def _select_bir_report_name(typ, silos_id):
    """
    Wybiera nazwę raportu BIR 1.2 na podstawie Typ i SilosID.

    Typ:
      - 'P'  -> osoba prawna                 -> BIR11OsPrawna
      - 'F'  -> osoba fizyczna               -> zależnie od SilosID:
                SilosID 1 -> BIR11OsFizycznaDzialalnoscCeidg
                SilosID 2 -> BIR11OsFizycznaDzialalnoscRolnicza
                SilosID 3 -> BIR11OsFizycznaDzialalnoscPozostala
                SilosID 4 -> BIR11OsFizycznaDzialalnoscSkreslonaDo20141108
                SilosID 6 (osoba fiz. bez działalności) -> BIR11OsFizycznaDaneOgolne
      - 'LP' -> jednostka lokalna osoby prawnej -> BIR11JednLokalnaOsPrawnej
      - 'LF' -> jednostka lokalna osoby fizycznej -> BIR11JednLokalnaOsFizycznej
    """
    if typ == "P":
        return "BIR11OsPrawna"
    if typ == "LP":
        return "BIR11JednLokalnaOsPrawnej"
    if typ == "LF":
        return "BIR11JednLokalnaOsFizycznej"
    if typ == "F":
        silos_map = {
            "1": "BIR11OsFizycznaDzialalnoscCeidg",
            "2": "BIR11OsFizycznaDzialalnoscRolnicza",
            "3": "BIR11OsFizycznaDzialalnoscPozostala",
            "4": "BIR11OsFizycznaDzialalnoscSkreslonaDo20141108",
            "6": "BIR11OsFizycznaDaneOgolne",
        }
        return silos_map.get(str(silos_id), "BIR11OsFizycznaDzialalnoscCeidg")
    # Domyślnie spróbuj raport dla osoby prawnej
    return "BIR11OsPrawna"


def _gus_bir_full_report(endpoint_url, sid, regon, report_name):
    """
    Wywołuje DanePobierzPelnyRaport i zwraca rozparsowane pola z sekcji
    <dane>. Zwraca słownik nazwa_pola -> wartość (string).
    """
    body = (
        '<ns:DanePobierzPelnyRaport>'
        '<ns:pRegon>{regon}</ns:pRegon>'
        '<ns:pNazwaRaportu>{report}</ns:pNazwaRaportu>'
        '</ns:DanePobierzPelnyRaport>'
    ).format(regon=regon, report=report_name)

    logger.info(f"[GUS BIR] Pobieranie pełnego raportu {report_name} dla REGON {regon}")
    response_text = _soap_request(endpoint_url, "DanePobierzPelnyRaport", body, sid=sid)
    raw_result = _extract_soap_result(response_text, "DanePobierzPelnyRaport")

    if not raw_result:
        return {}

    unescaped = _unescape_xml(raw_result)

    dane_match = re.search(r"<dane>(.*?)</dane>", unescaped, flags=re.DOTALL)
    if not dane_match:
        return {}

    dane_xml = dane_match.group(1)

    # Zbuduj słownik wszystkich pól wewnątrz <dane>
    fields = {}
    for m in re.finditer(r"<([a-zA-Z0-9_]+)>(.*?)</\1>", dane_xml, flags=re.DOTALL):
        fields[m.group(1)] = m.group(2).strip()
    return fields


def _extract_address_from_report(fields, typ):
    """
    Wyciąga ustrukturyzowane pola adresowe z raportu BIR.

    Pola w raporcie są prefiksowane:
      - 'praw_' dla osoby prawnej (BIR11OsPrawna)
      - 'fiz_'  dla osoby fizycznej (BIR11OsFizyczna*)
      - 'lokpraw_' / 'lokfiz_' dla jednostek lokalnych

    Dla każdego prefiksu próbujemy po kolei i bierzemy pierwsze niepuste.
    """
    prefixes = ["praw_", "fiz_", "lokpraw_", "lokfiz_"]

    def pick(suffix):
        for pref in prefixes:
            val = fields.get(pref + suffix)
            if val:
                return val
        return ""

    # Nazwa podmiotu (różne warianty)
    name = (
        pick("nazwa")
        or pick("nazwaSkrocona")
        or (pick("imie1") + " " + pick("nazwisko")).strip()
    )

    street = pick("adSiedzUlica_Nazwa")
    building = pick("adSiedzNumerNieruchomosci")
    apartment = pick("adSiedzNumerLokalu")
    zip_code = pick("adSiedzKodPocztowy")
    city = pick("adSiedzMiejscowosc_Nazwa")
    voivodeship = pick("adSiedzWojewodztwo_Nazwa")
    county = pick("adSiedzPowiat_Nazwa")
    commune = pick("adSiedzGmina_Nazwa")

    # Normalizacja kodu pocztowego (BIR zwraca bez myślnika, np. "00838")
    if zip_code and re.match(r"^\d{5}$", zip_code):
        zip_code = zip_code[:2] + "-" + zip_code[2:]

    # KRS tylko dla osoby prawnej
    krs = fields.get("praw_numerWRejestrzeEwidencji", "") or fields.get("praw_numerwRejestrzeEwidencji", "")

    # REGON
    regon = pick("regon9") or pick("regon14") or fields.get("regon", "")

    # Sklejka dla kompatybilności wstecznej (format zbliżony do MF WL)
    address_parts = []
    if street:
        addr_line = street
        if building:
            addr_line += f" {building}"
            if apartment:
                addr_line += f"/{apartment}"
        address_parts.append(addr_line)
    if zip_code or city:
        address_parts.append(f"{zip_code} {city}".strip())
    address_flat = ", ".join([p for p in address_parts if p])

    return {
        "name": name or None,
        "company": name or None,
        "address": address_flat or None,
        "street": street,
        "building_number": building,
        "apartment_number": apartment,
        "zip": zip_code,
        "city": city,
        "voivodeship": voivodeship.lower() if voivodeship else None,
        "county": county,
        "commune": commune,
        "regon": regon,
        "krs": krs,
        "_source": "GUS_BIR",
    }


def query_gus_bir_api(nip):
    """
    Odpytuje GUS REGON BIR 1.2 SOAP o dane firmy po NIP.

    Returns:
        dict w formacie kompatybilnym z odpowiedzią endpointu /api/gus_lookup,
        albo None gdy brak danych / błąd.
    """
    api_key, endpoint_url = _get_gus_bir_config()

    try:
        sid = _gus_bir_login(endpoint_url, api_key)
        if not sid:
            logger.warning("[GUS BIR] Nie udało się zalogować do usługi BIR")
            return None

        try:
            basic = _gus_bir_search_by_nip(endpoint_url, sid, nip)
            if not basic or not basic.get("regon"):
                logger.info(f"[GUS BIR] Brak podmiotu w rejestrze REGON dla NIP {nip}")
                return None

            report_name = _select_bir_report_name(basic.get("typ"), basic.get("silos_id"))
            fields = _gus_bir_full_report(endpoint_url, sid, basic["regon"], report_name)

            if not fields:
                logger.warning(f"[GUS BIR] Pusta odpowiedź raportu {report_name}")
                return None

            result = _extract_address_from_report(fields, basic.get("typ"))

            # Fallback na nazwę z wyszukiwania, gdy raport nie zwrócił
            if not result.get("name") and basic.get("nazwa"):
                result["name"] = basic["nazwa"]
                result["company"] = basic["nazwa"]

            # Fallback na województwo z wyszukiwania
            if not result.get("voivodeship") and basic.get("wojewodztwo"):
                result["voivodeship"] = basic["wojewodztwo"].lower()

            # Uzupełnij REGON gdy raport go nie zwrócił
            if not result.get("regon"):
                result["regon"] = basic.get("regon", "")

            logger.info(
                f"[GUS BIR] OK dla NIP {nip}: typ={basic.get('typ')}, "
                f"raport={report_name}, miasto={result.get('city')}"
            )
            return result
        finally:
            _gus_bir_logout(endpoint_url, sid)

    except requests.exceptions.Timeout:
        logger.error(f"[GUS BIR] Timeout podczas zapytania dla NIP {nip}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"[GUS BIR] Błąd HTTP dla NIP {nip}: {e}")
        return None
    except Exception:
        logger.exception(f"[GUS BIR] Wyjątek dla NIP {nip}")
        return None


def query_mf_wl_api(nip):
    """
    Odpytuje Białą Listę VAT Ministerstwa Finansów (fallback).
    Zwraca dict w formacie odpowiedzi /api/gus_lookup albo None.
    """
    try:
        today = date.today().isoformat()
        url = f"{MF_WL_BASE_URL}{nip}?date={today}"
        headers = {"Accept": "application/json"}

        logger.info(f"[MF WL] Wysyłanie zapytania do Białej Listy VAT dla NIP {nip}")
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            logger.warning(f"[MF WL] Błąd HTTP: status {response.status_code}")
            return None

        data = response.json()
        subject = data.get("result", {}).get("subject")
        if not subject:
            request_id = data.get("result", {}).get("requestId", "brak")
            logger.info(f"[MF WL] Brak danych dla NIP {nip} (RequestId: {request_id})")
            return None

        full_address = subject.get("workingAddress") or subject.get("residenceAddress") or ""

        zip_match = re.search(r"\d{2}-\d{3}", full_address)
        zip_code = zip_match.group(0) if zip_match else ""

        city = ""
        if zip_code:
            parts = full_address.split(zip_code)
            if len(parts) > 1:
                city = parts[1].strip().strip(',').strip()
        if not city and full_address:
            city = full_address.split()[-1]

        voivodeship = get_voivodeship_from_zipcode(zip_code) if zip_code else None

        return {
            "name": subject.get("name"),
            "company": subject.get("name"),
            "address": subject.get("workingAddress"),
            "zip": zip_code,
            "city": city,
            "voivodeship": voivodeship,
            "_source": "MF_WL",
        }

    except requests.exceptions.Timeout:
        logger.error(f"[MF WL] Timeout dla NIP {nip}")
        return None
    except Exception:
        logger.exception(f"[MF WL] Wyjątek przetwarzania")
        return None


@clients_bp.route('/api/gus_lookup')
@require_module_access('clients')
def gus_lookup():
    """
    Endpoint zwracający dane firmy po NIP.

    Kolejność źródeł:
      1. GUS REGON BIR 1.2 (najbogatsze dane, pola strukturalne)
      2. Biała Lista VAT (MF) - fallback
      3. CEIDG - fallback dla jednoosobowej działalności
    """
    nip = request.args.get('nip')
    if not nip or not nip.isdigit() or len(nip) != 10:
        return jsonify({"error": "Nieprawidłowy NIP"}), 400

    # Priorytet 1: GUS BIR 1.2
    bir_data = query_gus_bir_api(nip)
    if bir_data and bir_data.get("name"):
        return jsonify(bir_data)

    # Priorytet 2: Biała Lista VAT (MF)
    logger.warning(f"[GUS Lookup] Brak danych w GUS BIR dla NIP {nip}, próba MF Białej Listy")
    mf_data = query_mf_wl_api(nip)
    if mf_data and mf_data.get("name"):
        return jsonify(mf_data)

    # Priorytet 3: CEIDG
    logger.warning(f"[GUS Lookup] Brak danych w MF dla NIP {nip}, próba CEIDG")
    ceidg_data = query_ceidg_api(nip)
    if ceidg_data and ceidg_data.get("name"):
        logger.info(f"[GUS Lookup] Dane pobrane z CEIDG dla NIP {nip}")
        return jsonify(ceidg_data)

    logger.warning(f"[GUS Lookup] Brak danych we wszystkich źródłach dla NIP {nip}")
    return jsonify({
        "error": "Nie znaleziono firmy o podanym NIP w rejestrze GUS, MF ani CEIDG. "
                 "NIP może być nieaktywny lub nieprawidłowy."
    }), 404


@clients_bp.route('/search_in_database', methods=['GET'])
@require_module_access('clients')
def search_in_database():
    """
    Endpoint dla Partnera do wyszukiwania klientów w całej bazie.
    Admin/User widzą wszystkich (jak zwykle).
    Partner widzi tylko swoich w liście głównej, ale przez ten endpoint może sprawdzić czy klient istnieje.

    Logika wyświetlania dla cudzych klientów:
    - Jeśli ostatnia wycena > 6 miesięcy LUB brak wyceny → pokaż wszystkie dane
    - Jeśli ostatnia wycena < 6 miesięcy → pokaż tylko nazwę i imię
    """
    from datetime import datetime, timedelta

    term = request.args.get('q', '').strip()
    if len(term) < 3:
        return jsonify([])

    user_id = session.get('user_id')
    if not user_id:
        return jsonify([])

    user = User.query.get(user_id)
    if not user:
        return jsonify([])

    # Wyszukiwanie w całej bazie (dla wszystkich ról)
    base_query = Client.query.filter(
        (Client.client_number.ilike(f"%{term}%")) |
        (Client.client_name.ilike(f"%{term}%")) |
        (Client.email.ilike(f"%{term}%")) |
        (Client.phone.ilike(f"%{term}%")) |
        (Client.invoice_nip.ilike(f"%{term}%"))
    )

    matches = base_query.all()

    results = []
    six_months_ago = datetime.utcnow() - timedelta(days=180)

    for client in matches:
        is_own_client = client.created_by_user_id == user_id

        # Pobierz najnowszą wycenę dla tego klienta
        latest_quote = Quote.query.filter_by(client_id=client.id).order_by(Quote.created_at.desc()).first()

        # Sprawdź czy ostatnia wycena jest młodsza niż 6 miesięcy
        has_recent_quote = latest_quote and latest_quote.created_at > six_months_ago

        # Przygotuj dane klienta
        client_data = {
            "id": client.id,
            "is_own_client": is_own_client,
            "latest_quote_date": latest_quote.created_at.strftime("%Y-%m-%d") if latest_quote else None,
        }

        # Zawsze pokazujemy nazwę i imię
        client_data["client_number"] = client.client_number or ""
        client_data["client_name"] = client.client_name or ""

        # Jeśli to nasz klient LUB cudzy bez świeżej wyceny - pokaż wszystkie dane
        if is_own_client or not has_recent_quote:
            client_data["email"] = client.email or ""
            client_data["phone"] = client.phone or ""
            client_data["invoice_nip"] = client.invoice_nip or ""
            client_data["show_full_data"] = True
        else:
            # Cudzy klient ze świeżą wyceną - ukryj dane kontaktowe
            client_data["email"] = None
            client_data["phone"] = None
            client_data["invoice_nip"] = None
            client_data["show_full_data"] = False

        results.append(client_data)

    return jsonify(results)