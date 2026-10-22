# -*- coding: utf-8 -*-
"""Stan drukarek dla tabletów stanowisk (`/api/mobile/printers`). Tylko odczyt, bez blokad i commitów."""
from flask import Blueprint, g, jsonify

from modules.production.drukarki.services import stan
from modules.production.services.mobile_api_service import require_device_token
from modules.production.services.station_catalog import resolve_station_code

drukarki_mobile_bp = Blueprint('drukarki_mobile', __name__)


@drukarki_mobile_bp.route('/status', methods=['GET'])
@require_device_token
def status():
    kod = resolve_station_code(g.device.station_code)
    dane = stan.migawka()
    dane['drukarki'] = [d for d in dane['drukarki'] if kod in stan.stanowiska_drukarki(d['nazwa'])]
    odpowiedz = jsonify(dane)
    odpowiedz.headers['Cache-Control'] = 'no-store'
    return odpowiedz
