# modules/calculator/services/quote_service.py
"""
Serwis wycen - tworzenie, ladowanie i aktualizacja wycen.
"""

import json as _json
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


def _coerce_cut_to_size(product_data):
    """
    Wyciąga pole 'cut_to_size' z payloadu produktu z domyślną wartością True.
    None / brak klucza traktujemy jako True (kompat z draftami sprzed wdrożenia).
    """
    value = product_data.get('cut_to_size')
    if value is None:
        return True
    return bool(value)

logger = logging.getLogger(__name__)


def _validate_quote_access(quote, current_user):
    """Sprawdza czy uzytkownik ma prawo edytowac wycene."""
    if current_user.role in ('admin', 'user'):
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
                "shape_data": detail.shape_data if detail else None,
                "shape_svg": detail.shape_svg if detail else None,
                "lamella_direction": detail.lamella_direction if detail else None,
                "cut_to_size": bool(detail.cut_to_size) if detail else True,
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
                    "attachment_filename": quote.attachment_filename,
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
        # === BACKEND LICZY CENY OD ZERA — payload frontu to tylko parametry ===
        # Wykonane PRZED jakąkolwiek mutacją `quote`/DB, zeby przy bledzie
        # walidacji nic nie zostalo zmienione (return 400 bez zapisu).
        from modules.calculator.services.pricing_service import (
            load_pricing_data, calculate_quote as calc_quote,
        )
        pricing_data = load_pricing_data()
        calc = calc_quote(_payload_to_calc_request(data), pricing_data)
        if not calc['ok']:
            return {"success": False, "error": "Błędy walidacji wyceny",
                    "errors": calc['errors']}, 400

        # Nadpisz ceny w payloadzie wynikami backendu (per produkt / wariant)
        _inject_backend_prices(data.get('products', []), calc)

        settings = data.get('settings', {})

        # 1. Aktualizacja ustawien Quote
        quote.notes = settings.get('notes', quote.notes)
        quote.courier_name = settings.get('courierName', quote.courier_name)
        quote.shipping_cost_netto = settings.get('shippingNetto', quote.shipping_cost_netto)
        quote.shipping_cost_brutto = settings.get('shippingBrutto', quote.shipping_cost_brutto)
        quote.quote_type = settings.get('quoteType', quote.quote_type)
        quote.quote_client_type = settings.get('clientType', quote.quote_client_type)
        # quote_multiplier zapisywany do Quote to wartosc rozstrzygnieta przez
        # backend (grupa cenowa lub partner fixed), NIE surowy payload frontu.
        quote.quote_multiplier = calc['multiplier']
        quote.source = settings.get('source', quote.source)

        # total_price liczony przez backend (calc['totals']), nie payload frontu.
        quote.total_price = calc['totals']['total_brutto']

        # 2. Usun WSZYSTKIE stare produkty i dodaj nowe (pelna nadpisanie)
        QuoteItem.query.filter_by(quote_id=quote.id).delete()
        QuoteItemDetails.query.filter_by(quote_id=quote.id).delete()

        # 3. Dodanie produktow od nowa
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
    shape_data_json = product_data.get('shape_data')  # JSON string z frontendu
    shape_svg = product_data.get('shape_svg')
    lamella_direction = product_data.get('lamella_direction')
    round_surcharge_netto = 0
    round_surcharge_brutto = 0
    if shape in ('round', 'circle'):
        surcharge_per_unit = _to_decimal(
            CalculatorSetting.get_value('round_shape_surcharge_netto', '50.00')
        )
        round_surcharge_netto = _round_price(surcharge_per_unit * Decimal(quantity))
        round_surcharge_brutto = _round_price(
            _to_decimal(round_surcharge_netto) * Decimal('1.23')
        )

    # Docięcie do wymiaru (default True)
    cut_to_size = _coerce_cut_to_size(product_data)

    # Typ produktu wg sklepu (blat|schody|parapet) — CRM nie interpretuje, round-trip do by-token.
    # Brak klucza (payload kalkulatora CRM) => None (kolumna zostaje pusta / czyszczona przy edycji).
    product_type = product_data.get('product_type')

    # Aktualizuj lub utworz QuoteItemDetails
    detail = QuoteItemDetails.query.filter_by(
        quote_id=quote.id, product_index=idx
    ).first()

    # Obsluga dwoch formatow danych:
    # Format A (z load_quote_for_edit): finishing={type,variant,...}, edges={config,type,...}
    # Format B (z frontendu): finishing_type, finishing_variant, edges (lista), edges_type, ...
    finishing_raw = product_data.get('finishing')
    if isinstance(finishing_raw, dict):
        finishing_type = finishing_raw.get('type')
        finishing_variant = finishing_raw.get('variant')
        finishing_color = finishing_raw.get('color')
        finishing_gloss = finishing_raw.get('gloss')
        finishing_price_netto = finishing_raw.get('priceNetto', 0)
        finishing_price_brutto = finishing_raw.get('priceBrutto', 0)
    else:
        finishing_type = product_data.get('finishing_type')
        finishing_variant = product_data.get('finishing_variant')
        finishing_color = product_data.get('finishing_color')
        finishing_gloss = product_data.get('finishing_gloss_level')
        finishing_price_netto = product_data.get('finishing_netto', 0)
        finishing_price_brutto = product_data.get('finishing_brutto', 0)

    edges_raw = product_data.get('edges')
    if isinstance(edges_raw, dict):
        edges_config = edges_raw.get('config')
        edges_type = edges_raw.get('type')
        edges_r_value = edges_raw.get('rValue')
        edges_angle_value = edges_raw.get('angleValue')
        edges_price_netto = edges_raw.get('netto', 0)
        edges_price_brutto = edges_raw.get('brutto', 0)
        edges_svg = edges_raw.get('svg')
        edges_mode = edges_raw.get('mode')
    else:
        edges_config = edges_raw if isinstance(edges_raw, list) and edges_raw else None
        edges_type = product_data.get('edges_type')
        edges_r_value = product_data.get('edges_r_value')
        edges_angle_value = product_data.get('edges_angle_value')
        edges_price_netto = product_data.get('edges_netto', 0)
        edges_price_brutto = product_data.get('edges_brutto', 0)
        edges_svg = product_data.get('edges_svg')
        edges_mode = product_data.get('edges_mode')

    if detail:
        detail.quantity = quantity
        detail.finishing_type = finishing_type
        detail.finishing_variant = finishing_variant
        detail.finishing_color = finishing_color
        detail.finishing_gloss_level = finishing_gloss
        detail.finishing_price_netto = finishing_price_netto
        detail.finishing_price_brutto = finishing_price_brutto
        detail.edges_config = edges_config
        detail.edges_type = edges_type
        detail.edges_r_value = edges_r_value
        detail.edges_angle_value = edges_angle_value
        detail.edges_price_netto = edges_price_netto
        detail.edges_price_brutto = edges_price_brutto
        detail.edges_svg = edges_svg
        detail.edges_mode = edges_mode
        detail.shape = shape
        detail.shape_data = shape_data_json
        detail.shape_svg = shape_svg
        detail.round_surcharge_netto = round_surcharge_netto
        detail.round_surcharge_brutto = round_surcharge_brutto
        detail.lamella_direction = lamella_direction
        detail.cut_to_size = cut_to_size
        detail.product_type = product_type
    else:
        detail = QuoteItemDetails(
            quote_id=quote.id,
            product_index=idx,
            quantity=quantity,
            finishing_type=finishing_type,
            finishing_variant=finishing_variant,
            finishing_color=finishing_color,
            finishing_gloss_level=finishing_gloss,
            finishing_price_netto=finishing_price_netto,
            finishing_price_brutto=finishing_price_brutto,
            edges_config=edges_config,
            edges_type=edges_type,
            edges_r_value=edges_r_value,
            edges_angle_value=edges_angle_value,
            edges_price_netto=edges_price_netto,
            edges_price_brutto=edges_price_brutto,
            edges_svg=edges_svg,
            edges_mode=edges_mode,
            shape=shape,
            shape_data=shape_data_json,
            shape_svg=shape_svg,
            round_surcharge_netto=round_surcharge_netto,
            round_surcharge_brutto=round_surcharge_brutto,
            lamella_direction=lamella_direction,
            cut_to_size=cut_to_size,
            product_type=product_type,
        )
        db.session.add(detail)

    # Usun stare warianty dla tego produktu
    QuoteItem.query.filter_by(quote_id=quote.id, product_index=idx).delete()

    # Dodaj nowe warianty
    for variant in product_data.get('variants', []):
        # Obsluga dwoch formatow:
        # Format A (load_quote): unit_price_netto/brutto (cena jednostkowa)
        # Format B (frontend): final_price_netto/brutto (cena calkowita za ilosc)
        # UWAGA: galaz "unit_price_netto" jest defensywna — realny frontend
        # (calculator-api.js/save_quote.js) zawsze wysyla final_price_netto
        # (Format B). Ta galaz obsluguje tylko Format A (np. load_quote_for_edit
        # / inne wewnetrzne wywolania), nie usuwac bez potwierdzenia braku uzycia.
        if 'unit_price_netto' in variant:
            unit_price_netto = variant.get('unit_price_netto', 0)
            unit_price_brutto = variant.get('unit_price_brutto', 0)
        else:
            final_netto = variant.get('final_price_netto', 0)
            final_brutto = variant.get('final_price_brutto', 0)
            unit_price_netto = _round_price(
                _to_decimal(final_netto) / Decimal(quantity)
            ) if quantity > 0 else 0
            unit_price_brutto = _round_price(
                _to_decimal(final_brutto) / Decimal(quantity)
            ) if quantity > 0 else 0

        is_available = variant.get('show_on_client_page',
                                   variant.get('is_available', True))

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
            show_on_client_page=is_available,
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


def _payload_to_calc_request(data):
    """Mapuje payload z save_quote/update_quote na request calculate_quote.
    Ceny z frontu celowo NIE przechodzą — backend liczy od zera.

    Obsluguje oba formaty produktu:
    - Format B (save_quote/frontend): finishing_type/finishing_variant/...,
      edges = lista krawedzi, edges_mode osobno.
    - Format A (edycja/load_quote_for_edit): finishing = dict
      {type, variant, color, gloss, priceNetto, priceBrutto},
      edges = dict {config, type, mode, netto, brutto, ...}.
    """
    products = []
    for i, product in enumerate(data.get('products', [])):
        selected = None
        for v in product.get('variants', []):
            if v.get('is_selected'):
                selected = v.get('variant_code')

        holes = 0
        sd = product.get('shape_data')
        if sd:
            try:
                sd_obj = _json.loads(sd) if isinstance(sd, str) else sd
                holes = len(sd_obj.get('holes') or [])
            except Exception:
                pass

        # Wykonczenie: Format A (dict) vs Format B (plaskie klucze)
        finishing_raw = product.get('finishing')
        if isinstance(finishing_raw, dict):
            finishing_type = finishing_raw.get('type')
            finishing_variant = finishing_raw.get('variant')
            finishing_color = finishing_raw.get('color')
            finishing_gloss_level = finishing_raw.get('gloss')
        else:
            finishing_type = product.get('finishing_type')
            finishing_variant = product.get('finishing_variant')
            finishing_color = product.get('finishing_color')
            finishing_gloss_level = product.get('finishing_gloss_level')

        # Krawedzie: Format A (dict z 'config') vs Format B (lista)
        edges_raw = product.get('edges')
        if isinstance(edges_raw, dict):
            edges_list = edges_raw.get('config')
            edges_mode = edges_raw.get('mode')
        else:
            edges_list = edges_raw
            edges_mode = product.get('edges_mode')

        products.append({
            'index': product.get('index', i + 1),
            'length': product.get('length'),
            'width': product.get('width'),
            'thickness': product.get('thickness'),
            'quantity': product.get('quantity', 1),
            'shape': product.get('shape', 'rectangular'),
            'shape_data': product.get('shape_data'),
            'holes_count': holes,
            'selected_variant': selected,
            'finishing_type': finishing_type,
            'finishing_variant': finishing_variant,
            'finishing_color': finishing_color,
            'finishing_gloss_level': finishing_gloss_level,
            'finishing_option_id': product.get('finishing_option_id'),
            'finishing_full_path': product.get('finishing_full_path'),
            'edges': edges_list,
            'edges_mode': edges_mode,
        })

    # Ustawienia calej wyceny: Format B (save_quote) trzyma je na plasko
    # w gornym poziomie payloadu; Format A (update_quote/edycja) zagniezdza
    # je w 'settings' (patrz save_quote.js - payload.settings.{clientType,
    # multiplier, shippingNetto, shippingBrutto}). Format A ma pierwszenstwo
    # gdy 'settings' jest obecne, bo klucze plaskie tam nie wystepuja.
    settings = data.get('settings')
    if isinstance(settings, dict):
        client_type = settings.get('clientType')
        multiplier_raw = settings.get('multiplier')
        shipping_netto = settings.get('shippingNetto', 0)
        shipping_brutto = settings.get('shippingBrutto', 0)
    else:
        client_type = data.get('quote_client_type')
        multiplier_raw = data.get('quote_multiplier')
        shipping_netto = data.get('shipping_cost_netto', 0)
        shipping_brutto = data.get('shipping_cost_brutto', 0)

    return {
        'client_type': client_type,
        # 'multiplier' celowo zawsze None: resolve_multiplier() w pricing_service
        # rozstrzyga mnoznik na podstawie client_type (grupa cenowa). Explicit
        # multiplier w resolve_multiplier() to sciezka dla partnera z fixed
        # mnoznikiem, ale frontend nigdy nie wysyla is_partner_fixed/tego trybu —
        # martwa galaz (is_partner_fixed) usunieta, multiplier_raw z payloadu
        # swiadomie ignorowany, zeby nie omijac walidacji client_type.
        'multiplier': None,
        'products': products,
        'shipping': {'netto': shipping_netto,
                     'brutto': shipping_brutto},
    }


def _inject_backend_prices(products, calc):
    """Nadpisuje ceny w liscie produktow (mutuje in-place) wynikami calculate_quote.
    Payload frontu (finishing_netto/edges_netto/final_price_netto/volume_m3/...)
    jest ignorowany — jedynym zrodlem prawdy o cenach jest `calc`.
    """
    calc_by_index = {p['index']: p for p in calc['products']}
    for i, product in enumerate(products):
        cp = calc_by_index.get(product.get('index', i + 1))
        if not cp:
            continue
        product['finishing_netto'] = cp['finishing']['netto']
        product['finishing_brutto'] = cp['finishing']['brutto']
        product['edges_netto'] = cp['edges']['netto']
        product['edges_brutto'] = cp['edges']['brutto']
        calc_variants = {v['variant_code']: v for v in cp['variants']}
        for variant in product.get('variants', []):
            cv = calc_variants.get(variant.get('variant_code'))
            if cv and cv.get('available'):
                variant['final_price_netto'] = cv['total_netto']
                variant['final_price_brutto'] = cv['total_brutto']
                variant['volume_m3'] = cv['volume_m3']
                variant['price_per_m3'] = cv['price_per_m3']
                variant['multiplier'] = cv['multiplier']


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

        if not products:
            return {"success": False, "error": "Brakuje produktow."}, 400

        # === BACKEND LICZY CENY — payload frontu jest tylko parametrami ===
        # Wykonane PRZED obsluga klienta (tworzenie Clienta), zeby przy bledzie
        # walidacji (return 400) nie zostal osierocony wpis Client w DB.
        from modules.calculator.services.pricing_service import (
            load_pricing_data, calculate_quote as calc_quote,
        )
        pricing_data = load_pricing_data()
        calc = calc_quote(_payload_to_calc_request(data), pricing_data)
        if not calc['ok']:
            return {"success": False, "error": "Błędy walidacji wyceny",
                    "errors": calc['errors']}, 400

        # Nadpisz ceny w payload wynikami backendu (per produkt / wariant)
        _inject_backend_prices(products, calc)
        data['total_price'] = calc['totals']['total_brutto']
        total_price = data['total_price']
        # quote_multiplier zapisywany do Quote to wartosc rozstrzygnieta przez
        # backend (grupa cenowa lub partner fixed), NIE surowy payload frontu.
        quote_multiplier = calc['multiplier']

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
            edges_mode = product.get('edges_mode')
            edges_type = product.get('edges_type')
            edges_r_value = product.get('edges_r_value')
            edges_angle_value = product.get('edges_angle_value')
            edges_price_netto = float(product.get('edges_netto', 0.0))
            edges_price_brutto = float(product.get('edges_brutto', 0.0))

            if edges_data:
                if edges_mode == 'advanced':
                    # Mieszane typy — sentinel
                    edges_type = 'mixed'
                    edges_r_value = None
                    edges_angle_value = None
                else:
                    # Basic / legacy — fallback z payloadu lub z pierwszego elementu
                    if not edges_type:
                        edges_type = edges_data[0].get('type')
                    if edges_r_value is None:
                        edges_r_value = edges_data[0].get('r_value')
                    if edges_angle_value is None and edges_type == 'chamfer':
                        edges_angle_value = edges_data[0].get('angle_value')
                current_app.logger.info(
                    f"[save_quote] Produkt #{i + 1}: {len(edges_data)} krawędzi, "
                    f"mode={edges_mode}, typ={edges_type}, R={edges_r_value}, kąt={edges_angle_value}, "
                    f"netto={edges_price_netto}, brutto={edges_price_brutto}"
                )

            edges_svg = product.get('edges_svg', '')

            # Kształt produktu i dopłata za okrągły/koło/elipsa
            product_shape = product.get('shape', 'rectangular')
            product_shape_data = product.get('shape_data')
            product_shape_svg = product.get('shape_svg')
            lamella_direction = product.get('lamella_direction')
            if lamella_direction is not None and lamella_direction not in (0, 45, 90, 135):
                lamella_direction = None
            round_surcharge_netto = 0
            round_surcharge_brutto = 0
            if product_shape in ('round', 'circle'):
                surcharge_per_unit = _to_decimal(
                    CalculatorSetting.get_value('round_shape_surcharge_netto', '50.00')
                )
                round_surcharge_netto = _round_price(surcharge_per_unit * Decimal(product_quantity))
                round_surcharge_brutto = _round_price(
                    _to_decimal(round_surcharge_netto) * Decimal('1.23')
                )

            # Docięcie do wymiaru (default True — klient dostaje produkt docięty)
            cut_to_size = _coerce_cut_to_size(product)

            # Szczegóły produktu (wykończenie + krawędzie + kształt)
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
                edges_mode=edges_mode,
                edges_type=edges_type,
                edges_r_value=edges_r_value,
                edges_angle_value=edges_angle_value,
                edges_price_netto=edges_price_netto,
                edges_price_brutto=edges_price_brutto,
                edges_svg=edges_svg if edges_svg else None,
                shape=product_shape,
                shape_data=product_shape_data,
                shape_svg=product_shape_svg if product_shape_svg else None,
                round_surcharge_netto=round_surcharge_netto,
                round_surcharge_brutto=round_surcharge_brutto,
                lamella_direction=lamella_direction,
                cut_to_size=cut_to_size,
                # Koncept sklepu (blat|schody|parapet) — CRM nie interpretuje, tylko przechowuje
                # do round-tripu w /api/bot/quotes/by-token. Brak klucza (kalkulator CRM) => None.
                product_type=product.get('product_type'),
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
