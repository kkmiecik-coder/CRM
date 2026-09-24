# -*- coding: utf-8 -*-
"""
Endpointy CRON: brak sekretu w konfiguracji ZAMYKA dostęp, nie otwiera go.

Wcześniej oba dekoratory (produkcja i raporty) brały
`config.get('PRODUCTION_CRON_SECRET', <wartość wpisana w kod>)`. Repo jest
publiczne, więc przy braku pola w core.json każdy mógł wołać sync-cron,
close-stale-sessions i sync-statuses. Teraz jest jeden dekorator
(cron_auth.py) bez wartości zapasowej, z porównaniem stałoczasowym.

Sekrety w testach są losowe — żaden test nie zależy od konkretnej wartości.
"""

import ast
import json
import logging
import os
import secrets

import pytest
from flask import Flask, jsonify

import cron_auth
from cron_auth import (
    CRON_SECRET_CONFIG_KEY,
    CRON_SECRET_HEADER,
    cron_secret_required,
    sekret_crona_poprawny,
    skonfigurowany_sekret_crona,
)


KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Adresy endpointów CRON w prawdziwej aplikacji — wszystkie muszą iść przez
# wspólny dekorator.
ENDPOINTY_CRON = (
    '/production/api/sync-cron',
    '/production/api/workers/close-stale-sessions',
    '/production/api/logistics/cron',
    '/reports/api/cron/sync-statuses',
)


# ----------------------------------------------------------------------------
# Funkcje pomocnicze
# ----------------------------------------------------------------------------

@pytest.mark.parametrize('konfiguracja', [
    {},
    {CRON_SECRET_CONFIG_KEY: None},
    {CRON_SECRET_CONFIG_KEY: ''},
    {CRON_SECRET_CONFIG_KEY: '   '},
    {CRON_SECRET_CONFIG_KEY: 12345},
])
def test_brak_lub_bledny_sekret_w_konfiguracji_to_none(konfiguracja):
    assert skonfigurowany_sekret_crona(konfiguracja) is None


def test_skonfigurowany_sekret_jest_zwracany_bez_zmian():
    sekret = secrets.token_hex(16)
    assert skonfigurowany_sekret_crona({CRON_SECRET_CONFIG_KEY: sekret}) == sekret


def test_porownanie_sekretu():
    sekret = secrets.token_hex(16)
    assert sekret_crona_poprawny(sekret, sekret) is True
    assert sekret_crona_poprawny(sekret + 'x', sekret) is False
    assert sekret_crona_poprawny(None, sekret) is False
    assert sekret_crona_poprawny('', sekret) is False
    assert sekret_crona_poprawny(sekret, None) is False     # brak konfiguracji = zamknięte


def test_porownanie_znakow_spoza_ascii_nie_rzuca_wyjatku():
    # hmac.compare_digest na napisach rzuca TypeError dla nie-ASCII; nagłówek
    # przychodzi od kogokolwiek, więc to musi być zwykłe „nie".
    assert sekret_crona_poprawny('sekret-é', secrets.token_hex(16)) is False
    assert sekret_crona_poprawny('zażółć', 'zażółć') is True


def test_przyklad_konfiguracji_nie_daje_dzialajacego_sekretu():
    # Skopiowany bez zmian core.json.example ma zamykać endpointy CRON,
    # a nie otwierać je wartością znaną z publicznego repo.
    with open(os.path.join(KORZEN, 'config', 'core.json.example'), encoding='utf-8') as f:
        przyklad = json.load(f)

    assert CRON_SECRET_CONFIG_KEY in przyklad
    assert skonfigurowany_sekret_crona(przyklad) is None


# ----------------------------------------------------------------------------
# Dekorator na minimalnej aplikacji
# ----------------------------------------------------------------------------

def _aplikacja(**konfiguracja):
    app = Flask(__name__)
    app.config.update(konfiguracja)

    @app.route('/cron')
    @cron_secret_required
    def cron():
        return jsonify({'success': True})

    return app


def test_brak_sekretu_w_konfiguracji_zamyka_endpoint():
    klient = _aplikacja().test_client()

    bez_naglowka = klient.get('/cron')
    z_naglowkiem = klient.get('/cron', headers={CRON_SECRET_HEADER: secrets.token_hex(16)})

    assert bez_naglowka.status_code == 500
    assert z_naglowkiem.status_code == 500
    assert z_naglowkiem.get_json()['success'] is False


@pytest.mark.parametrize('wartosc', ['', '   '])
def test_pusty_sekret_w_konfiguracji_zamyka_endpoint(wartosc):
    klient = _aplikacja(**{CRON_SECRET_CONFIG_KEY: wartosc}).test_client()

    assert klient.get('/cron', headers={CRON_SECRET_HEADER: wartosc}).status_code == 500
    assert klient.get('/cron').status_code == 500


def test_poprawny_sekret_przepuszcza():
    sekret = secrets.token_hex(32)
    klient = _aplikacja(**{CRON_SECRET_CONFIG_KEY: sekret}).test_client()

    odpowiedz = klient.get('/cron', headers={CRON_SECRET_HEADER: sekret})

    assert odpowiedz.status_code == 200
    assert odpowiedz.get_json() == {'success': True}


def test_zly_albo_brakujacy_sekret_daje_403():
    sekret = secrets.token_hex(32)
    klient = _aplikacja(**{CRON_SECRET_CONFIG_KEY: sekret}).test_client()

    assert klient.get('/cron').status_code == 403
    assert klient.get('/cron', headers={CRON_SECRET_HEADER: ''}).status_code == 403
    assert klient.get('/cron', headers={CRON_SECRET_HEADER: sekret[:-1]}).status_code == 403
    assert klient.get('/cron', headers={CRON_SECRET_HEADER: 'sekret-é'}).status_code == 403


def test_odpowiedz_nie_zawiera_sekretu():
    sekret = secrets.token_hex(32)
    klient = _aplikacja(**{CRON_SECRET_CONFIG_KEY: sekret}).test_client()

    odpowiedz = klient.get('/cron', headers={CRON_SECRET_HEADER: 'zly'})

    assert sekret not in odpowiedz.get_data(as_text=True)


# ----------------------------------------------------------------------------
# Brak sekretu = alarm w Sentry, a nie tylko wpis w pliku logu
# ----------------------------------------------------------------------------
# Odpowiedź 500 to nie wyjątek, więc integracja Flaska w Sentry jej nie widzi,
# a cron z `curl --silent` bez -f kończy się kodem 0. Jedyny sygnał to log,
# który musi mieć poziom, od którego Sentry robi zdarzenie. Inaczej
# synchronizacja BaseLinkera, statusy raportów i domykanie sesji stoją po
# cichu całymi dniami.

NAZWA_LOGGERA = 'app.cron_auth'


@pytest.fixture(autouse=True)
def czyste_alarmy():
    # Pamięć „kiedy ostatnio alarmowano” jest na poziomie modułu, więc każdy
    # test zaczyna od zera, niezależnie od kolejności.
    cron_auth._ostatni_alarm.clear()
    yield
    cron_auth._ostatni_alarm.clear()


def _poziomy_logu(caplog):
    return [r.levelno for r in caplog.records if r.name == NAZWA_LOGGERA]


def test_brak_sekretu_loguje_critical(caplog):
    klient = _aplikacja().test_client()

    with caplog.at_level(logging.DEBUG, logger=NAZWA_LOGGERA):
        odpowiedz = klient.get('/cron', headers={CRON_SECRET_HEADER: secrets.token_hex(16)})

    assert odpowiedz.status_code == 500
    assert _poziomy_logu(caplog) == [logging.CRITICAL]


def test_alarm_o_braku_sekretu_przechodzi_przez_prog_sentry(tmp_path, monkeypatch, caplog):
    """Kontrakt z sentry_config.init_sentry: poziom alarmu >= event_level integracji logowania."""
    sentry_sdk = pytest.importorskip('sentry_sdk')
    integracja_logowania = pytest.importorskip('sentry_sdk.integrations.logging')
    import sentry_config

    przechwycone = {}

    class NagrywajacaIntegracjaLogowania:
        # Wartości domyślne jak w sentry-sdk: gdyby sentry_config przestał
        # podawać event_level, próg spadłby do ERROR i test by to pokazał.
        def __init__(self, level=logging.INFO, event_level=logging.ERROR):
            przechwycone['event_level'] = event_level

    # Prawdziwe Sentry nie startuje: init i integracja logowania są podmienione.
    monkeypatch.setattr(integracja_logowania, 'LoggingIntegration', NagrywajacaIntegracjaLogowania)
    monkeypatch.setattr(sentry_sdk, 'init', lambda **kwargs: przechwycone.setdefault('init', kwargs))

    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'core.json').write_text(
        json.dumps({'SENTRY': {'enabled': True, 'dsn': 'https://klucz@sentry.invalid/1'}}),
        encoding='utf-8')
    assert sentry_config.init_sentry(str(tmp_path)) is True
    prog_sentry = przechwycone['event_level']

    klient = _aplikacja().test_client()
    with caplog.at_level(logging.DEBUG, logger=NAZWA_LOGGERA):
        klient.get('/cron')

    poziomy = _poziomy_logu(caplog)
    assert poziomy, 'brak sekretu nie zostawił żadnego wpisu w logu'
    assert max(poziomy) >= prog_sentry, (
        f'alarm ma poziom {logging.getLevelName(max(poziomy))}, a Sentry robi zdarzenie '
        f'dopiero od {logging.getLevelName(prog_sentry)}, więc nikt się nie dowie')


def test_alarm_ponawiany_najwyzej_raz_na_odstep(caplog, monkeypatch):
    # Cron woła endpoint co kilka minut, a przy braku sekretu może go wołać
    # każdy z internetu. Bez ograniczenia każde wywołanie byłoby zdarzeniem
    # w Sentry i zjadałoby limit, zasłaniając inne błędy.
    zegar = [1000.0]
    monkeypatch.setattr(cron_auth, '_teraz', lambda: zegar[0])
    klient = _aplikacja().test_client()

    with caplog.at_level(logging.DEBUG, logger=NAZWA_LOGGERA):
        kody = [klient.get('/cron').status_code, klient.get('/cron').status_code]
        zegar[0] += cron_auth.ODSTEP_ALARMU_S - 1
        kody.append(klient.get('/cron').status_code)
        zegar[0] += 2
        kody.append(klient.get('/cron').status_code)

    # Każde wywołanie dalej zamknięte, zmienia się tylko poziom wpisu.
    assert kody == [500, 500, 500, 500]
    assert _poziomy_logu(caplog) == [logging.CRITICAL, logging.ERROR, logging.ERROR, logging.CRITICAL]


def test_alarm_osobno_dla_kazdego_endpointu(caplog):
    app = _aplikacja()

    @app.route('/cron-drugi')
    @cron_secret_required
    def cron_drugi():
        return jsonify({'success': True})

    klient = app.test_client()
    with caplog.at_level(logging.DEBUG, logger=NAZWA_LOGGERA):
        klient.get('/cron')
        klient.get('/cron-drugi')

    assert _poziomy_logu(caplog) == [logging.CRITICAL, logging.CRITICAL]


def test_skonfigurowany_sekret_nie_daje_alarmu(caplog):
    sekret = secrets.token_hex(32)
    klient = _aplikacja(**{CRON_SECRET_CONFIG_KEY: sekret}).test_client()

    with caplog.at_level(logging.DEBUG, logger=NAZWA_LOGGERA):
        klient.get('/cron', headers={CRON_SECRET_HEADER: sekret})
        klient.get('/cron', headers={CRON_SECRET_HEADER: 'zly'})

    # Zły nagłówek to sprawa klienta (403, WARNING), a nie awaria konfiguracji.
    assert logging.CRITICAL not in _poziomy_logu(caplog)


# ----------------------------------------------------------------------------
# Podpięcie w prawdziwej aplikacji
# ----------------------------------------------------------------------------

def _kod_dekoratora():
    # Wewnętrzna funkcja dekoratora ma jeden obiekt kodu niezależnie od tego,
    # co opakowuje — po nim rozpoznajemy widok przepuszczony przez cron_auth.
    return cron_secret_required(lambda: None).__code__


def test_endpointy_cron_w_aplikacji_ida_przez_wspolny_dekorator():
    import app as modul
    aplikacja = modul.app

    widoki = {}
    for regula in aplikacja.url_map.iter_rules():
        if regula.rule in ENDPOINTY_CRON:
            widoki[regula.rule] = aplikacja.view_functions[regula.endpoint]

    assert set(widoki) == set(ENDPOINTY_CRON), 'nie znaleziono któregoś endpointu CRON'
    for adres, widok in widoki.items():
        assert widok.__code__ is _kod_dekoratora(), f'{adres} nie używa cron_auth.cron_secret_required'


def test_moduly_uzywaja_tego_samego_dekoratora():
    from modules.production.routers.api import common_api
    from modules.reports import routers as reports_routers

    assert common_api.cron_secret_required is cron_auth.cron_secret_required
    assert reports_routers.cron_secret_required is cron_auth.cron_secret_required


# ----------------------------------------------------------------------------
# Nic zaszytego w kodzie
# ----------------------------------------------------------------------------

def _pliki_py(*katalogi):
    for katalog in katalogi:
        for sciezka_kat, podkatalogi, pliki in os.walk(os.path.join(KORZEN, katalog)):
            podkatalogi[:] = [d for d in podkatalogi if d not in ('__pycache__', 'lib', 'node_modules')]
            for plik in pliki:
                if plik.endswith('.py'):
                    yield os.path.join(sciezka_kat, plik)


def test_nigdzie_nie_ma_wartosci_domyslnej_sekretu_crona():
    """Żadne `.get('PRODUCTION_CRON_SECRET', <cokolwiek>)` w kodzie aplikacji."""
    pliki = list(_pliki_py('modules', 'integrations', 'scripts'))
    pliki += [os.path.join(KORZEN, nazwa) for nazwa in os.listdir(KORZEN) if nazwa.endswith('.py')]

    naruszenia = []
    for sciezka in pliki:
        with open(sciezka, encoding='utf-8') as f:
            try:
                drzewo = ast.parse(f.read())
            except SyntaxError:
                continue
        for wezel in ast.walk(drzewo):
            if (isinstance(wezel, ast.Call)
                    and isinstance(wezel.func, ast.Attribute)
                    and wezel.func.attr in ('get', 'setdefault')
                    and wezel.args
                    and isinstance(wezel.args[0], ast.Constant)
                    and wezel.args[0].value == CRON_SECRET_CONFIG_KEY
                    and (len(wezel.args) > 1 or wezel.keywords)):
                naruszenia.append(f'{os.path.relpath(sciezka, KORZEN)}:{wezel.lineno}')

    assert naruszenia == [], f'Wartość domyślna sekretu crona: {naruszenia}'


def test_jedyna_definicja_dekoratora_crona_jest_w_cron_auth():
    definicje = []
    for sciezka in _pliki_py('modules', 'integrations'):
        with open(sciezka, encoding='utf-8') as f:
            if 'def cron_secret_required' in f.read():
                definicje.append(os.path.relpath(sciezka, KORZEN))

    assert definicje == []
