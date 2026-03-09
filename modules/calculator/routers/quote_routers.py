# modules/calculator/routers/quote_routers.py
"""
Routery wycen - zapis, ladowanie i aktualizacja wycen.
"""

from flask import request, jsonify, session, current_app
from flask_login import login_required, current_user
from modules.calculator.models import User, QuoteSource
from modules.users.decorators import require_module_access
from modules.calculator.services.quote_service import (
    create_quote, load_quote_for_edit, update_quote
)


def register_routes(bp):
    """Rejestruje trasy wycen na podanym blueprint."""

    @bp.route('/save_quote', methods=['POST'])
    @require_module_access('calculator')
    def save_quote():
        user_email = session.get('user_email')
        if not user_email:
            current_app.logger.warning("[save_quote] Brak sesji użytkownika.")
            return jsonify({"success": False, "error": "Brak sesji uzytkownika."}), 401

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Brak danych wyceny"}), 400
        result, status_code = create_quote(data, user_email)
        return jsonify(result), status_code

    @bp.route('/api/load_quote/<edit_uuid>', methods=['GET'])
    @require_module_access('calculator')
    def load_quote(edit_uuid):
        """Laduje dane wyceny do edycji w kalkulatorze."""
        try:
            result, status_code = load_quote_for_edit(edit_uuid, current_user)
            return jsonify(result), status_code
        except Exception as e:
            current_app.logger.error(f"[load_quote] Blad: {str(e)}")
            return jsonify({"success": False, "error": "Blad ladowania wyceny"}), 500

    @bp.route('/api/update_quote/<edit_uuid>', methods=['PUT'])
    @require_module_access('calculator')
    def update_quote_endpoint(edit_uuid):
        """Aktualizuje istniejaca wycene na podstawie danych z kalkulatora."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"success": False, "error": "Brak danych aktualizacji"}), 400
            result, status_code = update_quote(edit_uuid, data, current_user)
            return jsonify(result), status_code
        except Exception as e:
            current_app.logger.error(f"[update_quote] Blad: {str(e)}")
            return jsonify({"success": False, "error": "Blad aktualizacji wyceny"}), 500

    @bp.route('/api/quote-sources', methods=['GET'])
    @require_module_access('calculator')
    def get_quote_sources():
        """Pobiera źródła wycen dostępne dla aktualnego użytkownika."""
        try:
            user_email = session.get('user_email')
            user = User.query.filter_by(email=user_email).first() if user_email else None

            user_role = user.role if user else None
            is_flexible_partner = user_role == 'flexible_partner' if user_role else False

            if user_role:
                sources = QuoteSource.get_sources_for_user(user_role, is_flexible_partner)
            else:
                sources = QuoteSource.query.filter_by(is_active=True).order_by(
                    QuoteSource.sort_order
                ).all()

            return jsonify({
                'success': True,
                'sources': [{
                    'id': s.id,
                    'name': s.name,
                    'skip_contact_validation': s.skip_contact_validation,
                } for s in sources]
            })

        except Exception as e:
            current_app.logger.error(f"[get_quote_sources] Błąd: {str(e)}")
            return jsonify({"success": False, "error": "Blad pobierania zrodel wycen"}), 500
