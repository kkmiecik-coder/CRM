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
