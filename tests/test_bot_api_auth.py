"""Auth API bota — klucz z config, bez sesji."""
from modules.calculator.routers.bot_api import _check_api_key


def test_zgodny_klucz():
    assert _check_api_key('tajny-klucz', 'tajny-klucz') is True


def test_brak_lub_zly_klucz():
    assert _check_api_key(None, 'tajny-klucz') is False
    assert _check_api_key('zly', 'tajny-klucz') is False
    assert _check_api_key('cokolwiek', None) is False   # brak konfiguracji = zamknięte
