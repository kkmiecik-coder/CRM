# modules/calculator/routers/main_routers.py
"""
Główne routery kalkulatora - strona główna i ustawienia.
"""

import json
import traceback
from flask import render_template, session, jsonify, current_app, request
from sqlalchemy import text
from extensions import db
from modules.calculator.models import Multiplier, User
from modules.users.decorators import require_module_access


def register_routes(bp):
    """Rejestruje trasy główne na podanym blueprint."""

    @bp.route('/', methods=['GET', 'POST'])
    @require_module_access('calculator')
    def calculator_home():
        user_email = session.get('user_email')
        user_id = session.get('user_id')

        user = User.query.filter_by(email=user_email).first()
        user_role = user.role
        user_multiplier = user.multiplier.multiplier if user.multiplier else 1.0
        user_client_type = user.multiplier.client_type if user.multiplier else None

        prices_query = db.session.execute(text("""
            SELECT species, technology, wood_class, thickness_min, thickness_max,
                   length_min, length_max, width_min, width_max, price_per_m3
            FROM prices
        """)).fetchall()
        prices_list = [dict(row._mapping) for row in prices_query]
        for row in prices_list:
            for key in ['thickness_min', 'thickness_max', 'length_min', 'length_max',
                         'width_min', 'width_max', 'price_per_m3']:
                if key in row and row[key] is not None:
                    row[key] = float(row[key])
        prices_json = json.dumps(prices_list)

        # Konfiguracja flexible partners
        FLEXIBLE_PARTNER_IDS = [14, 15]
        # Flexible partnerzy mają dostępny tylko mnożnik id 11 (Czernecki, 1.05)
        FLEXIBLE_PARTNER_ALLOWED_MULTIPLIERS = {
            14: [11],
            15: [11],
        }

        if user_role == 'partner' and user_id in FLEXIBLE_PARTNER_IDS:
            allowed_ids = FLEXIBLE_PARTNER_ALLOWED_MULTIPLIERS.get(user_id, [])
            multipliers_query = Multiplier.query.filter(Multiplier.id.in_(allowed_ids)).all()
        else:
            multipliers_query = Multiplier.query.all()

        multipliers_list = [
            {"id": m.id, "label": m.client_type, "value": m.multiplier}
            for m in multipliers_query
        ]
        multipliers_json = json.dumps(multipliers_list)

        is_flexible_partner = (user_role == 'partner' and user_id in FLEXIBLE_PARTNER_IDS)

        return render_template(
            "calculator.html",
            user_email=user_email,
            user_id=user_id,
            prices_json=prices_json,
            multipliers_json=multipliers_json,
            user_role=user_role,
            user_multiplier=user_multiplier,
            user_client_type=user_client_type,
            is_flexible_partner=is_flexible_partner,
        )

    @bp.route('/api/calculate', methods=['POST'])
    @require_module_access('calculator')
    def calculate():
        """Liczy pełny breakdown wyceny — jedyne źródło cen dla UI kalkulatora."""
        from modules.calculator.services.pricing_service import (
            load_pricing_data, calculate_quote,
        )
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({'ok': False, 'errors': [
                {'field': None, 'code': 'BAD_REQUEST', 'message': 'Brak danych wyceny.'}
            ]}), 400
        try:
            data = load_pricing_data()
            result = calculate_quote(payload, data)
            return jsonify(result), 200
        except Exception as e:
            current_app.logger.exception(f'[calculate] Błąd: {e}')
            return jsonify({'ok': False, 'errors': [
                {'field': None, 'code': 'INTERNAL', 'message': 'Błąd serwera podczas liczenia wyceny.'}
            ]}), 500

    @bp.route('/api/import-dxf', methods=['POST'])
    def import_dxf():
        """Importuje plik DXF i zwraca listę produktów."""
        try:
            if 'file' not in request.files:
                return jsonify({'error': 'Brak pliku w żądaniu.'}), 400

            file = request.files['file']

            if not file.filename or not file.filename.lower().endswith('.dxf'):
                return jsonify({'error': 'Nieprawidłowy format pliku. Wymagany plik .dxf.'}), 400

            file_bytes = file.read()

            max_size = 10 * 1024 * 1024  # 10 MB
            if len(file_bytes) > max_size:
                return jsonify({'error': 'Plik jest za duży. Maksymalny rozmiar to 10 MB.'}), 400

            from modules.calculator.services.dxf_import_service import parse_dxf
            result = parse_dxf(file_bytes)

            return jsonify(result)

        except Exception as e:
            current_app.logger.error(
                f"[import_dxf] Błąd podczas importu DXF: {str(e)}\n{traceback.format_exc()}"
            )
            return jsonify({'error': f'Błąd podczas przetwarzania pliku DXF: {str(e)}'}), 500
