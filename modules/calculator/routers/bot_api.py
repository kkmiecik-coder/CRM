"""
API bota AI (Chatwoot/chat_bridge) — wyceny przez tę samą logikę co UI.
Auth: nagłówek X-Bot-Api-Key vs BOT_API_KEY z config/core.json.
Wyceny podpisywane kontem BOT_USER_ID ("Asystent AI").
Odpowiedzi projektowane pod LLM: zawsze {ok, ...}, błędy z {code, message PL, field}.
"""

import hmac
import re
from functools import wraps
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

bot_api_bp = Blueprint('bot_api', __name__)


def _check_api_key(provided, expected):
    """Stałoczasowe porównanie klucza; brak skonfigurowanego klucza = dostęp zamknięty."""
    if not provided or not expected:
        return False
    return hmac.compare_digest(str(provided), str(expected))


def require_bot_api_key(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        expected = current_app.config.get('BOT_API_KEY')
        if not _check_api_key(request.headers.get('X-Bot-Api-Key'), expected):
            return jsonify({'ok': False, 'errors': [
                {'field': None, 'code': 'UNAUTHORIZED', 'message': 'Nieprawidłowy klucz API.'}
            ]}), 401
        return f(*args, **kwargs)
    return wrapper


_POSTCODE_RE = re.compile(r"^\d{2}-\d{3}$")


def _valid_receiver_postcode(v):
    """Kod pocztowy odbiorcy w formacie 00-000 (GlobKurier wymaga kodu, nie samej nazwy miasta)."""
    return bool(_POSTCODE_RE.match(str(v or "").strip()))


@bot_api_bp.route('/options', methods=['GET'])
@require_bot_api_key
def bot_options():
    """Słowniki dla LLM: co wolno wybrać (warianty, zakresy, wykończenia, krawędzie, grupy)."""
    # Reuse: _pricing_limits jest prywatny (podkreślnik) w pricing_service, ale to
    # świadomy import — liczy dokładnie te same globalne min/max co UI kalkulatora,
    # nie chcemy duplikować logiki dla bota.
    from modules.calculator.services.pricing_service import (
        load_pricing_data, VARIANT_MAPPING, _pricing_limits,
    )
    data = load_pricing_data()

    # Zakresy per wariant — LLM widzi, które kombinacje istnieją w cenniku
    variants = []
    for code, cfg in VARIANT_MAPPING.items():
        entries = [e for e in data.price_entries
                   if e['species'] == cfg['species']
                   and e['technology'] == cfg['technology']
                   and e['wood_class'] == cfg['wood_class']]
        if not entries:
            continue
        variants.append({
            'variant_code': code, **cfg,
            'length_min': min(e['length_min'] for e in entries),
            'length_max': max(e['length_max'] for e in entries),
            'width_min': min(e['width_min'] for e in entries),
            'width_max': max(e['width_max'] for e in entries),
            'thickness_min': min(e['thickness_min'] for e in entries),
            'thickness_max': max(e['thickness_max'] for e in entries),
        })

    finishing = [
        {'id': o['id'], 'full_path': o['full_path'], 'price_netto': o.get('price_netto'),
         'level': o.get('level')}
        for o in data.finishing_options_by_id.values()
        if o.get('code') != 'CUTOUT' and o.get('inherited_code') != 'CUTOUT'
    ]

    return jsonify({
        'ok': True,
        'variants': variants,
        'global_limits': _pricing_limits(data),
        'finishing_options': finishing,
        'edge_types': [{'type': t, **p} for t, p in data.edge_prices.items()],
        'client_types': sorted(data.multipliers.keys()),
        'cutout_price_netto': data.cutout_price_netto,
        'round_surcharge_netto': data.round_surcharge_netto,
        'shapes': ['rectangular', 'round', 'circle'],
        'vat': 1.23,
    })


_REQUIRED_PRODUCT_FIELDS = ['length', 'width', 'thickness', 'quantity', 'selected_variant']

_FIELD_HINTS_PL = {
    'length': 'długość w cm', 'width': 'szerokość w cm', 'thickness': 'grubość w cm',
    'quantity': 'ilość sztuk', 'selected_variant': 'wariant drewna (variant_code z /options)',
}


def _missing_fields(product):
    return [f for f in _REQUIRED_PRODUCT_FIELDS if not product.get(f)]


def _quote_level_missing(payload, alt_field=None):
    """Braki na poziomie całej wyceny (nie produktu) — na razie tylko client_type.
    W /calculate klucz to 'client_type', w /quotes bot może podać 'quote_client_type'
    (alt_field) — akceptujemy oba, brak obu = pole do dopytania."""
    missing = []
    has_client_type = bool(payload.get('client_type')) or (
        alt_field is not None and bool(payload.get(alt_field))
    )
    if not has_client_type:
        missing.append({'product_index': None, 'field': 'client_type',
                        'hint': 'grupa cenowa (client_types z /options)'})
    return missing


@bot_api_bp.route('/calculate', methods=['POST'])
@require_bot_api_key
def bot_calculate():
    """Liczy wycenę bez zapisu — bot podaje cenę w rozmowie."""
    from modules.calculator.services.pricing_service import load_pricing_data, calculate_quote
    payload = request.get_json(silent=True) or {}

    # Najpierw brakujące pola — LLM dostaje listę, o co dopytać klienta
    missing = []
    for i, p in enumerate(payload.get('products', [])):
        for f in _missing_fields(p):
            missing.append({'product_index': p.get('index', i + 1), 'field': f,
                            'hint': _FIELD_HINTS_PL[f]})
    if not payload.get('products'):
        missing.append({'product_index': None, 'field': 'products',
                        'hint': 'co najmniej jeden produkt z wymiarami'})
    missing.extend(_quote_level_missing(payload))
    if missing:
        return jsonify({'ok': False, 'missing_fields': missing, 'errors': []}), 200

    result = calculate_quote(payload, load_pricing_data())
    result['missing_fields'] = []
    return jsonify(result), 200


def _resolve_client(client_query, email, phone, name, client_number=None):
    """Dopasowanie klienta: najpierw e-mail/telefon (PRAWDZIWY powracajacy klient), DOPIERO gdy
    brak dopasowania i podano client_number — wlasny rekord techniczny (LS-01: lead bota
    zawsze ma klienta w CRM, nawet bez kontaktu). Zwraca (client_or_None, created_bool,
    matched_via) — matched_via = 'contact' TYLKO dla dopasowania po e-mailu/telefonie (to jedyny
    przypadek, w ktorym wolno pokazac klientowi 'widzimy wczesniejsze wyceny'; dopasowanie
    wlasnego leada po client_number to NIE powrot klienta — to pierwszy raz, gdy podaje kontakt).
    Nie tworzy tu nowego klienta — to robi wolajacy (rozne sciezki tworzenia)."""
    client = None
    if email:
        client = client_query.filter_by(email=email).first()
    if not client and phone:
        client = client_query.filter_by(phone=phone).first()
    if client:
        return client, False, "contact"
    if client_number:
        client = client_query.filter_by(client_number=client_number).first()
        if client:
            # Wlasny lead techniczny z tej samej rozmowy — kontakt WZBOGACA rekord,
            # niepusta nowa wartosc NIE nadpisuje juz ustawionej (biezaca wiadomosc
            # wygrywa juz wczesniej, w quotebot._set_contact, zanim API zostanie wolane).
            if email and not client.email:
                client.email = email
            if phone and not client.phone:
                client.phone = phone
            if name and client.client_name == client.client_number:
                client.client_name = name  # nazwa techniczna "chat-N" -> realna, gdy poznana
            return client, False, "client_number"
    return None, False, None


@bot_api_bp.route('/clients/find-or-create', methods=['POST'])
@require_bot_api_key
def bot_find_or_create_client():
    """Dopasowuje klienta po e-mailu, potem telefonie, potem (LS-01) po client_number
    technicznym 'chat-<conv_id>' — zaklada nowego gdy zaden nie pasuje."""
    from extensions import db
    from modules.clients.models import Client
    payload = request.get_json(silent=True) or {}
    email = (payload.get('email') or '').strip() or None
    phone = (payload.get('phone') or '').strip() or None
    name = (payload.get('name') or '').strip() or None
    client_number = (payload.get('client_number') or '').strip() or None

    if not email and not phone and not client_number:
        return jsonify({'ok': False, 'errors': [
            {'field': 'email', 'code': 'MISSING',
             'message': 'Podaj e-mail, telefon lub client_number, żeby dopasować lub założyć klienta.'}
        ]}), 200

    client, _, matched_via = _resolve_client(Client.query, email, phone, name, client_number)
    if client:
        try:
            db.session.commit()   # zapisz ewentualne wzbogacenie kontaktu technicznego leada
        except (IntegrityError, SQLAlchemyError):
            db.session.rollback()
        # 'matched' TYLKO dla prawdziwego powracajacego klienta (dopasowanie po e-mailu/
        # telefonie) — wlasny lead techniczny wzbogacony PIERWSZYM kontaktem klienta (matched_via
        # == 'client_number') to NIE powrot, bot nie moze pokazac "widzimy wczesniejsze wyceny".
        return jsonify({'ok': True, 'matched': matched_via == 'contact', 'created': False,
                        'client': {'id': client.id, 'client_name': client.client_name,
                                   'email': client.email, 'phone': client.phone}}), 200

    if not name:
        name = email or phone or client_number
    if client_number:
        # Konwencja chat-<conv_id> jest unikalna per rozmowa — bez petli disambiguacji
        # jak dla klientow z e-maila/nazwy (kolizja by oznaczala blad wolajacego).
        number = client_number
    else:
        # client_number jest unikalny — dla klientów z czatu użyj nazwy/e-maila
        base_number = name
        number = base_number
        suffix = 1
        while Client.query.filter_by(client_number=number).first():
            suffix += 1
            number = f'{base_number} ({suffix})'

    # Konto bota może nie istnieć w DB (BOT_USER_ID=0 lub nieustawione) — created_by_user_id
    # jest nullable, więc zamiast łamać FK po prostu zostawiamy None.
    from modules.users.models import User
    bot_user_id = current_app.config.get('BOT_USER_ID')
    if bot_user_id and not User.query.get(bot_user_id):
        bot_user_id = None

    try:
        client = Client(client_number=number, client_name=name, email=email, phone=phone,
                        created_by_user_id=bot_user_id,
                        source='Asystent AI')
        db.session.add(client)
        db.session.commit()
    except (IntegrityError, SQLAlchemyError):
        # Wyścig dwóch równoległych żądań z tym samym e-mailem/telefonem/client_number — jeden
        # proces wygrywa insert, drugi dostaje IntegrityError na unique client_number/email.
        # Zamiast wywalać globalny errorhandler (inny kształt JSON niż kontrakt bota),
        # cofamy transakcję i ponawiamy wyszukiwanie — przegrany wyścigu znajdzie zwycięzcę.
        db.session.rollback()
        client, _, matched_via = _resolve_client(Client.query, email, phone, name, client_number)
        if client:
            try:
                db.session.commit()   # zapisz ewentualne wzbogacenie kontaktu (przegrany wyscigu)
            except (IntegrityError, SQLAlchemyError):
                db.session.rollback()
            return jsonify({'ok': True, 'matched': matched_via == 'contact', 'created': False,
                            'client': {'id': client.id, 'client_name': client.client_name,
                                       'email': client.email, 'phone': client.phone}}), 200
        return jsonify({'ok': False, 'errors': [
            {'field': None, 'code': 'CLIENT_CONFLICT',
             'message': 'Nie udało się utworzyć klienta — konflikt danych. Spróbuj ponownie.'}
        ]}), 200

    return jsonify({'ok': True, 'matched': False, 'created': True,
                    'client': {'id': client.id, 'client_name': client.client_name,
                               'email': client.email, 'phone': client.phone}}), 200


@bot_api_bp.route('/quotes', methods=['POST'])
@require_bot_api_key
def bot_create_quote():
    """Tworzy pełnoprawną wycenę w CRM. Body jak /calculate + client_id (+ opcjonalnie notes).
    Zwraca numer wyceny i publiczny link dla klienta."""
    from modules.users.models import User
    from modules.clients.models import Client
    from modules.calculator.models import Quote
    from modules.calculator.services.quote_service import create_quote

    payload = request.get_json(silent=True) or {}
    if not payload.get('client_id'):
        return jsonify({'ok': False, 'errors': [
            {'field': 'client_id', 'code': 'MISSING',
             'message': 'Brak client_id — najpierw wywołaj /clients/find-or-create.'}
        ]}), 200

    # Jawny check klienta przed próbą zapisu — bez tego create_quote zwróciłby dopiero
    # błąd zapisu (np. FK), z mniej czytelnym kodem dla LLM.
    if not Client.query.get(payload['client_id']):
        return jsonify({'ok': False, 'errors': [
            {'field': 'client_id', 'code': 'CLIENT_NOT_FOUND',
             'message': f"Nie znaleziono klienta o id {payload['client_id']} — "
                        "najpierw wywołaj /clients/find-or-create."}
        ]}), 200

    missing = _quote_level_missing(payload, alt_field='quote_client_type')
    if missing:
        return jsonify({'ok': False, 'missing_fields': missing, 'errors': []}), 200

    # BOT_USER_ID nieustawiony/nieistniejący w DB — status 200 (spójnie z resztą kontraktu:
    # LLM czyta pole "ok", nie kody HTTP; kody 4xx/5xx zostawiamy realnym błędom transportu).
    bot_user = User.query.get(current_app.config.get('BOT_USER_ID') or 0)
    if not bot_user:
        return jsonify({'ok': False, 'errors': [
            {'field': None, 'code': 'BOT_USER_NOT_CONFIGURED',
             'message': 'Konto bota nie jest skonfigurowane (BOT_USER_ID).'}
        ]}), 200

    # Przekształć payload bota (products jak w /calculate) na format create_quote:
    # bot podaje tylko selected_variant — zapisujemy WSZYSTKIE warianty drewna (jak
    # z kalkulatora), z wybranym oznaczonym is_selected. create_quote/calculate_quote
    # policzą cenę każdego wariantu; klient widzi pełną tabelę do porównania.
    # Budujemy NOWY dict zamiast mutować payload in-place — czytelniej i odporne na to,
    # że payload mógłby być użyty ponownie przez wołający kod.
    quote_payload = dict(payload)
    quote_payload['products'] = _products_with_all_variants(payload)
    quote_payload.setdefault('quote_client_type', payload.get('client_type'))
    quote_payload.pop('client_type', None)
    quote_payload.setdefault('quote_note', payload.get('notes', ''))
    quote_payload.pop('notes', None)
    quote_payload.setdefault('quote_source', 'Asystent AI')

    result, status = create_quote(quote_payload, bot_user.email)
    if status != 200:
        errors = result.get('errors') or [{'field': None, 'code': 'SAVE_FAILED',
                                           'message': result.get('error', 'Błąd zapisu wyceny.')}]
        return jsonify({'ok': False, 'errors': errors}), 200

    quote = Quote.query.get(result['quote_id'])
    base_url = current_app.config.get('APP_BASE_URL', 'https://crm.woodpower.pl')
    # edit_uuid zwracamy, żeby bot mógł potem AKTUALIZOWAĆ tę wycenę (PUT /quotes/<edit_uuid>)
    # zamiast tworzyć nową przy dodaniu kolejnej pozycji.
    return jsonify({'ok': True, 'quote_number': result['quote_number'],
                    'quote_id': result['quote_id'], 'edit_uuid': quote.edit_uuid,
                    'public_url': base_url + quote.get_public_url()}), 200


def _products_with_all_variants(payload):
    """Rozwija każdy produkt bota (tylko selected_variant) na PEŁNĄ listę wariantów drewna
    z zaznaczonym wybranym — format wymagany przez create_quote/update_quote (jak z UI)."""
    from modules.calculator.services.pricing_service import VARIANT_MAPPING
    products = []
    for p in payload.get('products', []):
        p = dict(p)
        if 'variants' not in p:
            selected = p.get('selected_variant')
            p['variants'] = [{'variant_code': code, 'is_selected': (code == selected)}
                             for code in VARIANT_MAPPING]
        products.append(p)
    return products


def _shipping_settings(payload):
    """Mapuje pola wysylki z payloadu bota na klucze settings zrozumiale przez update_quote
    (courierName/shippingNetto/shippingBrutto). Pusty dict gdy bot nie przyslal kuriera."""
    if not payload.get('courier_name'):
        return {}
    return {
        'courierName': payload.get('courier_name'),
        'shippingNetto': payload.get('shipping_netto', 0),
        'shippingBrutto': payload.get('shipping_brutto', 0),
    }


@bot_api_bp.route('/quotes/<edit_uuid>', methods=['PUT'])
@require_bot_api_key
def bot_update_quote(edit_uuid):
    """Aktualizuje istniejącą wycenę (dodanie/zmiana pozycji) zamiast tworzyć nową.
    Body jak /quotes (products + quote_client_type/client_type), bez client_id."""
    from modules.users.models import User
    from modules.calculator.models import Quote
    from modules.calculator.services.quote_service import update_quote

    payload = request.get_json(silent=True) or {}
    quote = Quote.query.filter_by(edit_uuid=edit_uuid).first()
    if not quote:
        return jsonify({'ok': False, 'errors': [
            {'field': 'edit_uuid', 'code': 'QUOTE_NOT_FOUND',
             'message': f'Nie znaleziono wyceny {edit_uuid}.'}
        ]}), 200

    bot_user = User.query.get(current_app.config.get('BOT_USER_ID') or 0)
    if not bot_user:
        return jsonify({'ok': False, 'errors': [
            {'field': None, 'code': 'BOT_USER_NOT_CONFIGURED',
             'message': 'Konto bota nie jest skonfigurowane (BOT_USER_ID).'}
        ]}), 200

    # Format update_quote: settings.clientType + products z pełną listą wariantów.
    # Wysyłka (courier/koszt) — opcjonalnie, gdy bot dopisuje kuriera po oszacowaniu.
    client_type = payload.get('quote_client_type') or payload.get('client_type')
    settings = {'clientType': client_type, 'notes': payload.get('notes', '')}
    settings.update(_shipping_settings(payload))
    data = {'products': _products_with_all_variants(payload), 'settings': settings}

    result, status = update_quote(edit_uuid, data, bot_user)
    if status != 200 or not result.get('success'):
        errors = result.get('errors') or [{'field': None, 'code': 'UPDATE_FAILED',
                                           'message': result.get('error', 'Błąd aktualizacji wyceny.')}]
        return jsonify({'ok': False, 'errors': errors}), 200

    quote = Quote.query.get(result['quote_id'])
    base_url = current_app.config.get('APP_BASE_URL', 'https://crm.woodpower.pl')
    return jsonify({'ok': True, 'quote_number': result['quote_number'],
                    'quote_id': result['quote_id'], 'edit_uuid': quote.edit_uuid,
                    'public_url': base_url + quote.get_public_url()}), 200


@bot_api_bp.route('/shipping-quote', methods=['POST'])
@require_bot_api_key
def bot_shipping_quote():
    """Szacuje koszt wysylki (najtanszy kurier +30%) dla podanych produktow i kodu pocztowego
    odbiorcy. Wymiary/wage paczki liczy serwer (aggregate_package), przewoznikow pobiera GlobKurier.
    Kod nadawcy z GLOB_KURIER.sender_post_code (fallback 01-001)."""
    from modules.calculator.services.shipping_service import (
        aggregate_package, cheapest_with_packing, get_shipping_quotes,
    )
    payload = request.get_json(silent=True) or {}
    products = payload.get('products') or []
    receiver = (payload.get('receiver_postcode') or '').strip()

    if not products:
        return jsonify({'ok': False, 'errors': [
            {'field': 'products', 'code': 'MISSING', 'message': 'Brak produktów do wyceny wysyłki.'}
        ]}), 200
    if not _valid_receiver_postcode(receiver):
        return jsonify({'ok': False, 'errors': [
            {'field': 'receiver_postcode', 'code': 'BAD_POSTCODE',
             'message': 'Podaj kod pocztowy odbiorcy w formacie 00-000.'}
        ]}), 200

    glob_config = current_app.config.get('GLOB_KURIER')
    if not glob_config:
        return jsonify({'ok': False, 'errors': [
            {'field': None, 'code': 'NO_CONFIG',
             'message': 'Brak konfiguracji serwisu kurierskiego.'}
        ]}), 200

    params = aggregate_package(products)
    params['senderPostCode'] = glob_config.get('sender_post_code', '01-001')
    params['receiverPostCode'] = receiver

    result, status = get_shipping_quotes(params, glob_config)
    # get_shipping_quotes zwraca (list, 200) przy sukcesie albo (dict bledu, kod) przy problemie.
    if status != 200 or not isinstance(result, list):
        return jsonify({'ok': False, 'errors': [
            {'field': None, 'code': 'CARRIER_UNAVAILABLE',
             'message': 'Nie udało się teraz oszacować wysyłki.'}
        ]}), 200
    if not result:
        # Pusta lista = brak kuriera dla gabarytu (np. blat 450 cm powyzej limitu paczki).
        return jsonify({'ok': True, 'carriers': 0}), 200

    cheapest = cheapest_with_packing(result)
    if not cheapest:
        return jsonify({'ok': True, 'carriers': 0}), 200
    return jsonify({'ok': True, 'carriers': len(result), **cheapest}), 200
