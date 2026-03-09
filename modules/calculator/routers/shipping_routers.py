# modules/calculator/routers/shipping_routers.py
"""
Routery wysyłki - wyceny kurierskie GlobKurier.
"""

from flask import request, jsonify, current_app
from modules.users.decorators import require_module_access
from modules.calculator.services.shipping_service import get_shipping_quotes


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
