# modules/calculator/routers/finishing_routers.py
"""
Routery wykończeń - pobieranie cen wykończeń.
"""

from flask import jsonify
from modules.users.decorators import require_module_access
from modules.calculator.services.pricing_service import get_finishing_prices_data


def register_routes(bp):
    """Rejestruje trasy wykończeń na podanym blueprint."""

    @bp.route('/api/finishing-prices', methods=['GET'])
    @require_module_access('calculator')
    def get_finishing_prices():
        """Pobieranie cen wykończeń z bazy danych - hierarchiczne drzewko"""
        result, status_code = get_finishing_prices_data()
        return jsonify(result), status_code
