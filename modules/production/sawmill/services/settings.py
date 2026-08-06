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
    # Obwód bez górnego limitu (None = „nie sprawdzaj") — decyzja biznesowa:
    # nietypowo gruba kłoda ma przejść, dolna granica łapie pomyłkę rzędu
    # wielkości (np. wpisaną średnicę zamiast obwodu).
    'min_circumference_cm': 30.0,
    'max_circumference_cm': None,
    'min_length_cm': 30.0,
    'max_length_cm': 20000.0,
    'decimal_places': DECIMAL_PLACES,
    'deviation_threshold_pct': 5.0,
}

# Klucze, które użytkownik może zmienić w panelu. decimal_places celowo poza listą.
EDITABLE_KEYS = (
    'min_circumference_cm', 'max_circumference_cm',
    'min_length_cm', 'max_length_cm',
    'deviation_threshold_pct',
)

# deviation_threshold_pct zostaje po stronie panelu — tablet nie zna deklaracji,
# więc próg odchylenia nic by mu nie powiedział.
MOBILE_KEYS = (
    'min_circumference_cm', 'max_circumference_cm',
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


class SawmillSettingsError(Exception):
    """Ustawienie poza sensownym zakresem — mapowane na HTTP 422."""

    def __init__(self, field, detail):
        super().__init__(detail)
        self.field = field
        self.detail = detail


# Pary (minimum, maksimum) pilnowane względem siebie.
_LIMIT_PAIRS = (
    ('min_circumference_cm', 'max_circumference_cm'),
    ('min_length_cm', 'max_length_cm'),
)


def _validate(settings):
    """
    Te limity idą JEDNYM kanałem do walidacji serwera i na tablet
    (mobile_config_payload), więc literówka w panelu zatrzymuje stanowisko:
    `min_length_cm = 99999` sprawia, że KAŻDY pomiar leci 422, a jedyną
    diagnozą jest komunikat „wartość 410 poniżej minimum 99999". Dlatego
    zakresy sprawdzamy przy zapisie, a nie dopiero przy pomiarze.
    """
    for key in EDITABLE_KEYS:
        wartosc = settings.get(key)
        if wartosc is not None and wartosc < 0:
            raise SawmillSettingsError(key, u'wartość nie może być ujemna')

    for key_min, key_max in _LIMIT_PAIRS:
        dolny, gorny = settings.get(key_min), settings.get(key_max)
        # None znaczy „nie sprawdzaj tego limitu", więc para z pustym polem
        # jest zawsze poprawna — nie ma czego porównywać.
        if dolny is not None and gorny is not None and dolny >= gorny:
            raise SawmillSettingsError(
                key_min, u'minimum musi być mniejsze od maksimum')

    prog = settings.get('deviation_threshold_pct')
    if prog is not None and prog > 100:
        raise SawmillSettingsError(
            'deviation_threshold_pct', u'próg powyżej 100% nigdy się nie zapali')


def save_sawmill_settings(values, user_id=None):
    """Zapisuje edytowalne klucze. Nie commituje — robi to wywołujący."""
    settings = get_sawmill_settings()
    for key in EDITABLE_KEYS:
        if key in values:
            raw = values[key]
            if raw in (None, ''):
                settings[key] = None
                continue
            try:
                settings[key] = float(raw)
            except (TypeError, ValueError):
                raise SawmillSettingsError(key, u'wartość nie jest liczbą')
    settings['decimal_places'] = DECIMAL_PLACES
    _validate(settings)

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
