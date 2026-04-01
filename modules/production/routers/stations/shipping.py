# modules/production/routers/stations/shipping.py
"""
Packaging/shipping API endpoints
"""

from flask import request, jsonify
from datetime import datetime, timedelta
from extensions import db
import traceback

from . import station_bp, logger


# ============================================================================
# SHIPPING / COURIER API ENDPOINTS (2025-12)
# ============================================================================

@station_bp.route('/api/packaging/ship/<order_id>', methods=['POST'])
def create_shipment(order_id):
    """
    Tworzy przesylke kurierska dla zamowienia.

    Workflow:
    1. Pobierz produkty zamowienia
    2. Generuj warianty pakowania (lub uzyj przekazanych wymiarow)
    3. Zapytaj GlobKurier o ceny
    4. Porownaj i wybierz najtansza opcje
    5. Utworz przesylke przez Baselinker
    6. Pobierz etykiete

    Request Body:
        {
            "length": int (cm),
            "width": int (cm),
            "height": int (cm),
            "weight": float (kg)
        }

    Returns:
        JSON: {
            success: bool,
            courier_name: str,
            service_name: str,
            price: float,
            tracking_number: str,
            package_id: int,
            label_base64: str
        }
    """
    current_step = 'init'

    try:
        # Importy wewnatrz try-except zeby zlapac bledy importu
        current_step = 'import'
        from ...models import ProductionItem
        from ...services.shipping_service import ShippingService
        from modules.baselinker.service import BaselinkerService

        current_step = 'dimensions'

        # Pobierz dane z requestu
        data = request.get_json() or {}
        dimensions = {
            'length': int(data.get('length', 0)),
            'width': int(data.get('width', 0)),
            'height': int(data.get('height', 0)),
            'weight': float(data.get('weight', 0))
        }

        # KROK 1: Pobierz produkty zamowienia
        products = ProductionItem.query.filter(
            ProductionItem.baselinker_order_id == str(order_id)
        ).all()

        if not products:
            # Sprobuj po internal_order_number
            products = ProductionItem.query.filter(
                ProductionItem.internal_order_number == str(order_id)
            ).all()

        if not products:
            raise ValueError(f"Nie znaleziono produktow dla zamowienia {order_id}")

        # Pobierz dane dostawy z pierwszego produktu
        first_product = products[0]
        receiver_postcode = first_product.delivery_postcode
        receiver_address = first_product.delivery_address
        receiver_city = first_product.delivery_city
        receiver_name = first_product.delivery_fullname
        receiver_country = first_product.delivery_country_code or 'PL'

        # Pobierz baselinker_order_id dla createPackage
        baselinker_order_id = first_product.baselinker_order_id

        if not receiver_postcode:
            raise ValueError("Brak kodu pocztowego odbiorcy")

        # KROK 2: Generuj warianty pakowania (informacyjnie)
        current_step = 'variants'

        shipping_service = ShippingService()
        variants = shipping_service.generate_packaging_variants(products)
        valid_variants = [v for v in variants if v['valid']]

        # KROK 3: Zapytaj GlobKurier o ceny
        current_step = 'prices'

        # Uzyj wymiarow podanych przez uzytkownika
        quotes = shipping_service.get_quotes_for_package(
            package=dimensions,
            receiver_postcode=receiver_postcode,
            sender_postcode='36-068'  # Bachorz
        )

        if not quotes:
            raise ValueError("Nie znaleziono dostepnych ofert kurierskich")

        # KROK 4: Porownaj i wybierz najtansza
        current_step = 'compare'

        # Juz przefiltrowane w get_quotes_for_package (bez automatow)
        if not quotes:
            raise ValueError("Brak ofert kurierskich door-to-door (tylko automaty paczkowe)")

        # Sortuj po cenie
        cheapest = min(quotes, key=lambda x: x.get('price', float('inf')))

        # KROK 5: Utworz przesylke przez Baselinker
        current_step = 'create'

        # Mapowanie nazw kurierow z GlobKurier API na kody dla Baselinker
        COURIER_NAME_TO_CODE = {
            'inpost': 'inpost',
            'inpost-kurier': 'inpost',
            'dpd': 'dpd',
            'dhl': 'dhl',
            'dhl de': 'dhl-de',
            'dhl pop': 'dhl pop',
            'gls': 'gls',
            'ups': 'ups',
            'fedex': 'fedex',
            'poczta polska': 'poczta',
            'poczta': 'poczta',
            'ambro': 'ambro',
            'ambroexpress': 'ambro',
            'globkurier': 'Globkurier',
            'geodis': 'GEODIS',
            'hellmann': 'Hellmann',
            'cargus': 'cargus',
            'orlen paczka': 'ruch',
            'ruch': 'ruch',
            'postnord': 'PostNord',
            'spring': 'Spring',
            'colissimo': 'Colissimo',
        }

        # Znajdz kod kuriera na podstawie nazwy
        courier_name_lower = (cheapest.get('courier_name') or '').lower().strip()
        selected_courier_code = COURIER_NAME_TO_CODE.get(courier_name_lower)

        # Jesli nie znaleziono bezposrednio, sprobuj czesciowego dopasowania
        if not selected_courier_code:
            for name_part, code in COURIER_NAME_TO_CODE.items():
                if name_part in courier_name_lower or courier_name_lower in name_part:
                    selected_courier_code = code
                    break

        if not selected_courier_code:
            raise ValueError(f"Nie mozna zmapowac kuriera '{cheapest.get('courier_name')}' na kod Baselinker")

        # Oblicz laczna wartosc netto zamowienia (suma total_value_net wszystkich produktow)
        total_order_value = sum(
            float(p.total_value_net or 0) for p in products
        )

        # Oblicz date odbioru: dzisiaj jesli przed 14:00, jutro jesli po 14:00
        now = datetime.now()
        cutoff_hour = 14

        if now.hour < cutoff_hour:
            pickup_date = now.date()
        else:
            pickup_date = (now + timedelta(days=1)).date()

        # Format daty jako timestamp Unix (wymagany przez Baselinker)
        pickup_timestamp = int(datetime.combine(pickup_date, datetime.min.time()).timestamp())

        package_fields = [
            {'id': 'courier', 'value': selected_courier_code},
            {'id': 'count_package', 'value': '1'},
            {'id': 'reference_number', 'value': str(baselinker_order_id)},
            {'id': 'package_description', 'value': 'Klejonka drewniana'},
            {'id': 'value_price', 'value': str(round(total_order_value, 2))},
            {'id': 'pickup_date', 'value': str(pickup_timestamp)},
        ]

        # Tablica paczek z wymiarami
        packages_data = [
            {
                'weight': float(dimensions['weight']),
                'height': int(dimensions['height']),
                'length': int(dimensions['length']),
                'width': int(dimensions['width'])
            }
        ]

        baselinker = BaselinkerService()
        package_result = baselinker.create_package(
            order_id=int(baselinker_order_id),
            courier_code='globkurier',
            account_id=11364,
            fields=package_fields,
            packages=packages_data
        )

        if not package_result.get('success'):
            raise ValueError(f"Blad Baselinker: {package_result.get('error', 'Nieznany blad')}")

        package_id = package_result.get('package_id')
        tracking_number = package_result.get('courier_package_nr', '')

        # KROK 6: Pobierz etykiete
        current_step = 'label'

        label_result = baselinker.get_label(
            courier_code='globkurier',
            package_id=package_id
        )

        if not label_result.get('success'):
            logger.warning(f"[Shipping] Nie udalo sie pobrac etykiety: {label_result.get('error')}")
            label_base64 = ''
        else:
            label_base64 = label_result.get('label', '')

        # KROK 7: Zapisz dane wysylki w bazie danych
        current_step = 'save'

        shipping_price = cheapest.get('price', 0)
        courier_name = cheapest.get('courier_name', '')

        # Zapisz dane wysylki dla wszystkich produktow w zamowieniu
        for product in products:
            product.shipping_package_id = package_id
            product.shipping_tracking_number = tracking_number
            product.shipping_courier_name = courier_name
            product.shipping_price = shipping_price
            product.shipping_label_base64 = label_base64
            product.shipping_created_at = datetime.now()

        db.session.commit()

        return jsonify({
            'success': True,
            'courier_name': courier_name,
            'service_name': cheapest.get('service_name'),
            'price': shipping_price,
            'tracking_number': tracking_number,
            'package_id': package_id,
            'label_base64': label_base64
        }), 200

    except Exception as e:
        logger.error(f"[Shipping] BLAD w kroku '{current_step}': {str(e)}",
                    order_id=order_id,
                    current_step=current_step,
                    error=str(e),
                    traceback_info=traceback.format_exc())

        return jsonify({
            'success': False,
            'failed_step': current_step,
            'error': str(e)
        }), 200  # 200 bo frontend oczekuje JSON z bledem


@station_bp.route('/api/packaging/check-shipping/<order_id>')
def check_shipping_availability(order_id):
    """
    Sprawdza czy zamowienie moze byc wyslane kurierem.

    Returns:
        JSON: {
            can_ship: bool,
            is_personal_pickup: bool,
            dimensions: {...},
            within_limits: bool,
            limit_issues: [...]
        }
    """
    try:
        from ...models import ProductionItem
        from ...services.shipping_service import ShippingService

        products = ProductionItem.query.filter(
            ProductionItem.baselinker_order_id == str(order_id)
        ).all()

        if not products:
            products = ProductionItem.query.filter(
                ProductionItem.internal_order_number == str(order_id)
            ).all()

        if not products:
            return jsonify({
                'success': False,
                'error': f'Nie znaleziono produktow dla zamowienia {order_id}'
            }), 404

        first_product = products[0]

        # Sprawdz typ dostawy
        is_pickup = first_product.is_personal_pickup

        if is_pickup:
            return jsonify({
                'success': True,
                'can_ship': False,
                'is_personal_pickup': True,
                'reason': 'Zamowienie przeznaczone do odbioru osobistego'
            }), 200

        # Oblicz wymiary
        shipping_service = ShippingService()
        dimensions = shipping_service.calculate_package_dimensions(products)

        can_ship = dimensions['within_limits']

        return jsonify({
            'success': True,
            'can_ship': can_ship,
            'is_personal_pickup': False,
            'dimensions': dimensions,
            'within_limits': dimensions['within_limits'],
            'limit_issues': dimensions.get('limit_issues', [])
        }), 200

    except Exception as e:
        logger.error("[Shipping] Blad sprawdzania dostepnosci wysylki", extra={
            'order_id': order_id,
            'error': str(e)
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@station_bp.route('/api/packaging/quote/<order_id>', methods=['POST'])
def get_shipping_quote(order_id):
    """
    Pobiera wycene przesylki BEZ jej tworzenia.
    Zwraca najlepsza opcje (single lub multi-package).

    Request Body:
        {
            "length": int (cm),
            "width": int (cm),
            "height": int (cm),
            "weight": float (kg)
        }

    Returns:
        JSON: {
            success: bool,
            quote: {
                courier_name: str,
                service_name: str,
                price: float,
                is_multi_package: bool,
                total_packages: int,
                packages: [...]
            }
        }
    """
    try:
        from ...models import ProductionItem
        from ...services.shipping_service import ShippingService

        # Pobierz dane z requestu
        data = request.get_json() or {}
        dimensions = {
            'length': int(data.get('length', 0)),
            'width': int(data.get('width', 0)),
            'height': int(data.get('height', 0)),
            'weight': float(data.get('weight', 0))
        }

        # Walidacja wymiarow
        if dimensions['length'] <= 0 or dimensions['width'] <= 0 or dimensions['height'] <= 0 or dimensions['weight'] <= 0:
            return jsonify({
                'success': False,
                'error': 'Nieprawidlowe wymiary paczki'
            }), 400

        # Pobierz produkty zamowienia
        products = ProductionItem.query.filter(
            ProductionItem.baselinker_order_id == str(order_id)
        ).all()

        if not products:
            products = ProductionItem.query.filter(
                ProductionItem.internal_order_number == str(order_id)
            ).all()

        if not products:
            return jsonify({
                'success': False,
                'error': f'Nie znaleziono produktow dla zamowienia {order_id}'
            }), 404

        first_product = products[0]
        receiver_postcode = first_product.delivery_postcode

        if not receiver_postcode:
            return jsonify({
                'success': False,
                'error': 'Brak kodu pocztowego odbiorcy'
            }), 400

        # Inicjalizacja ShippingService
        shipping_service = ShippingService()

        # Pobierz wyceny dla podanych wymiarow (pojedyncza paczka)
        quotes = shipping_service.get_quotes_for_package(
            package=dimensions,
            receiver_postcode=receiver_postcode,
            sender_postcode='36-068'
        )

        if not quotes:
            return jsonify({
                'success': False,
                'error': 'Brak dostepnych ofert kurierskich dla tych wymiarow'
            }), 400

        # Znajdz najtansza opcje
        cheapest = min(quotes, key=lambda x: x.get('price', float('inf')))

        # Przygotuj odpowiedz
        quote_response = {
            'courier_name': cheapest.get('courier_name', 'Nieznany'),
            'service_name': cheapest.get('service_name', ''),
            'price': cheapest.get('price', 0),
            'service_id': cheapest.get('service_id', ''),
            'is_multi_package': False,
            'total_packages': 1,
            'packages': [{
                'length': dimensions['length'],
                'width': dimensions['width'],
                'height': dimensions['height'],
                'weight': dimensions['weight'],
                'courier_name': cheapest.get('courier_name'),
                'price': cheapest.get('price')
            }]
        }

        return jsonify({
            'success': True,
            'quote': quote_response
        }), 200

    except Exception as e:
        logger.error(f"[Shipping] Blad pobierania wyceny: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@station_bp.route('/api/packaging/refresh-tracking/<order_id>')
def refresh_tracking(order_id):
    """
    Pobiera i aktualizuje numer sledzenia z Baselinker (getOrderPackages).
    GlobKurier moze nie zwracac numeru tracking od razu - trzeba odpytac pozniej.

    Returns:
        JSON: {
            success: bool,
            tracking_number: str,
            tracking_url: str
        }
    """
    try:
        from ...models import ProductionItem
        from modules.baselinker.service import BaselinkerService

        # Znajdz produkty zamowienia
        products = ProductionItem.query.filter(
            ProductionItem.baselinker_order_id == str(order_id)
        ).all()

        if not products:
            products = ProductionItem.query.filter(
                ProductionItem.internal_order_number == str(order_id)
            ).all()

        if not products:
            return jsonify({
                'success': False,
                'error': f'Nie znaleziono produktow dla zamowienia {order_id}'
            }), 404

        # Pobierz baselinker_order_id
        baselinker_order_id = products[0].baselinker_order_id
        if not baselinker_order_id:
            return jsonify({
                'success': False,
                'error': 'Brak baselinker_order_id dla tego zamowienia'
            }), 400

        # Pobierz paczki z Baselinker
        baselinker = BaselinkerService()
        result = baselinker.get_order_packages(int(baselinker_order_id))

        if not result.get('success'):
            return jsonify({
                'success': False,
                'error': result.get('error', 'Blad pobierania paczek z Baselinker')
            }), 500

        packages = result.get('packages', [])

        if not packages:
            return jsonify({
                'success': True,
                'tracking_number': '',
                'tracking_url': '',
                'message': 'Brak paczek dla tego zamowienia'
            }), 200

        # Znajdz paczke z numerem sledzenia (pierwsza z listy)
        package = packages[0]
        tracking_number = package.get('courier_package_nr', '')
        tracking_url = package.get('tracking_url', '')

        # Aktualizuj w bazie danych jesli jest numer
        if tracking_number:
            for product in products:
                product.shipping_tracking_number = tracking_number

            db.session.commit()

        return jsonify({
            'success': True,
            'tracking_number': tracking_number,
            'tracking_url': tracking_url,
            'package_id': package.get('package_id'),
            'courier_code': package.get('courier_code')
        }), 200

    except Exception as e:
        logger.error(f"[Shipping] Blad odswiezania numeru sledzenia: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@station_bp.route('/api/packaging/refresh-label/<order_id>')
def refresh_label(order_id):
    """
    Ponownie pobiera etykiete z Baselinker i aktualizuje w bazie danych.
    Uzywane gdy etykieta zostala obcieta lub uszkodzona.

    Returns:
        JSON: {
            success: bool,
            label_base64: str,
            label_size: int
        }
    """
    try:
        from ...models import ProductionItem
        from modules.baselinker.service import BaselinkerService

        # Znajdz produkty zamowienia
        products = ProductionItem.query.filter(
            ProductionItem.baselinker_order_id == str(order_id)
        ).all()

        if not products:
            products = ProductionItem.query.filter(
                ProductionItem.internal_order_number == str(order_id)
            ).all()

        if not products:
            return jsonify({
                'success': False,
                'error': f'Nie znaleziono produktow dla zamowienia {order_id}'
            }), 404

        first_product = products[0]

        # Sprawdz czy mamy package_id
        package_id = first_product.shipping_package_id
        if not package_id:
            return jsonify({
                'success': False,
                'error': 'Brak package_id - przesylka nie zostala jeszcze zgloszona'
            }), 400

        # Pobierz etykiete z Baselinker
        baselinker = BaselinkerService()
        label_result = baselinker.get_label(
            courier_code='globkurier',
            package_id=package_id
        )

        if not label_result.get('success'):
            return jsonify({
                'success': False,
                'error': f"Blad pobierania etykiety: {label_result.get('error')}"
            }), 500

        label_base64 = label_result.get('label', '')
        label_size = len(label_base64)

        # Aktualizuj w bazie danych
        for product in products:
            product.shipping_label_base64 = label_base64

        db.session.commit()

        return jsonify({
            'success': True,
            'label_base64': label_base64,
            'label_size': label_size,
            'message': f'Etykieta pobrana pomyslnie ({label_size} znakow)'
        }), 200

    except Exception as e:
        logger.error(f"[Shipping] Blad ponownego pobierania etykiety: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
