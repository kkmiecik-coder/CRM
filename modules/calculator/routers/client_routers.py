# modules/calculator/routers/client_routers.py
"""
Routery klientów - wyszukiwanie klientów z kalkulatora.
"""

from flask import request, jsonify, session
from modules.users.models import User
from modules.users.decorators import require_module_access
from modules.calculator.services.client_service import search_clients_by_term


def register_routes(bp):
    """Rejestruje trasy klientów na podanym blueprint."""

    @bp.route('/search_clients', methods=['GET'])
    @require_module_access('calculator')
    def search_clients():
        term = request.args.get('q', '').strip()
        if len(term) < 3:
            return jsonify([])

        user_id = session.get('user_id')
        if not user_id:
            return jsonify([])

        user = User.query.get(user_id)
        if not user:
            return jsonify([])

        result = search_clients_by_term(term, user_id)
        return jsonify(result)
