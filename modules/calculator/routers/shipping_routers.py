# modules/calculator/routers/shipping_routers.py
"""
Routery wysyłki - wyceny kurierskie GlobKurier.
"""

from flask import request, jsonify, current_app
from modules.users.decorators import require_module_access
from modules.calculator.services.shipping_service import get_shipping_quotes
from modules.calculator.services.shipping_pricing import (
    build_markup_payload, load_shipping_config, parse_markup_request,
)


def register_routes(bp):
    """Rejestruje trasy wysyłki na podanym blueprint."""

    @bp.route('/shipping_quote', methods=['POST'])
    @require_module_access('calculator')
    def shipping_quote():
        current_app.logger.info(">>> shipping_quote: endpoint wywołany")

        shipping_params = request.get_json()
        if not shipping_params:
            current_app.logger.error(">>> shipping_quote: Brak danych wysyłki")
            return jsonify({"success": False, "error": "Brak danych wysylki"}), 400

        glob_config = current_app.config.get("GLOB_KURIER")
        if not glob_config:
            current_app.logger.error(">>> shipping_quote: Brak konfiguracji GlobKURIER")
            return jsonify({"success": False, "error": "Brak konfiguracji serwisu kurierskiego"}), 500

        result, status_code = get_shipping_quotes(shipping_params, glob_config)
        return jsonify(result), status_code

    @bp.route('/api/shipping-markup', methods=['POST'])
    @require_module_access('calculator', as_json=True)
    def shipping_markup():
        """Przelicza surowe ceny brutto z GlobKuriera na ceny koncowe wg ustawien
        z panelu (narzut % + doplata progowa).

        Osobny endpoint, a nie policzenie tego od razu w /shipping_quote, bo cache
        wysylki w localStorage trzyma ceny SUROWE (TTL 24 h). Dzieki temu zmiana
        ustawien dziala natychmiast, bez ponownego — wolnego — odpytywania kuriera.
        """
        payload = request.get_json(silent=True)
        ceny, blad = parse_markup_request(payload)

        if blad is not None:
            current_app.logger.warning(">>> shipping_markup: brak cen do przeliczenia")
            return jsonify({"success": False, "error": blad}), 400

        return jsonify(build_markup_payload(ceny, load_shipping_config())), 200
