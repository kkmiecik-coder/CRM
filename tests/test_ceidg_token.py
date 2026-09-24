# -*- coding: utf-8 -*-
"""
Token API CEIDG pochodzi z config/core.json, nie z kodu.

Token (JWT) był wpisany w modules/clients/routers.py w publicznym repo.
Payload JWT to zwykłe base64, więc każdy mógł odczytać dane osobowe
właściciela tokenu i odpytywać API CEIDG na jego tożsamość. Te testy pilnują:
- braku jakiegokolwiek literału JWT w plikach repo,
- tego, że brak tokenu w konfiguracji to twardy, widoczny błąd (503),
  a nie ciche „nie znaleziono firmy" (404) jak wcześniej.

Tokeny w testach są losowe i nie mają formatu JWT.
"""

import os
import re
import secrets

import pytest
from flask import Flask

from modules.clients import routers
from modules.clients.routers import (
    CEIDG_TOKEN_CONFIG_KEY,
    BrakTokenuCeidgError,
    _ceidg_token,
    query_ceidg_api,
)


KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NIP = '1234567890'


@pytest.fixture()
def aplikacja():
    return Flask(__name__)


class _Odpowiedz:
    def __init__(self, status_code, dane=None):
        self.status_code = status_code
        self._dane = dane

    def json(self):
        return self._dane


# ----------------------------------------------------------------------------
# Źródło tokenu
# ----------------------------------------------------------------------------

@pytest.mark.parametrize('konfiguracja', [
    {},
    {CEIDG_TOKEN_CONFIG_KEY: None},
    {CEIDG_TOKEN_CONFIG_KEY: ''},
    {CEIDG_TOKEN_CONFIG_KEY: '   '},
    {CEIDG_TOKEN_CONFIG_KEY: 12345},
])
def test_brak_tokenu_w_konfiguracji_rzuca(aplikacja, konfiguracja):
    aplikacja.config.update(konfiguracja)

    with aplikacja.app_context():
        with pytest.raises(BrakTokenuCeidgError) as blad:
            _ceidg_token()

    komunikat = str(blad.value)
    assert CEIDG_TOKEN_CONFIG_KEY in komunikat
    assert 'core.json' in komunikat


def test_token_z_konfiguracji(aplikacja):
    token = secrets.token_hex(24)
    aplikacja.config[CEIDG_TOKEN_CONFIG_KEY] = f'  {token}\n'

    with aplikacja.app_context():
        assert _ceidg_token() == token


def test_brak_tokenu_nie_wysyla_zapytania_i_nie_jest_polykany(aplikacja, monkeypatch):
    # Błąd musi wyjść poza query_ceidg_api — wcześniej ogólny `except Exception`
    # i `return None` robiły z niego „nie znaleziono firmy".
    def _zakazane(*a, **k):
        raise AssertionError('Bez tokenu nie wolno odpytywać CEIDG')

    monkeypatch.setattr(routers.requests, 'get', _zakazane)

    with aplikacja.app_context():
        with pytest.raises(BrakTokenuCeidgError):
            query_ceidg_api(NIP)


def test_zapytanie_niesie_token_z_konfiguracji(aplikacja, monkeypatch):
    token = secrets.token_hex(24)
    aplikacja.config[CEIDG_TOKEN_CONFIG_KEY] = token
    wyslane = {}

    def _get(url, headers=None, timeout=None):
        wyslane['url'] = url
        wyslane['headers'] = headers
        return _Odpowiedz(204)

    monkeypatch.setattr(routers.requests, 'get', _get)

    with aplikacja.app_context():
        assert query_ceidg_api(NIP) is None

    assert wyslane['headers']['Authorization'] == f'Bearer {token}'
    assert NIP in wyslane['url']


# ----------------------------------------------------------------------------
# Endpoint /clients/api/gus_lookup
# ----------------------------------------------------------------------------

def _gus_lookup(aplikacja, monkeypatch, ceidg=None):
    """Woła widok z pominięciem require_module_access; GUS i MF nic nie znajdują."""
    monkeypatch.setattr(routers, 'query_gus_bir_api', lambda nip: None)
    monkeypatch.setattr(routers, 'query_mf_wl_api', lambda nip: None)
    if ceidg is not None:
        monkeypatch.setattr(routers, 'query_ceidg_api', ceidg)

    with aplikacja.test_request_context(f'/clients/api/gus_lookup?nip={NIP}'):
        wynik = routers.gus_lookup.__wrapped__()

    odpowiedz, status = wynik if isinstance(wynik, tuple) else (wynik, 200)
    return status, odpowiedz.get_json()


def test_gus_lookup_bez_tokenu_ceidg_daje_503_z_komunikatem(aplikacja, monkeypatch):
    monkeypatch.setattr(routers.requests, 'get', lambda *a, **k: pytest.fail('bez tokenu nie ma zapytania'))

    status, dane = _gus_lookup(aplikacja, monkeypatch)

    assert status == 503
    assert 'CEIDG' in dane['error']
    assert 'ręcznie' in dane['error']


def test_gus_lookup_z_tokenem_zwraca_dane_z_ceidg(aplikacja, monkeypatch):
    aplikacja.config[CEIDG_TOKEN_CONFIG_KEY] = secrets.token_hex(24)
    firma = {'name': 'Jan Testowy', 'company': 'Jan Testowy', '_source': 'CEIDG'}

    status, dane = _gus_lookup(aplikacja, monkeypatch, ceidg=lambda nip: firma)

    assert status == 200
    assert dane == firma


def test_gus_lookup_z_tokenem_bez_wynikow_daje_404(aplikacja, monkeypatch):
    aplikacja.config[CEIDG_TOKEN_CONFIG_KEY] = secrets.token_hex(24)

    status, dane = _gus_lookup(aplikacja, monkeypatch, ceidg=lambda nip: None)

    assert status == 404
    assert 'Nie znaleziono firmy' in dane['error']


# ----------------------------------------------------------------------------
# Nic zaszytego w repo
# ----------------------------------------------------------------------------

# Nagłówek i payload JWT zaczynają się od base64 z '{"' = "eyJ".
_WZORZEC_JWT = re.compile(rb'eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}')

# Skanujemy to, co trafia do gita. Kontener testów nie ma dostępu do .git
# worktree, więc zamiast `git ls-files` idziemy po katalogach kodu i pomijamy
# pliki lokalne spoza gita (.env, bridge.env, config/core.json, notatki
# w docs/superpowers) — tam token MA prawo leżeć i test by na nim padał.
_KATALOGI_KODU = ('modules', 'integrations', 'scripts', 'templates', 'static',
                  'migrations', 'tests', 'ops', 'tools', 'docker', 'docs', 'config')
_POMIJANE_KATALOGI = {'__pycache__', 'node_modules', 'venv', '.venv', 'lib',
                      'superpowers', 'clickup', 'logs', 'backups'}
_POMIJANE_PLIKI = {os.path.join('config', 'core.json'), os.path.join('config', 'core.local.json')}
_ROZSZERZENIA = {'.py', '.js', '.html', '.json', '.example', '.sh', '.yml', '.yaml',
                 '.md', '.txt', '.sql', '.cfg', '.ini', '.conf', '.h', '.cpp', '.ino'}


def _pliki_do_skanu():
    for nazwa in os.listdir(KORZEN):
        if nazwa.endswith(('.py', '.sh', '.yml')) or nazwa == 'CLAUDE.md':
            yield os.path.join(KORZEN, nazwa)
    for katalog in _KATALOGI_KODU:
        for sciezka_kat, podkatalogi, pliki in os.walk(os.path.join(KORZEN, katalog)):
            podkatalogi[:] = [d for d in podkatalogi if d not in _POMIJANE_KATALOGI]
            for plik in pliki:
                sciezka = os.path.join(sciezka_kat, plik)
                if os.path.relpath(sciezka, KORZEN) in _POMIJANE_PLIKI:
                    continue
                if os.path.splitext(plik)[1] in _ROZSZERZENIA:
                    yield sciezka


def test_w_repo_nie_ma_zadnego_literalu_jwt():
    trafienia = []
    przeskanowane = 0
    for sciezka in _pliki_do_skanu():
        przeskanowane += 1
        with open(sciezka, 'rb') as f:
            if _WZORZEC_JWT.search(f.read()):
                # Tylko ścieżka — wartości tokenu nie wypisujemy nawet w teście.
                trafienia.append(os.path.relpath(sciezka, KORZEN))

    assert przeskanowane > 500, 'skan objął podejrzanie mało plików'
    assert trafienia == [], f'Literał JWT w plikach: {trafienia}'


def test_modul_nie_ma_tokenu_jako_stalej():
    assert not hasattr(routers, 'CEIDG_JWT_TOKEN')
