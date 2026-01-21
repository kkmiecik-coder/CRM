import sys
import json
from flask import (
    render_template, session, redirect, url_for,
    request, jsonify, current_app
)
from sqlalchemy import text
from extensions import db
from flask import Blueprint, render_template, request, jsonify
from modules.calculator.models import Quote, QuoteItem, QuoteCounter, QuoteLog, Multiplier, User, QuoteSource
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
    FLEXIBLE_PARTNER_IDS = [14, 15]
    FLEXIBLE_PARTNER_ALLOWED_MULTIPLIERS = {
        14: [5, 6],
        15: [5, 6],
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
    import time
    
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

    # ===== NOWE: Konfiguracja timeout i retry =====
    REQUEST_TIMEOUT = 30  # 30 sekund timeout dla każdego requesta
    MAX_RETRIES = 2  # Maksymalnie 2 próby (czyli 3 wywołania: pierwsze + 2 retry)
    RETRY_DELAY = 2  # 2 sekundy przerwy między próbami
    RETRYABLE_STATUS_CODES = [502, 503, 504]  # Kody błędów, które warto retry'ować

    def make_request_with_retry(request_func, request_name, *args, **kwargs):
        """
        Wykonuje request z mechanizmem retry dla błędów tymczasowych
        """
        for attempt in range(MAX_RETRIES + 1):
            try:
                # Dodaj timeout do kwargs jeśli nie ma
                if 'timeout' not in kwargs:
                    kwargs['timeout'] = REQUEST_TIMEOUT
                
                current_app.logger.info(f">>> shipping_quote: {request_name} - próba {attempt + 1}/{MAX_RETRIES + 1}")
                response = request_func(*args, **kwargs)
                
                # Jeśli status jest OK lub nie jest retry'owalny, zwróć response
                if response.status_code == 200 or response.status_code not in RETRYABLE_STATUS_CODES:
                    return response
                
                # Jeśli to błąd retry'owalny i nie jest ostatnia próba, poczekaj i spróbuj ponownie
                if attempt < MAX_RETRIES:
                    current_app.logger.warning(
                        f">>> shipping_quote: {request_name} - błąd {response.status_code}, "
                        f"retry za {RETRY_DELAY}s..."
                    )
                    time.sleep(RETRY_DELAY)
                    continue
                
                # Ostatnia próba też się nie powiodła
                return response
                
            except requests.exceptions.Timeout:
                current_app.logger.error(f">>> shipping_quote: {request_name} - timeout po {REQUEST_TIMEOUT}s")
                if attempt < MAX_RETRIES:
                    current_app.logger.warning(f">>> shipping_quote: {request_name} - retry za {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)
                    continue
                else:
                    raise
            except requests.exceptions.RequestException as e:
                current_app.logger.error(f">>> shipping_quote: {request_name} - wyjątek: {e}")
                if attempt < MAX_RETRIES:
                    current_app.logger.warning(f">>> shipping_quote: {request_name} - retry za {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)
                    continue
                else:
                    raise
        
        return None

    # ===== Logowanie do GlobKurier z retry =====
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
        auth_response = make_request_with_retry(
            requests.post,
            "auth/login",
            auth_url,
            headers=headers,
            json=login_payload
        )
        
        if not auth_response:
            current_app.logger.error(">>> shipping_quote: Nie otrzymano odpowiedzi po wszystkich próbach logowania")
            return jsonify({
                "error": "Serwis kurierski chwilowo niedostępny. Spróbuj ponownie za chwilę."
            }), 503
        
        if auth_response.status_code != 200:
            current_app.logger.error(">>> shipping_quote: Blad logowania, status: %s", auth_response.status_code)
            return jsonify({
                "error": "Błąd logowania do serwisu kurierskiego",
                "status": auth_response.status_code
            }), 401
        
        auth_data = auth_response.json()
        token = auth_data.get("token")
        if not token:
            current_app.logger.error(">>> shipping_quote: Nie otrzymano tokena")
            return jsonify({"error": "Nie otrzymano tokena autoryzacyjnego"}), 401
            
    except requests.exceptions.Timeout:
        current_app.logger.error(">>> shipping_quote: Timeout podczas logowania po wszystkich próbach")
        return jsonify({
            "error": "Serwis kurierski nie odpowiada. Spróbuj ponownie za chwilę."
        }), 504
    except Exception as e:
        current_app.logger.error(">>> shipping_quote: Wyjatek podczas logowania: %s", e)
        return jsonify({
            "error": "Błąd połączenia z serwisem kurierskim"
        }), 500

    # ===== Wysyłamy zapytanie do /products z retry =====
    products_url = glob_config["endpoint"] + "/products"
    headers_quote = {
        "accept-language": "en",
        "x-auth-token": token
    }
    
    try:
        quote_response = make_request_with_retry(
            requests.get,
            "products",
            products_url,
            headers=headers_quote,
            params=query_params
        )
        
        if not quote_response:
            current_app.logger.error(">>> shipping_quote: Nie otrzymano odpowiedzi po wszystkich próbach wyceny")
            return jsonify({
                "error": "Serwis kurierski chwilowo niedostępny. Spróbuj ponownie za chwilę."
            }), 503
        
        if quote_response.status_code != 200:
            current_app.logger.error(
                ">>> shipping_quote: Blad pobierania wyceny, status: %s, treść: %s", 
                quote_response.status_code,
                quote_response.text[:500]  # Loguj tylko pierwsze 500 znaków
            )
            return jsonify({
                "error": "Nie udało się pobrać wyceny wysyłki",
                "status": quote_response.status_code
            }), quote_response.status_code
        
        quote_data = quote_response.json()
        
        # Łączymy wszystkie kategorie produktów
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
        
        current_app.logger.info(f">>> shipping_quote: Zwrócono {len(result)} opcji wysyłki")
        return jsonify(result), 200
        
    except requests.exceptions.Timeout:
        current_app.logger.error(">>> shipping_quote: Timeout podczas pobierania wyceny po wszystkich próbach")
        return jsonify({
            "error": "Serwis kurierski nie odpowiada. Spróbuj ponownie za chwilę."
        }), 504
    except Exception as e:
        current_app.logger.error(">>> shipping_quote: Wyjatek podczas pobierania wyceny: %s", e)
        return jsonify({
            "error": "Błąd podczas pobierania wyceny wysyłki"
        }), 500

logger = logging.getLogger(__name__)

@calculator_bp.route('/api/quote-sources', methods=['GET'])
@require_module_access('calculator')
def get_quote_sources():
    """
    Pobiera źródła wycen dostępne dla aktualnego użytkownika.
    Filtruje po roli użytkownika (allowed_roles).
    """
    try:
        # Pobierz dane użytkownika
        user_email = session.get('user_email')
        user = User.query.filter_by(email=user_email).first() if user_email else None

        user_role = user.role if user else None
        is_flexible_partner = user_role == 'flexible_partner' if user_role else False

        # Pobierz źródła dostępne dla użytkownika
        if user_role:
            sources = QuoteSource.get_sources_for_user(user_role, is_flexible_partner)
        else:
            # Fallback - wszystkie aktywne źródła
            sources = QuoteSource.query.filter_by(is_active=True).order_by(
                QuoteSource.sort_order
            ).all()

        return jsonify({
            'success': True,
            'sources': [{
                'id': s.id,
                'name': s.name,
                'skip_contact_validation': s.skip_contact_validation
            } for s in sources]
        })

    except Exception as e:
        current_app.logger.error(f"[get_quote_sources] Błąd: {str(e)}")
        return jsonify({'error': 'Błąd pobierania źródeł wycen'}), 500


@calculator_bp.route('/api/finishing-prices', methods=['GET'])
@require_module_access('calculator')
def get_finishing_prices():
    """Pobieranie cen wykończeń z bazy danych - hierarchiczne drzewko"""
    try:
        from .models import FinishingOption, FinishingTypePrice

        # Spróbuj najpierw z nowej tabeli hierarchicznej
        try:
            flat_list = FinishingOption.get_flat_list(include_inactive=False)
            if flat_list:
                prices_data = []
                for opt in flat_list:
                    prices_data.append({
                        'id': opt['id'],
                        'name': opt['name'],  # Pojedyncza nazwa np. "Barwne"
                        'full_path': opt['full_path'],  # Pełna ścieżka np. "Lakierowane > Barwne"
                        'price_netto': opt['effective_price_netto'],
                        'level': opt['level'],
                        'parent_id': opt['parent_id'],
                        'image_path': opt.get('image_path')
                    })
                return jsonify(prices_data)
        except Exception as e:
            current_app.logger.warning(f"Fallback do starej tabeli finishing: {e}")

        # Fallback: stara tabela
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

        # Typ wyceny (brutto/netto)
        quote_type = data.get('quote_type', 'brutto')

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

        # Zapisz wycenę z danymi kuriera i grupy cenowej i notatką
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
            quote_type=quote_type,
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
            
            # Pobierz dane obróbki krawędzi z poziomu produktu
            edges_data = product.get('edges', [])
            edges_type = None
            edges_r_value = None
            edges_angle_value = product.get('edges_angle_value')  # Kąt fazowania
            edges_price_netto = float(product.get('edges_netto', 0.0))
            edges_price_brutto = float(product.get('edges_brutto', 0.0))

            # Pobierz typ i R z pierwszej krawędzi (wszystkie mają te same ustawienia)
            if edges_data:
                edges_type = edges_data[0].get('type')
                edges_r_value = edges_data[0].get('r_value')
                # Jeśli kąt nie został przesłany osobno, pobierz z pierwszej krawędzi
                if edges_angle_value is None and edges_type == 'chamfer':
                    edges_angle_value = edges_data[0].get('angle_value')
                current_app.logger.info(f"[save_quote] Produkt #{i + 1}: {len(edges_data)} krawędzi, typ={edges_type}, R={edges_r_value}, kąt={edges_angle_value}, netto={edges_price_netto}, brutto={edges_price_brutto}")

            # Pobierz SVG wizualizacji krawędzi
            edges_svg = product.get('edges_svg', '')
            current_app.logger.info(f"[save_quote] Produkt #{i + 1}: edges_svg length={len(edges_svg) if edges_svg else 0}, has_svg={bool(edges_svg)}")

            # Zapisz szczegóły wykończenia i krawędzi dla produktu
            item_details = QuoteItemDetails(
                quote_id=quote.id,
                product_index=i + 1,
                finishing_type=finishing_type,
                finishing_variant=finishing_variant,
                finishing_color=finishing_color,
                finishing_gloss_level=finishing_gloss_level,
                finishing_price_netto=finishing_price_netto,
                finishing_price_brutto=finishing_price_brutto,
                quantity=product_quantity,
                # Obróbka krawędzi
                edges_config=edges_data if edges_data else None,
                edges_type=edges_type,
                edges_r_value=edges_r_value,
                edges_angle_value=edges_angle_value,
                edges_price_netto=edges_price_netto,
                edges_price_brutto=edges_price_brutto,
                edges_svg=edges_svg if edges_svg else None
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

            # Krawędzie są już zapisane w QuoteItemDetails (edges_config jako JSON)

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

    # Pobierz aktualnego użytkownika
    user_id = session.get('user_id')
    if not user_id:
        return jsonify([])
    
    user = User.query.get(user_id)
    if not user:
        return jsonify([])

    # ✅ NOWE: Bazowe query - WSZYSCY klienci (usunięto filtrowanie per rola)
    base_query = Client.query.filter(
        (Client.client_number.ilike(f"%{term}%")) |
        (Client.client_name.ilike(f"%{term}%")) |
        (Client.email.ilike(f"%{term}%")) |
        (Client.phone.ilike(f"%{term}%"))
    )

    matches = base_query.all()

    # ✅ NOWE: Segreguj klientów na własnych i cudzych
    own_clients = []
    other_clients = []
    
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
        
        client_data = {
            "id": c.id,
            "name": display_name,
            "email": c.email or "",
            "phone": c.phone or "",
            "is_own_client": c.created_by_user_id == user_id  # ✅ NOWE POLE
        }
        
        # ✅ NOWE: Segregacja - własni na górze, cudzy na dole
        if c.created_by_user_id == user_id:
            own_clients.append(client_data)
        else:
            other_clients.append(client_data)

    # ✅ NOWE: Złącz listy - własni klienci najpierw
    result = own_clients + other_clients

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


# ============================================
# ENDPOINTY OBRÓBKI KRAWĘDZI
# ============================================

@calculator_bp.route('/api/edge-options', methods=['GET'])
@require_module_access('calculator')
def get_edge_options():
    """Pobiera dostępne typy obróbki krawędzi z bazy danych"""
    try:
        from .models import EdgeOption

        # is_active=True lub NULL (dla kompatybilności wstecznej)
        options = EdgeOption.query.filter(
            (EdgeOption.is_active == True) | (EdgeOption.is_active.is_(None))
        ).order_by(EdgeOption.id).all()

        # Jeśli brak w bazie, zwróć domyślne wartości
        if not options:
            return jsonify([
                {'id': 1, 'type': 'chamfer', 'name': 'Fazowanie', 'price_per_mb': 15.0, 'corner_price': 5.0, 'r_min': 3, 'r_max': 10, 'r_default': 3},
                {'id': 2, 'type': 'round', 'name': 'Zaokrąglenie', 'price_per_mb': 15.0, 'corner_price': 5.0, 'r_min': 3, 'r_max': 20, 'r_default': 5}
            ])

        return jsonify([opt.to_dict() for opt in options])

    except Exception as e:
        current_app.logger.error(f"[get_edge_options] Błąd: {str(e)}")
        # Zwróć domyślne wartości w przypadku błędu
        return jsonify([
            {'id': 1, 'type': 'chamfer', 'name': 'Fazowanie', 'price_per_mb': 15.0, 'corner_price': 5.0, 'r_min': 3, 'r_max': 10, 'r_default': 3},
            {'id': 2, 'type': 'round', 'name': 'Zaokrąglenie', 'price_per_mb': 15.0, 'corner_price': 5.0, 'r_min': 3, 'r_max': 20, 'r_default': 5}
        ])


@calculator_bp.route('/api/edge-definitions', methods=['GET'])
@require_module_access('calculator')
def get_edge_definitions():
    """Zwraca definicje 12 krawędzi i grup dla frontendu"""
    try:
        from .services.edge_calculator import get_edge_definitions_for_frontend
        return jsonify(get_edge_definitions_for_frontend())
    except Exception as e:
        current_app.logger.error(f"[get_edge_definitions] Błąd: {str(e)}")
        return jsonify({'error': 'Błąd pobierania definicji krawędzi'}), 500


@calculator_bp.route('/api/calculate-edges', methods=['POST'])
@require_module_access('calculator')
def calculate_edges():
    """
    Oblicza cenę obróbki krawędzi na podstawie przesłanych danych.
    Opcjonalny endpoint - kalkulacja może być też wykonywana na froncie.
    """
    try:
        from .services.edge_calculator import calculate_all_edges

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Brak danych'}), 400

        edges_config = data.get('edges', [])
        dimensions = {
            'length': float(data.get('length', 0)),
            'width': float(data.get('width', 0)),
            'thickness': float(data.get('thickness', 0))
        }

        result = calculate_all_edges(edges_config, dimensions)
        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"[calculate_edges] Błąd: {str(e)}")
        return jsonify({'error': 'Błąd kalkulacji krawędzi'}), 500