import sys
import json
from flask import (
    render_template, session, redirect, url_for,
    request, jsonify, current_app
)
from sqlalchemy import text
from extensions import db
from flask import Blueprint, render_template, request, jsonify
from modules.calculator.models import Quote, QuoteItem, QuoteCounter, QuoteLog, Multiplier, User
from modules.clients.models import Client
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError
import logging
import requests
from modules.quotes.models import QuoteStatus
from modules.calculator.models import QuoteItemDetails
from modules.users.decorators import require_module_access

calculator_bp = Blueprint('calculator', __name__, template_folder='templates', static_folder='static')

@calculator_bp.route('/', methods=['GET', 'POST'])
@require_module_access('calculator')
def calculator_home():
    user_email = session.get('user_email')
    user_id = session.get('user_id')
    
    user = User.query.filter_by(email=user_email).first()
    user_role = user.role
    user_multiplier = user.multiplier.multiplier if user.multiplier else 1.0
    user_client_type = user.multiplier.client_type if user.multiplier else None
    
    prices_query = db.session.execute(text("""
        SELECT species, technology, wood_class, thickness_min, thickness_max, 
               length_min, length_max, price_per_m3 
        FROM prices
    """)).fetchall()
    prices_list = [dict(row._mapping) for row in prices_query]
    for row in prices_list:
        for key in ['thickness_min', 'thickness_max', 'length_min', 'length_max', 'price_per_m3']:
            if key in row and row[key] is not None:
                row[key] = float(row[key])
    prices_json = json.dumps(prices_list)
    
    # ✅ NOWE: Konfiguracja flexible partners
    FLEXIBLE_PARTNER_IDS = [14, 15, 16]
    FLEXIBLE_PARTNER_ALLOWED_MULTIPLIERS = {
        14: [5, 6],
        15: [5, 6],
        16: [5, 6],
    }
    
    # Pobieranie mnożników z bazy - filtrowanie per user
    if user_role == 'partner' and user_id in FLEXIBLE_PARTNER_IDS:
        # Flexible partner - pokaż tylko dozwolone mnożniki
        allowed_ids = FLEXIBLE_PARTNER_ALLOWED_MULTIPLIERS.get(user_id, [])
        multipliers_query = Multiplier.query.filter(Multiplier.id.in_(allowed_ids)).all()
    else:
        # Wszyscy inni (admin, user, standardowi partnerzy) - pokaż wszystkie
        multipliers_query = Multiplier.query.all()
    
    multipliers_list = [
        {"id": m.id, "label": m.client_type, "value": m.multiplier}
        for m in multipliers_query
    ]
    multipliers_json = json.dumps(multipliers_list)
    
    # ✅ NOWE: Flaga czy to "flexible partner"
    is_flexible_partner = (user_role == 'partner' and user_id in FLEXIBLE_PARTNER_IDS)
    
    return render_template(
        "calculator.html", 
        user_email=user_email, 
        user_id=user_id, 
        prices_json=prices_json, 
        multipliers_json=multipliers_json, 
        user_role=user_role, 
        user_multiplier=user_multiplier,
        user_client_type=user_client_type,
        is_flexible_partner=is_flexible_partner  # ← NOWY PARAMETR
    )

@calculator_bp.route('/shipping_quote', methods=['POST'])
@require_module_access('calculator')
def shipping_quote():
    current_app.logger.info(">>> shipping_quote: endpoint wywołany")
    
    shipping_params = request.get_json()
    if not shipping_params:
        current_app.logger.error(">>> shipping_quote: Brak danych wysyłki")
        return jsonify({"error": "Brak danych wysyłki"}), 400

    try:
        original_length = float(shipping_params.get("length", 0))
        original_width  = float(shipping_params.get("width", 0))
        original_height = float(shipping_params.get("height", 0))
        weight          = float(shipping_params.get("weight", 0))
    except ValueError:
        current_app.logger.error(">>> shipping_quote: Błędne dane wejściowe")
        return jsonify({"error": "Błędne dane wejściowe"}), 400

    if original_length <= 0 or original_width <= 0 or original_height <= 0 or weight <= 0:
        current_app.logger.error(">>> shipping_quote: Nieprawidlowe wymiary lub waga")
        return jsonify({"error": "Nieprawidlowe wymiary lub waga"}), 400

    # Dodajemy 5 cm do każdego wymiaru i konwertujemy na liczbę całkowitą
    length_int = int(round(original_length + 5))
    width_int  = int(round(original_width + 5))
    height_int = int(round(original_height + 5))

    # Zaokrąglamy wagę do dwóch miejsc po przecinku i formatujemy jako string
    weight_2dec = round(weight, 2)
    weight_str = f"{weight_2dec:.2f}"

    quantity = 1
    senderCountryId   = shipping_params.get("senderCountryId", "1")
    receiverCountryId = shipping_params.get("receiverCountryId", "1")
    senderPostCode    = shipping_params.get("senderPostCode", "01-001")
    receiverPostCode  = shipping_params.get("receiverPostCode", "41-100")

    query_params = {
        "width": width_int,
        "height": height_int,
        "length": length_int,
        "weight": weight_str,
        "quantity": quantity,
        "senderCountryId": senderCountryId,
        "receiverCountryId": receiverCountryId,
        "senderPostCode": senderPostCode,
        "receiverPostCode": receiverPostCode
    }

    glob_config = current_app.config.get("GLOB_KURIER")
    if not glob_config:
        current_app.logger.error(">>> shipping_quote: Brak konfiguracji GlobKURIER")
        return jsonify({"error": "Brak konfiguracji GlobKURIER"}), 500

    # Logowanie do GlobKurier
    auth_url = glob_config["endpoint"] + "/auth/login"
    login_payload = {
        "email": glob_config["login"],
        "password": glob_config["password"]
    }

    headers = {
        "Content-Type": "application/json",
        "accept-language": "en"
    }

    try:
        auth_response = requests.post(auth_url, headers=headers, json=login_payload)
        if auth_response.status_code != 200:
            current_app.logger.error(">>> shipping_quote: Blad logowania, status: %s", auth_response.status_code)
            return jsonify({"error": "Blad logowania do GlobKurier", "status": auth_response.status_code}), 401
        auth_data = auth_response.json()
        token = auth_data.get("token")
        if not token:
            current_app.logger.error(">>> shipping_quote: Nie otrzymano tokena")
            return jsonify({"error": "Nie otrzymano tokena"}), 401
    except Exception as e:
        current_app.logger.error(">>> shipping_quote: Wyjatek podczas logowania: %s", e)
        return jsonify({"error": "Wyjatek podczas logowania: " + str(e)}), 500

    # Wysyłamy zapytanie do /products
    products_url = glob_config["endpoint"] + "/products"
    headers_quote = {
        "accept-language": "en",
        "x-auth-token": token
    }
    try:
        quote_response = requests.get(products_url, headers=headers_quote, params=query_params)
        if quote_response.status_code != 200:
            current_app.logger.error(">>> shipping_quote: Blad pobierania wyceny, status: %s, treść: %s", 
                                       quote_response.status_code, quote_response.text)
            return jsonify({
                "error": "Błąd pobierania wyceny",
                "status": quote_response.status_code,
                "treść": quote_response.text
            }), quote_response.status_code
        quote_data = quote_response.json()
        # Łączymy wszystkie kategorie produktów, upewniając się, że każde zagranie jest listą
        all_products = []
        for category in quote_data:
            items = quote_data[category]
            if isinstance(items, list):
                all_products.extend(items)
            else:
                all_products.append(items)
        if not all_products:
            result = []
        else:
            result = [
                {
                    "carrierName": product.get("carrierName", "Nieznany"),
                    "grossPrice": product.get("grossPrice", ""),
                    "netPrice": round(product.get("grossPrice", 0) / 1.23, 2) if product.get("grossPrice") else "",
                    "carrierLogoLink": product.get("carrierLogoLink", "")
                }
                for product in all_products
            ]
    except Exception as e:
        current_app.logger.error(">>> shipping_quote: Wyjatek podczas pobierania wyceny: %s", e)
        return jsonify({"error": "Wyjatek podczas pobierania wyceny: " + str(e)}), 500
    
    return jsonify(result), 200

logger = logging.getLogger(__name__)

@calculator_bp.route('/api/finishing-prices', methods=['GET'])
@require_module_access('calculator')
def get_finishing_prices():
    """Pobieranie cen wykończeń z bazy danych"""
    try:
        from .models import FinishingTypePrice
        prices = FinishingTypePrice.query.filter_by(is_active=True).all()
        prices_data = []
        for price in prices:
            prices_data.append({
                'id': price.id,
                'name': price.name,
                'price_netto': float(price.price_netto)
            })
        return jsonify(prices_data)
    except Exception as e:
        current_app.logger.error(f"Błąd pobierania cen wykończeń: {str(e)}")
        return jsonify({'error': 'Błąd pobierania cen wykończeń'}), 500

@calculator_bp.route('/save_quote', methods=['POST'])
@require_module_access('calculator')
def save_quote():
    user_email = session.get('user_email')
    if not user_email:
        current_app.logger.warning("[save_quote_backend] Brak sesji uzytkownika.")
        return jsonify({"error": "Brak sesji uzytkownika."}), 401

    try:
        data = request.get_json(force=True)
        
        # Dane kuriera
        courier_name = data.get('courier_name')
        shipping_netto = data.get('shipping_cost_netto', 0.0)
        shipping_brutto = data.get('shipping_cost_brutto', 0.0)

        # Dane grupy cenowej
        quote_client_type = data.get('quote_client_type')
        quote_multiplier = data.get('quote_multiplier', 1.0)

        # Notatka do wyceny
        quote_note = data.get('quote_note', '')
                
        client_id = data.get('client_id')
        products = data.get('products')

        total_price = data.get('total_price', 0.0)

        if not client_id:
            login = data.get('client_login')
            if not login:
                current_app.logger.warning("[save_quote_backend] Brak loginu klienta.")
                return jsonify({"error": "Brak danych klienta."}), 400

            existing_client = Client.query.filter_by(client_number=login).first()
            if existing_client:
                return jsonify({"error": "Klient o takim loginie już istnieje"}), 400

            # ✅ NOWE: Pobierz user_id osoby tworzącej klienta
            user = db.session.execute(
                text("SELECT id FROM users WHERE email = :email"), 
                {'email': user_email}
            ).fetchone()
            current_user_id = user.id if user else None

            client = Client(
                client_number=login,
                client_name=data.get("client_name"),
                email=data.get("client_email"),
                phone=data.get("client_phone"),
                created_by_user_id=current_user_id  # ✅ DODAJ TO
            )
            db.session.add(client)
            db.session.commit()
            client_id = client.id

        if not products:
            return jsonify({"error": "Brakuje produktow."}), 400

        now = datetime.utcnow()
        year = now.year
        month = now.month
        year_short = str(year)[-2:]

        counter = db.session.query(QuoteCounter).filter_by(year=year, month=month).with_for_update().first()
        if not counter:
            counter = QuoteCounter(year=year, month=month, current_number=1)
            db.session.add(counter)
            db.session.flush()
            current_number = 1
        else:
            counter.current_number += 1
            db.session.flush()
            current_number = counter.current_number

        quote_number = f"{current_number:02d}/{month:02d}/{year_short}/W"

        user = db.session.execute(text("SELECT id FROM users WHERE email = :email"), {'email': user_email}).fetchone()
        user_id = user.id if user else None

        # Zapisz wycenę z danymi kuriera, grupy cenowej i notatką
        quote = Quote(
            quote_number=quote_number,
            user_id=user_id,
            client_id=client_id,
            total_price=total_price,
            shipping_cost_netto=shipping_netto,
            shipping_cost_brutto=shipping_brutto,
            courier_name=courier_name,
            quote_client_type=quote_client_type,
            quote_multiplier=quote_multiplier,
            source=data.get('quote_source'),
            notes=quote_note,
            status_id=1,
        )
        
        db.session.add(quote)
        db.session.flush()

        for i, product in enumerate(products):
            variants = product.get('variants', [])

            if not variants:
                current_app.logger.warning(f"[save_quote_backend] Produkt #{i + 1} nie zawiera wariantów – pomijam.")
                continue

            # ✅ POPRAWKA: Pobierz dane wykończenia z poziomu produktu, nie z pierwszego wariantu
            product_quantity = int(product.get('quantity', 1))
            
            # NOWE: Pobierz wykończenie z poziomu produktu
            finishing_type = product.get("finishing_type")
            finishing_variant = product.get("finishing_variant")
            finishing_color = product.get("finishing_color")
            finishing_gloss_level = product.get("finishing_gloss_level")
            finishing_price_netto = product.get("finishing_netto", 0.0)
            finishing_price_brutto = product.get("finishing_brutto", 0.0)
            
            # Zapisz szczegóły wykończenia dla produktu
            item_details = QuoteItemDetails(
                quote_id=quote.id,
                product_index=i + 1,
                finishing_type=finishing_type,
                finishing_variant=finishing_variant,
                finishing_color=finishing_color,
                finishing_gloss_level=finishing_gloss_level,
                finishing_price_netto=finishing_price_netto,
                finishing_price_brutto=finishing_price_brutto,
                quantity=product_quantity
            )
            db.session.add(item_details)

            for j, variant in enumerate(variants):
                # POPRAWKA: Oblicz ceny jednostkowe dzieląc przez quantity
                final_price_netto = variant.get('final_price_netto', 0.0)
                final_price_brutto = variant.get('final_price_brutto', 0.0)
                
                # Podziel przez quantity aby otrzymać ceny jednostkowe
                unit_price_netto = final_price_netto / product_quantity if product_quantity > 0 else 0.0
                unit_price_brutto = final_price_brutto / product_quantity if product_quantity > 0 else 0.0
                
                # ✅ NOWE: Pobierz informację o dostępności wariantu
                is_available = variant.get('is_available', True)
                
                current_app.logger.info(f"[save_quote_backend] Variant #{j + 1}: final_total={final_price_brutto}, quantity={product_quantity}, unit_price={unit_price_brutto}, available={is_available}")
                
                quote_item = QuoteItem(
                    quote_id=quote.id,
                    product_index=i + 1,
                    length_cm=product.get('length'),
                    width_cm=product.get('width'),
                    thickness_cm=product.get('thickness'),
                    volume_m3=variant.get('volume_m3', 0.0),
                    price_per_m3=variant.get('price_per_m3', 0.0),
                    multiplier=variant.get('multiplier', 1.0),
                    price_netto=unit_price_netto,      # CENA JEDNOSTKOWA
                    price_brutto=unit_price_brutto,    # CENA JEDNOSTKOWA
                    is_selected=variant.get('is_selected', False),
                    variant_code=variant.get('variant_code'),
                    # ✅ NOWE: Ustawienie widoczności na stronie klienta na podstawie dostępności
                    show_on_client_page=is_available   # Tylko dostępne warianty widoczne dla klienta
                )
                db.session.add(quote_item)

        log = QuoteLog(
            quote_id=quote.id,
            user_id=user_id,
            description=f"Utworzono wycenę {quote_number} dla grupy cenowej '{quote_client_type or 'brak grupy'}' (mnożnik: {quote_multiplier})"
        )
        db.session.add(log)

        db.session.commit()

        return jsonify({
            "message": "Wycena zapisana.", 
            "quote_number": quote_number,
            "quote_id": quote.id
        })

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("[save_quote] Blad podczas zapisu wyceny:")
        return jsonify({"error": str(e)}), 500


@calculator_bp.route('/search_clients', methods=['GET'])
@require_module_access('calculator')
def search_clients():
    term = request.args.get('q', '').strip()
    if len(term) < 3:
        return jsonify([])

    from modules.clients.models import Client
    from modules.users.models import User

    # ✅ NOWE: Najpierw bazowe query z wyszukiwaniem
    base_query = Client.query.filter(
        (Client.client_number.ilike(f"%{term}%")) |
        (Client.client_name.ilike(f"%{term}%")) |
        (Client.email.ilike(f"%{term}%")) |
        (Client.phone.ilike(f"%{term}%"))
    )

    # ✅ NOWE: Filtrowanie per rola
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user and user.role == 'partner':
            # Partner widzi tylko swoich klientów
            base_query = base_query.filter(Client.created_by_user_id == user_id)

    matches = base_query.all()

    result = []
    for c in matches:
        # POPRAWKA: Priorityzuj client_number (imię i nazwisko) nad client_name
        if c.client_number and c.client_number.strip():
            # Jeśli client_number istnieje, użyj go jako głównej nazwy
            display_name = c.client_number.strip()
            
            # Dodaj client_name w nawiasach jeśli istnieje i się różni
            if (c.client_name and 
                c.client_name.strip() and 
                c.client_name.strip() != c.client_number.strip()):
                display_name = f"{c.client_number.strip()} ({c.client_name.strip()})"
                
        elif c.client_name and c.client_name.strip():
            # Fallback na client_name jeśli client_number jest puste
            display_name = c.client_name.strip()
        else:
            # Ostatnia deska ratunku
            display_name = f"Klient ID: {c.id}"
        
        result.append({
            "id": c.id,
            "name": display_name,
            "email": c.email or "",
            "phone": c.phone or ""
        })

    return jsonify(result)

@calculator_bp.route('/latest_quotes')
@require_module_access('calculator')
def latest_quotes():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify([])

    quotes = (Quote.query
              .filter_by(user_id=user_id)
              .order_by(Quote.created_at.desc())
              .limit(10)  # Tu można zmienić limit wyświetlanych ostatnich wycen w module kalkulatora
              .all())

    result = []
    for q in quotes:
        client = Client.query.get(q.client_id)
        result.append({
            "id": q.id,
            "quote_number": q.quote_number,
            "created_at": q.created_at.strftime("%Y-%m-%d %H:%M"),
            "client_name": client.client_name if client else "-",
            "quote_source": q.source or "-",
            "status": q.quote_status.name if q.quote_status else "-",
            "status_color": q.quote_status.color_hex if q.quote_status else "#ccc",
            "public_token": q.public_token
        })

    return jsonify(result)