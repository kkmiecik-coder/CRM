# modules/calculator/services/pricing_service.py
"""
Serwis cennika wykończeń - hierarchia opcji z fallbackiem.
Wyciągnięty z routers.py (linie 357-393).
"""

import logging
from flask import current_app

logger = logging.getLogger(__name__)


def get_finishing_prices_data():
    """
    Pobiera ceny wykończeń z bazy danych - hierarchiczne drzewko.
    Jeśli nowa tabela finishing_options nie działa, fallback do finishing_type_prices.

    Returns:
        tuple: (lista cen, kod HTTP)
    """
    from modules.calculator.models import FinishingOption, FinishingTypePrice

    try:
        # Spróbuj z nowej tabeli hierarchicznej
        try:
            flat_list = FinishingOption.get_flat_list(include_inactive=False)
            if flat_list:
                prices_data = []
                for opt in flat_list:
                    prices_data.append({
                        'id': opt['id'],
                        'name': opt['name'],
                        'full_path': opt['full_path'],
                        'price_netto': opt['effective_price_netto'],
                        'level': opt['level'],
                        'parent_id': opt['parent_id'],
                        'image_path': opt.get('image_path'),
                    })
                return prices_data, 200
        except Exception as e:
            current_app.logger.warning(f"Fallback do starej tabeli finishing: {e}")

        # Fallback: stara tabela
        prices = FinishingTypePrice.query.filter_by(is_active=True).all()
        prices_data = []
        for price in prices:
            prices_data.append({
                'id': price.id,
                'name': price.name,
                'price_netto': float(price.price_netto),
            })
        return prices_data, 200

    except Exception as e:
        current_app.logger.error(f"Błąd pobierania cen wykończeń: {str(e)}")
        return {"success": False, "error": "Blad pobierania cen wykonczeń"}, 500
