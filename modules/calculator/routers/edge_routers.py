# modules/calculator/routers/edge_routers.py
"""
Routery obróbki krawędzi - opcje, definicje, kalkulacja.
"""

from flask import request, jsonify, current_app
from modules.users.decorators import require_module_access


def register_routes(bp):
    """Rejestruje trasy krawędzi na podanym blueprint."""

    @bp.route('/api/edge-options', methods=['GET'])
    @require_module_access('calculator')
    def get_edge_options():
        """Pobiera dostępne typy obróbki krawędzi z bazy danych"""
        try:
            from modules.calculator.models import EdgeOption

            options = EdgeOption.query.filter(
                (EdgeOption.is_active == True) | (EdgeOption.is_active.is_(None))
            ).order_by(EdgeOption.id).all()

            if not options:
                return jsonify([
                    {'id': 1, 'type': 'chamfer', 'name': 'Fazowanie', 'price_per_mb': 15.0,
                     'corner_price': 5.0, 'r_min': 3, 'r_max': 10, 'r_default': 3},
                    {'id': 2, 'type': 'round', 'name': 'Zaokrąglenie', 'price_per_mb': 15.0,
                     'corner_price': 5.0, 'r_min': 3, 'r_max': 20, 'r_default': 5},
                ])

            return jsonify([opt.to_dict() for opt in options])

        except Exception as e:
            current_app.logger.error(f"[get_edge_options] Błąd: {str(e)}")
            return jsonify([
                {'id': 1, 'type': 'chamfer', 'name': 'Fazowanie', 'price_per_mb': 15.0,
                 'corner_price': 5.0, 'r_min': 3, 'r_max': 10, 'r_default': 3},
                {'id': 2, 'type': 'round', 'name': 'Zaokrąglenie', 'price_per_mb': 15.0,
                 'corner_price': 5.0, 'r_min': 3, 'r_max': 20, 'r_default': 5},
            ])

    @bp.route('/api/edge-definitions', methods=['GET'])
    @require_module_access('calculator')
    def get_edge_definitions():
        """Zwraca definicje 12 krawędzi i grup dla frontendu"""
        try:
            from modules.calculator.services.edge_calculator import get_edge_definitions_for_frontend
            return jsonify(get_edge_definitions_for_frontend())
        except Exception as e:
            current_app.logger.error(f"[get_edge_definitions] Błąd: {str(e)}")
            return jsonify({"success": False, "error": "Blad pobierania definicji krawedzi"}), 500

    @bp.route('/api/calculate-edges', methods=['POST'])
    @require_module_access('calculator')
    def calculate_edges():
        """Oblicza cenę obróbki krawędzi na podstawie przesłanych danych."""
        try:
            from modules.calculator.services.edge_calculator import calculate_all_edges

            data = request.get_json()
            if not data:
                return jsonify({"success": False, "error": "Brak danych"}), 400

            edges_config = data.get('edges', [])
            dimensions = {
                'length': float(data.get('length', 0)),
                'width': float(data.get('width', 0)),
                'thickness': float(data.get('thickness', 0)),
            }

            result = calculate_all_edges(edges_config, dimensions)
            return jsonify(result)

        except Exception as e:
            current_app.logger.error(f"[calculate_edges] Błąd: {str(e)}")
            return jsonify({"success": False, "error": "Blad kalkulacji krawedzi"}), 500
