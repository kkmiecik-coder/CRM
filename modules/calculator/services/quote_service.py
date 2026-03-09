# modules/calculator/services/quote_service.py
"""
Serwis wycen - tworzenie, ladowanie i aktualizacja wycen.
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from extensions import db


def _to_decimal(value, default='0'):
    """Konwertuje wartość na Decimal bezpiecznie."""
    try:
        return Decimal(str(value)) if value is not None else Decimal(default)
    except Exception:
        return Decimal(default)


def _round_price(value):
    """Zaokrągla cenę do groszy (2 miejsc po przecinku)."""
    return float(_to_decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

logger = logging.getLogger(__name__)


def _validate_quote_access(quote, current_user):
    """Sprawdza czy uzytkownik ma prawo edytowac wycene."""
    if current_user.role == 'admin':
        return True
    if quote.user_id == current_user.id:
        return True
    return False


def load_quote_for_edit(edit_uuid, current_user):
    """
    Laduje dane wyceny do edycji w kalkulatorze.

    Args:
        edit_uuid: UUID wyceny
        current_user: Aktualny uzytkownik (flask_login)

    Returns:
        tuple: (slownik wyniku, kod HTTP)
    """
    from modules.calculator.models import Quote, QuoteItem, QuoteItemDetails

    quote = Quote.query.filter_by(edit_uuid=edit_uuid).first()
    if not quote:
        return {"success": False, "error": "Wycena nie istnieje"}, 404

    if not _validate_quote_access(quote, current_user):
        return {"success": False, "error": "Brak uprawnien do edycji tej wyceny"}, 403

    try:
        # Pobierz items i details
        quote_items = quote.items.all()
        details = QuoteItemDetails.query.filter_by(quote_id=quote.id).all()
        details_by_index = {d.product_index: d for d in details}

        # Grupuj warianty po product_index
        products_map = {}
        for item in quote_items:
            idx = item.product_index
            if idx not in products_map:
                products_map[idx] = {
                    "items": [],
                    "selected_variant": None
                }
            products_map[idx]["items"].append(item)
            if item.is_selected:
                products_map[idx]["selected_variant"] = item.variant_code

        # Buduj liste produktow
        products = []
        for idx in sorted(products_map.keys()):
            product_data = products_map[idx]
            detail = details_by_index.get(idx)
            first_item = product_data["items"][0]

            product = {
                "index": idx,
                "length": float(first_item.length_cm) if first_item.length_cm else 0,
                "width": float(first_item.width_cm) if first_item.width_cm else 0,
                "thickness": float(first_item.thickness_cm) if first_item.thickness_cm else 0,
                "quantity": detail.quantity if detail else 1,
                "shape": detail.shape if detail else "rectangular",
                "round_surcharge_netto": float(detail.round_surcharge_netto) if detail and detail.round_surcharge_netto else 0,
                "round_surcharge_brutto": float(detail.round_surcharge_brutto) if detail and detail.round_surcharge_brutto else 0,
                "selectedVariant": product_data["selected_variant"],
                "finishing": {
                    "type": detail.finishing_type if detail else None,
                    "variant": detail.finishing_variant if detail else None,
                    "color": detail.finishing_color if detail else None,
                    "gloss": detail.finishing_gloss_level if detail else None,
                    "priceNetto": float(detail.finishing_price_netto) if detail and detail.finishing_price_netto else 0,
                    "priceBrutto": float(detail.finishing_price_brutto) if detail and detail.finishing_price_brutto else 0,
                } if detail else None,
                "edges": {
                    "config": detail.edges_config if detail else None,
                    "type": detail.edges_type if detail else None,
                    "rValue": detail.edges_r_value if detail else None,
                    "angleValue": detail.edges_angle_value if detail else None,
                    "netto": float(detail.edges_price_netto) if detail and detail.edges_price_netto else 0,
                    "brutto": float(detail.edges_price_brutto) if detail and detail.edges_price_brutto else 0,
                    "svg": detail.edges_svg if detail else None,
                } if detail and detail.edges_type else None,
                "variants": []
            }

            for item in product_data["items"]:
                product["variants"].append({
                    "item_id": item.id,
                    "variant_code": item.variant_code,
                    "is_selected": item.is_selected,
                    "show_on_client_page": item.show_on_client_page,
                    "price_per_m3": float(item.price_per_m3) if item.price_per_m3 else 0,
                    "volume_m3": float(item.volume_m3) if item.volume_m3 else 0,
                    "real_volume_m3": float(item.real_volume_m3) if item.real_volume_m3 else 0,
                    "multiplier": float(item.multiplier) if item.multiplier else 1.0,
                    "unit_price_netto": float(item.price_netto) if item.price_netto else 0,
                    "unit_price_brutto": float(item.price_brutto) if item.price_brutto else 0,
                    "original_price_netto": float(item.original_price_netto) if item.original_price_netto else None,
                    "original_price_brutto": float(item.original_price_brutto) if item.original_price_brutto else None,
                    "discount_percentage": float(item.discount_percentage) if item.discount_percentage else 0,
                })

            products.append(product)

        # Buduj response
        client = quote.client
        return {
            "success": True,
            "quote": {
                "id": quote.id,
                "edit_uuid": quote.edit_uuid,
                "quote_number": quote.quote_number,
                "created_at": quote.created_at.isoformat() if quote.created_at else None,
                "status_name": quote.quote_status.name if quote.quote_status else None,
                "client": {
                    "id": client.id if client else None,
                    "client_number": client.client_number if client else None,
                    "client_name": client.client_name if client else client.client_number if client else None,
                    "email": client.email if client else None,
                    "phone": client.phone if client else None,
                },
                "settings": {
                    "clientType": quote.quote_client_type,
                    "multiplier": float(quote.quote_multiplier) if quote.quote_multiplier else 1.0,
                    "quoteType": quote.quote_type or "brutto",
                    "courierName": quote.courier_name,
                    "shippingNetto": float(quote.shipping_cost_netto) if quote.shipping_cost_netto else 0,
                    "shippingBrutto": float(quote.shipping_cost_brutto) if quote.shipping_cost_brutto else 0,
                    "notes": quote.notes or "",
                    "source": quote.source,
                },
                "products": products,
            }
        }, 200

    except Exception as e:
        current_app.logger.exception(f"[load_quote_for_edit] Blad: {str(e)}")
        return {"success": False, "error": "Blad ladowania wyceny"}, 500


def update_quote(edit_uuid, data, current_user):
    """
    Aktualizuje istniejaca wycene na podstawie danych z kalkulatora.

    Args:
        edit_uuid: UUID wyceny
        data: Dane z requestu (JSON)
        current_user: Aktualny uzytkownik (flask_login)

    Returns:
        tuple: (slownik wyniku, kod HTTP)
    """
    from modules.calculator.models import (
        Quote, QuoteItem, QuoteItemDetails, QuoteLog,
        CalculatorSetting
    )

    quote = Quote.query.filter_by(edit_uuid=edit_uuid).first()
    if not quote:
        return {"success": False, "error": "Wycena nie istnieje"}, 404

    if not _validate_quote_access(quote, current_user):
        return {"success": False, "error": "Brak uprawnien do edycji tej wyceny"}, 403

    try:
        settings = data.get('settings', {})

        # 1. Aktualizacja ustawien Quote
        quote.notes = settings.get('notes', quote.notes)
        quote.courier_name = settings.get('courierName', quote.courier_name)
        quote.shipping_cost_netto = settings.get('shippingNetto', quote.shipping_cost_netto)
        quote.shipping_cost_brutto = settings.get('shippingBrutto', quote.shipping_cost_brutto)
        quote.quote_type = settings.get('quoteType', quote.quote_type)
        quote.quote_client_type = settings.get('clientType', quote.quote_client_type)
        quote.quote_multiplier = settings.get('multiplier', quote.quote_multiplier)
        quote.source = settings.get('source', quote.source)

        if 'total_price' in data:
            quote.total_price = data['total_price']

        # 2. Usuniecie produktow
        for idx in data.get('deleted_product_indexes', []):
            QuoteItem.query.filter_by(quote_id=quote.id, product_index=idx).delete()
            QuoteItemDetails.query.filter_by(quote_id=quote.id, product_index=idx).delete()

        # 3. Aktualizacja/dodanie produktow
        for product in data.get('products', []):
            _update_or_create_product(quote, product)

        # 4. Log zmian
        log = QuoteLog(
            quote_id=quote.id,
            user_id=current_user.id,
            description="Zaktualizowano wycene przez kalkulator",
        )
        db.session.add(log)
        db.session.commit()

        return {
            "success": True,
            "message": "Wycena zostala zaktualizowana",
            "quote_id": quote.id,
            "quote_number": quote.quote_number,
        }, 200

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("[update_quote] Blad podczas aktualizacji wyceny:")
        return {"success": False, "error": "Blad bazy danych podczas aktualizacji wyceny"}, 500


def _update_or_create_product(quote, product_data):
    """Aktualizuje lub tworzy produkt w wycenie."""
    from modules.calculator.models import (
        QuoteItem, QuoteItemDetails, CalculatorSetting
    )

    idx = product_data.get('index')
    quantity = int(product_data.get('quantity', 1))

    # Ksztalt i doplata
    shape = product_data.get('shape', 'rectangular')
    round_surcharge_netto = 0
    round_surcharge_brutto = 0
    if shape == 'round':
        surcharge_per_unit = _to_decimal(
            CalculatorSetting.get_value('round_shape_surcharge_netto', '50.00')
        )
        round_surcharge_netto = _round_price(surcharge_per_unit * Decimal(quantity))
        round_surcharge_brutto = _round_price(
            _to_decimal(round_surcharge_netto) * Decimal('1.23')
        )

    # Aktualizuj lub utworz QuoteItemDetails
    detail = QuoteItemDetails.query.filter_by(
        quote_id=quote.id, product_index=idx
    ).first()

    finishing = product_data.get('finishing', {}) or {}
    edges = product_data.get('edges', {}) or {}

    if detail:
        detail.quantity = quantity
        detail.finishing_type = finishing.get('type')
        detail.finishing_variant = finishing.get('variant')
        detail.finishing_color = finishing.get('color')
        detail.finishing_gloss_level = finishing.get('gloss')
        detail.finishing_price_netto = finishing.get('priceNetto', 0)
        detail.finishing_price_brutto = finishing.get('priceBrutto', 0)
        detail.edges_config = edges.get('config')
        detail.edges_type = edges.get('type')
        detail.edges_r_value = edges.get('rValue')
        detail.edges_angle_value = edges.get('angleValue')
        detail.edges_price_netto = edges.get('netto', 0)
        detail.edges_price_brutto = edges.get('brutto', 0)
        detail.edges_svg = edges.get('svg')
        detail.shape = shape
        detail.round_surcharge_netto = round_surcharge_netto
        detail.round_surcharge_brutto = round_surcharge_brutto
    else:
        detail = QuoteItemDetails(
            quote_id=quote.id,
            product_index=idx,
            quantity=quantity,
            finishing_type=finishing.get('type'),
            finishing_variant=finishing.get('variant'),
            finishing_color=finishing.get('color'),
            finishing_gloss_level=finishing.get('gloss'),
            finishing_price_netto=finishing.get('priceNetto', 0),
            finishing_price_brutto=finishing.get('priceBrutto', 0),
            edges_config=edges.get('config'),
            edges_type=edges.get('type'),
            edges_r_value=edges.get('rValue'),
            edges_angle_value=edges.get('angleValue'),
            edges_price_netto=edges.get('netto', 0),
            edges_price_brutto=edges.get('brutto', 0),
            edges_svg=edges.get('svg'),
            shape=shape,
            round_surcharge_netto=round_surcharge_netto,
            round_surcharge_brutto=round_surcharge_brutto,
        )
        db.session.add(detail)

    # Usun stare warianty dla tego produktu
    QuoteItem.query.filter_by(quote_id=quote.id, product_index=idx).delete()

    # Dodaj nowe warianty
    for variant in product_data.get('variants', []):
        unit_price_netto = variant.get('unit_price_netto', 0)
        unit_price_brutto = variant.get('unit_price_brutto', 0)

        quote_item = QuoteItem(
            quote_id=quote.id,
            product_index=idx,
            length_cm=product_data.get('length'),
            width_cm=product_data.get('width'),
            thickness_cm=product_data.get('thickness'),
            volume_m3=variant.get('volume_m3', 0),
            real_volume_m3=variant.get('real_volume_m3', variant.get('volume_m3', 0)),
            price_per_m3=variant.get('price_per_m3', 0),
            multiplier=variant.get('multiplier', 1.0),
            price_netto=unit_price_netto,
            price_brutto=unit_price_brutto,
            original_price_netto=unit_price_netto,
            original_price_brutto=unit_price_brutto,
            is_selected=variant.get('is_selected', False),
            variant_code=variant.get('variant_code'),
            show_on_client_page=variant.get('show_on_client_page', True),
        )
        db.session.add(quote_item)


def generate_quote_number(year, month):
    """
    Generuje kolejny numer wyceny w formacie NN/MM/RR/W.

    Returns:
        str: Numer wyceny
    """
    year_short = str(year)[-2:]

    counter = (
        db.session.query(_get_counter_model())
        .filter_by(year=year, month=month)
        .with_for_update()
        .first()
    )

    if not counter:
        CounterModel = _get_counter_model()
        counter = CounterModel(year=year, month=month, current_number=1)
        db.session.add(counter)
        db.session.flush()
        current_number = 1
    else:
        counter.current_number += 1
        db.session.flush()
        current_number = counter.current_number

    return f"{current_number:02d}/{month:02d}/{year_short}/W"


def _get_counter_model():
    """Import modelu QuoteCounter (unikamy circular imports)"""
    from modules.calculator.models import QuoteCounter
    return QuoteCounter


def create_quote(data, user_email):
    """
    Tworzy kompletną wycenę z produktami, wariantami i szczegółami.

    Args:
        data: Dane wyceny z requestu (JSON)
        user_email: Email zalogowanego użytkownika

    Returns:
        tuple: (słownik wyniku, kod HTTP)
    """
    from modules.calculator.models import (
        Quote, QuoteItem, QuoteItemDetails, QuoteLog,
        CalculatorSetting
    )
    from modules.clients.models import Client

    try:
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

        # Obsługa klienta - tworzenie nowego jeśli nie podano ID
        if not client_id:
            login = data.get('client_login')
            if not login:
                return {"success": False, "error": "Brak danych klienta."}, 400

            existing_client = Client.query.filter_by(client_number=login).first()
            if existing_client:
                return {"success": False, "error": "Klient o takim loginie juz istnieje"}, 400

            # Pobierz user_id osoby tworzącej klienta
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
                created_by_user_id=current_user_id,
            )
            db.session.add(client)
            db.session.commit()
            client_id = client.id

        if not products:
            return {"success": False, "error": "Brakuje produktow."}, 400

        now = datetime.utcnow()
        quote_number = generate_quote_number(now.year, now.month)

        user = db.session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {'email': user_email}
        ).fetchone()
        user_id = user.id if user else None

        # Zapisz wycenę
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

        # Przetwarzanie produktów
        for i, product in enumerate(products):
            variants = product.get('variants', [])
            if not variants:
                current_app.logger.warning(
                    f"[save_quote] Produkt #{i + 1} nie zawiera wariantów – pomijam."
                )
                continue

            product_quantity = int(product.get('quantity', 1))

            # Dane wykończenia z poziomu produktu
            finishing_type = product.get("finishing_type")
            finishing_variant = product.get("finishing_variant")
            finishing_color = product.get("finishing_color")
            finishing_gloss_level = product.get("finishing_gloss_level")
            finishing_price_netto = product.get("finishing_netto", 0.0)
            finishing_price_brutto = product.get("finishing_brutto", 0.0)

            # Dane obróbki krawędzi
            edges_data = product.get('edges', [])
            edges_type = None
            edges_r_value = None
            edges_angle_value = product.get('edges_angle_value')
            edges_price_netto = float(product.get('edges_netto', 0.0))
            edges_price_brutto = float(product.get('edges_brutto', 0.0))

            if edges_data:
                edges_type = edges_data[0].get('type')
                edges_r_value = edges_data[0].get('r_value')
                if edges_angle_value is None and edges_type == 'chamfer':
                    edges_angle_value = edges_data[0].get('angle_value')
                current_app.logger.info(
                    f"[save_quote] Produkt #{i + 1}: {len(edges_data)} krawędzi, "
                    f"typ={edges_type}, R={edges_r_value}, kąt={edges_angle_value}, "
                    f"netto={edges_price_netto}, brutto={edges_price_brutto}"
                )

            edges_svg = product.get('edges_svg', '')

            # Kształt produktu i dopłata za okrągły
            product_shape = product.get('shape', 'rectangular')
            round_surcharge_netto = 0
            round_surcharge_brutto = 0
            if product_shape == 'round':
                surcharge_per_unit = _to_decimal(
                    CalculatorSetting.get_value('round_shape_surcharge_netto', '50.00')
                )
                round_surcharge_netto = _round_price(surcharge_per_unit * Decimal(product_quantity))
                round_surcharge_brutto = _round_price(
                    _to_decimal(round_surcharge_netto) * Decimal('1.23')
                )

            # Szczegóły produktu (wykończenie + krawędzie)
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
                edges_config=edges_data if edges_data else None,
                edges_type=edges_type,
                edges_r_value=edges_r_value,
                edges_angle_value=edges_angle_value,
                edges_price_netto=edges_price_netto,
                edges_price_brutto=edges_price_brutto,
                edges_svg=edges_svg if edges_svg else None,
                shape=product_shape,
                round_surcharge_netto=round_surcharge_netto,
                round_surcharge_brutto=round_surcharge_brutto,
            )
            db.session.add(item_details)

            # Warianty produktu
            for j, variant in enumerate(variants):
                final_price_netto = variant.get('final_price_netto', 0.0)
                final_price_brutto = variant.get('final_price_brutto', 0.0)

                unit_price_netto = _round_price(
                    _to_decimal(final_price_netto) / Decimal(product_quantity)
                ) if product_quantity > 0 else 0.0
                unit_price_brutto = _round_price(
                    _to_decimal(final_price_brutto) / Decimal(product_quantity)
                ) if product_quantity > 0 else 0.0

                is_available = variant.get('is_available', True)

                quote_item = QuoteItem(
                    quote_id=quote.id,
                    product_index=i + 1,
                    length_cm=product.get('length'),
                    width_cm=product.get('width'),
                    thickness_cm=product.get('thickness'),
                    volume_m3=variant.get('volume_m3', 0.0),
                    real_volume_m3=variant.get('real_volume_m3', variant.get('volume_m3', 0.0)),
                    price_per_m3=variant.get('price_per_m3', 0.0),
                    multiplier=variant.get('multiplier', 1.0),
                    price_netto=unit_price_netto,
                    price_brutto=unit_price_brutto,
                    is_selected=variant.get('is_selected', False),
                    variant_code=variant.get('variant_code'),
                    show_on_client_page=is_available,
                )
                db.session.add(quote_item)

        # Log
        log = QuoteLog(
            quote_id=quote.id,
            user_id=user_id,
            description=(
                f"Utworzono wycenę {quote_number} dla grupy cenowej "
                f"'{quote_client_type or 'brak grupy'}' (mnożnik: {quote_multiplier})"
            ),
        )
        db.session.add(log)
        db.session.commit()

        return {
            "message": "Wycena zapisana.",
            "quote_number": quote_number,
            "quote_id": quote.id,
        }, 200

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("[save_quote] Błąd podczas zapisu wyceny:")
        return {"success": False, "error": "Blad bazy danych podczas zapisu wyceny"}, 500
