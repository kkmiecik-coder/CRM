"""Bot API — wykrywanie brakujących pól, żeby LLM wiedział o co dopytać klienta."""
from modules.calculator.routers.bot_api import _missing_fields


def test_brakujace_pola():
    assert _missing_fields({'length': 100}) == ['width', 'thickness', 'quantity', 'selected_variant']


def test_komplet():
    p = {'length': 100, 'width': 50, 'thickness': 3, 'quantity': 1,
         'selected_variant': 'dab-lity-ab'}
    assert _missing_fields(p) == []
