"""
API bota AI (Chatwoot/chat_bridge) — wyceny przez tę samą logikę co UI.
Auth: nagłówek X-Bot-Api-Key vs BOT_API_KEY z config/core.json.
Wyceny podpisywane kontem BOT_USER_ID ("Asystent AI").
Odpowiedzi projektowane pod LLM: zawsze {ok, ...}, błędy z {code, message PL, field}.
"""

import hmac
from functools import wraps
from flask import Blueprint, request, jsonify, current_app

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
    if missing:
        return jsonify({'ok': False, 'missing_fields': missing, 'errors': []}), 200

    result = calculate_quote(payload, load_pricing_data())
    result['missing_fields'] = []
    return jsonify(result), 200


@bot_api_bp.route('/clients/find-or-create', methods=['POST'])
@require_bot_api_key
def bot_find_or_create_client():
    """Dopasowuje klienta po e-mailu, potem telefonie; zakłada nowego gdy brak."""
    from extensions import db
    from modules.clients.models import Client
    payload = request.get_json(silent=True) or {}
    email = (payload.get('email') or '').strip() or None
    phone = (payload.get('phone') or '').strip() or None
    name = (payload.get('name') or '').strip() or None

    if not email and not phone:
        return jsonify({'ok': False, 'errors': [
            {'field': 'email', 'code': 'MISSING',
             'message': 'Podaj e-mail lub telefon klienta, żeby dopasować lub założyć klienta.'}
        ]}), 200

    client = None
    if email:
        client = Client.query.filter_by(email=email).first()
    if not client and phone:
        client = Client.query.filter_by(phone=phone).first()
    if client:
        return jsonify({'ok': True, 'matched': True, 'created': False,
                        'client': {'id': client.id, 'client_name': client.client_name,
                                   'email': client.email, 'phone': client.phone}}), 200

    if not name:
        name = email or phone
    # client_number jest unikalny — dla klientów z czatu użyj nazwy/e-maila
    base_number = name
    number = base_number
    suffix = 1
    while Client.query.filter_by(client_number=number).first():
        suffix += 1
        number = f'{base_number} ({suffix})'
    client = Client(client_number=number, client_name=name, email=email, phone=phone,
                    created_by_user_id=current_app.config.get('BOT_USER_ID'),
                    source='Asystent AI')
    db.session.add(client)
    db.session.commit()
    return jsonify({'ok': True, 'matched': False, 'created': True,
                    'client': {'id': client.id, 'client_name': client.client_name,
                               'email': client.email, 'phone': client.phone}}), 200


@bot_api_bp.route('/quotes', methods=['POST'])
@require_bot_api_key
def bot_create_quote():
    """Tworzy pełnoprawną wycenę w CRM. Body jak /calculate + client_id (+ opcjonalnie notes).
    Zwraca numer wyceny i publiczny link dla klienta."""
    from modules.users.models import User
    from modules.calculator.models import Quote
    from modules.calculator.services.quote_service import create_quote

    payload = request.get_json(silent=True) or {}
    if not payload.get('client_id'):
        return jsonify({'ok': False, 'errors': [
            {'field': 'client_id', 'code': 'MISSING',
             'message': 'Brak client_id — najpierw wywołaj /clients/find-or-create.'}
        ]}), 200

    bot_user = User.query.get(current_app.config.get('BOT_USER_ID') or 0)
    if not bot_user:
        return jsonify({'ok': False, 'errors': [
            {'field': None, 'code': 'BOT_USER_NOT_CONFIGURED',
             'message': 'Konto bota nie jest skonfigurowane (BOT_USER_ID).'}
        ]}), 500

    # Przekształć payload bota (products jak w /calculate) na format create_quote:
    # bot podaje tylko selected_variant — create_quote i tak przeliczy wszystko (Task 10),
    # ale potrzebuje struktury variants z is_selected.
    for p in payload.get('products', []):
        if 'variants' not in p:
            p['variants'] = [{'variant_code': p.get('selected_variant'), 'is_selected': True}]
    payload.setdefault('quote_client_type', payload.pop('client_type', None))
    payload.setdefault('quote_note', payload.pop('notes', ''))
    payload.setdefault('quote_source', 'Asystent AI')

    result, status = create_quote(payload, bot_user.email)
    if status != 200:
        errors = result.get('errors') or [{'field': None, 'code': 'SAVE_FAILED',
                                           'message': result.get('error', 'Błąd zapisu wyceny.')}]
        return jsonify({'ok': False, 'errors': errors}), 200

    quote = Quote.query.get(result['quote_id'])
    base_url = current_app.config.get('APP_BASE_URL', 'https://crm.woodpower.pl')
    return jsonify({'ok': True, 'quote_number': result['quote_number'],
                    'quote_id': result['quote_id'],
                    'public_url': base_url + quote.get_public_url()}), 200
