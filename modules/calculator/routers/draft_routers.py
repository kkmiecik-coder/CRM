# modules/calculator/routers/draft_routers.py
"""
Endpointy API dla draftow kalkulatora (server-side backup).
"""

from flask import request, jsonify, session
from modules.users.decorators import require_module_access
from modules.calculator.services.draft_service import save_draft, load_draft, delete_draft


def register_routes(bp):

    @bp.route('/api/draft', methods=['PUT'])
    @require_module_access('calculator')
    def api_draft_save():
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': 'Brak sesji'}), 401

        data = request.get_json()
        if not data or 'draft_data' not in data:
            return jsonify({'success': False, 'error': 'Brak danych draftu'}), 400

        result, status_code = save_draft(user_id, data['draft_data'])
        return jsonify(result), status_code

    @bp.route('/api/draft', methods=['GET'])
    @require_module_access('calculator')
    def api_draft_load():
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': 'Brak sesji'}), 401

        result, status_code = load_draft(user_id)
        return jsonify(result), status_code

    @bp.route('/api/draft', methods=['DELETE'])
    @require_module_access('calculator')
    def api_draft_delete():
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': 'Brak sesji'}), 401

        result, status_code = delete_draft(user_id)
        return jsonify(result), status_code
