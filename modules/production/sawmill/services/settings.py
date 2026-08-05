# -*- coding: utf-8 -*-
"""
Ustawienia trakowni — jeden klucz JSON w prod_config.

Odczyt idzie WPROST do bazy, z pominięciem ProductionConfigService, który
trzyma cache z TTL 60 minut. Zmiana limitu w panelu ma działać natychmiast,
na tablecie i w walidacji serwera — dokładnie ten problem występował
wcześniej w cenniku kalkulatora.
"""

import json

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import ProductionConfig

logger = get_structured_logger('production.sawmill.settings')

CONFIG_KEY = 'sawmill_settings'

# decimal_places jest STAŁĄ zgodną ze schematem DECIMAL(5,1)/DECIMAL(6,1).
# Ustawienie 2 sprawiłoby, że MySQL po cichu zaokrągli 40,25 do 40,3 —
# zapisany wymiar przestałby odpowiadać temu, co wpisał pracownik.
DECIMAL_PLACES = 1

DEFAULT_SETTINGS = {
    'min_diameter_cm': 10.0,
    'max_diameter_cm': 200.0,
    'min_length_cm': 30.0,
    'max_length_cm': 20000.0,
    'decimal_places': DECIMAL_PLACES,
    'deviation_threshold_pct': 5.0,
}

# Klucze, które użytkownik może zmienić w panelu. decimal_places celowo poza listą.
EDITABLE_KEYS = (
    'min_diameter_cm', 'max_diameter_cm',
    'min_length_cm', 'max_length_cm',
    'deviation_threshold_pct',
)

# deviation_threshold_pct zostaje po stronie panelu — tablet nie zna deklaracji,
# więc próg odchylenia nic by mu nie powiedział.
MOBILE_KEYS = (
    'min_diameter_cm', 'max_diameter_cm',
    'min_length_cm', 'max_length_cm',
    'decimal_places',
)


def _get_row():
    return ProductionConfig.query.filter_by(config_key=CONFIG_KEY).first()


def get_sawmill_settings():
    """Zwraca ustawienia z bazy, uzupełnione domyślnymi dla brakujących kluczy."""
    settings = dict(DEFAULT_SETTINGS)
    row = _get_row()
    if row is None:
        logger.warning("Brak wiersza sawmill_settings w prod_config — używam domyślnych")
        return settings

    try:
        stored = json.loads(row.config_value)
    except (ValueError, TypeError):
        logger.error("sawmill_settings zawiera niepoprawny JSON — używam domyślnych")
        return settings

    if isinstance(stored, dict):
        settings.update(stored)

    # decimal_places nigdy nie pochodzi z bazy — musi zgadzać się ze schematem.
    settings['decimal_places'] = DECIMAL_PLACES
    return settings


def save_sawmill_settings(values, user_id=None):
    """Zapisuje edytowalne klucze. Nie commituje — robi to wywołujący."""
    settings = get_sawmill_settings()
    for key in EDITABLE_KEYS:
        if key in values:
            raw = values[key]
            settings[key] = None if raw in (None, '') else float(raw)
    settings['decimal_places'] = DECIMAL_PLACES

    row = _get_row()
    if row is None:
        row = ProductionConfig(
            config_key=CONFIG_KEY,
            config_description='Trakownia: limity walidacji pomiarów i próg flagowania odchylenia',
            config_type='json',
        )
        db.session.add(row)

    row.config_value = json.dumps(settings, ensure_ascii=False)
    row.updated_by = user_id
    return settings


def mobile_config_payload():
    """Podzbiór ustawień wysyłany na tablet."""
    settings = get_sawmill_settings()
    return {key: settings.get(key) for key in MOBILE_KEYS}
