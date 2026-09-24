# -*- coding: utf-8 -*-
"""
Klucz sesji pochodzi z konfiguracji, nie z kodu.

Repo jest publiczne. Klucz wpisany w app.py pozwalał każdemu podpisać własne
ciasteczko sesji (wejście jako dowolny użytkownik). Te testy pilnują, żeby
problem nie wrócił i żeby brak klucza zatrzymywał start aplikacji zamiast po
cichu używać czegoś zaszytego.

Wartości kluczy w testach są losowe (secrets) — żaden test nie zależy od
konkretnej wartości i żadna nie ląduje w repo.
"""

import ast
import json
import os
import secrets

import pytest


KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZMIENNA = 'FLASK_SECRET_KEY'


@pytest.fixture(scope='module')
def app_modul():
    # Import odroczony do fixture'a: moduł app przy imporcie woła create_app()
    # (app.py kończy się `app = create_app()`); klucz dostarcza tests/conftest.py.
    import app as modul
    return modul


def _katalog_z_core_json(tmp_path, **pola):
    """Tworzy <tmp>/config/core.json z podanymi polami i zwraca <tmp> jako app_root."""
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'core.json').write_text(json.dumps(pola), encoding='utf-8')
    return str(tmp_path)


def _konfiguracja_testowa(**dodatkowe):
    """Minimalny core.json dla pełnego create_app(): baza w pamięci, bez migracji."""
    dane = {
        'DEBUG': True,
        'DATABASE_URI': 'sqlite://',
        'RUN_DB_SETUP': False,
        'RUN_MIGRATIONS': False,
    }
    dane.update(dodatkowe)
    return dane


# ----------------------------------------------------------------------------
# wczytaj_klucz_sesji() — źródła i walidacja
# ----------------------------------------------------------------------------

def test_zmienna_srodowiskowa_wygrywa_nad_plikiem(app_modul, tmp_path, monkeypatch):
    z_pliku = secrets.token_hex(32)
    ze_zmiennej = secrets.token_hex(32)
    root = _katalog_z_core_json(tmp_path, SECRET_KEY=z_pliku)
    monkeypatch.setenv(ZMIENNA, ze_zmiennej)

    assert app_modul.wczytaj_klucz_sesji(root) == ze_zmiennej


def test_bez_zmiennej_klucz_idzie_z_core_json(app_modul, tmp_path, monkeypatch):
    z_pliku = secrets.token_hex(32)
    root = _katalog_z_core_json(tmp_path, SECRET_KEY=z_pliku)
    monkeypatch.delenv(ZMIENNA, raising=False)

    assert app_modul.wczytaj_klucz_sesji(root) == z_pliku


@pytest.mark.parametrize('pusta', ['', '   '])
def test_pusta_zmienna_to_brak_zmiennej(app_modul, tmp_path, monkeypatch, pusta):
    # docker-compose przekazuje FLASK_SECRET_KEY="" z maszyny bez wpisu w .env —
    # pusty napis nie może zablokować klucza z core.json.
    z_pliku = secrets.token_hex(32)
    root = _katalog_z_core_json(tmp_path, SECRET_KEY=z_pliku)
    monkeypatch.setenv(ZMIENNA, pusta)

    assert app_modul.wczytaj_klucz_sesji(root) == z_pliku


def test_brak_klucza_w_obu_zrodlach_rzuca(app_modul, tmp_path, monkeypatch):
    root = _katalog_z_core_json(tmp_path, DEBUG=True)
    monkeypatch.delenv(ZMIENNA, raising=False)

    with pytest.raises(app_modul.BrakKluczaSesjiError) as blad:
        app_modul.wczytaj_klucz_sesji(root)

    komunikat = str(blad.value)
    assert 'Brak klucza sesji' in komunikat
    # Komunikat mówi, CO zrobić — operator czyta go w logu deployu.
    assert ZMIENNA in komunikat and 'SECRET_KEY' in komunikat
    assert 'token_hex' in komunikat


def test_brak_pliku_i_zmiennej_rzuca(app_modul, tmp_path, monkeypatch):
    monkeypatch.delenv(ZMIENNA, raising=False)

    with pytest.raises(app_modul.BrakKluczaSesjiError):
        app_modul.wczytaj_klucz_sesji(str(tmp_path))


def test_puste_pole_w_core_json_rzuca(app_modul, tmp_path, monkeypatch):
    root = _katalog_z_core_json(tmp_path, SECRET_KEY='')
    monkeypatch.delenv(ZMIENNA, raising=False)

    with pytest.raises(app_modul.BrakKluczaSesjiError):
        app_modul.wczytaj_klucz_sesji(root)


def test_za_krotki_klucz_ze_zmiennej_rzuca_i_nie_ujawnia_wartosci(app_modul, tmp_path,
                                                                   monkeypatch):
    krotki = secrets.token_hex(15)  # 30 znaków < 32
    monkeypatch.setenv(ZMIENNA, krotki)

    with pytest.raises(app_modul.BrakKluczaSesjiError) as blad:
        app_modul.wczytaj_klucz_sesji(str(tmp_path))

    komunikat = str(blad.value)
    assert 'za krótki' in komunikat
    assert ZMIENNA in komunikat
    assert krotki not in komunikat


def test_za_krotki_klucz_z_pliku_rzuca_i_nie_ujawnia_wartosci(app_modul, tmp_path,
                                                               monkeypatch):
    krotki = secrets.token_hex(10)  # 20 znaków
    root = _katalog_z_core_json(tmp_path, SECRET_KEY=krotki)
    monkeypatch.delenv(ZMIENNA, raising=False)

    with pytest.raises(app_modul.BrakKluczaSesjiError) as blad:
        app_modul.wczytaj_klucz_sesji(root)

    komunikat = str(blad.value)
    assert 'za krótki' in komunikat
    assert 'core.json' in komunikat
    assert krotki not in komunikat


def test_klucz_o_minimalnej_dlugosci_przechodzi(app_modul, tmp_path, monkeypatch):
    dokladnie_32 = secrets.token_hex(16)
    assert len(dokladnie_32) == app_modul.MIN_DLUGOSC_KLUCZA_SESJI == 32
    monkeypatch.setenv(ZMIENNA, dokladnie_32)

    assert app_modul.wczytaj_klucz_sesji(str(tmp_path)) == dokladnie_32


def test_klucz_niebedacy_tekstem_rzuca(app_modul, tmp_path, monkeypatch):
    root = _katalog_z_core_json(tmp_path, SECRET_KEY=12345678901234567890123456789012345)
    monkeypatch.delenv(ZMIENNA, raising=False)

    with pytest.raises(app_modul.BrakKluczaSesjiError) as blad:
        app_modul.wczytaj_klucz_sesji(root)

    assert 'tekstem' in str(blad.value)


def test_przyklad_core_json_nie_daje_dzialajacego_klucza(app_modul, tmp_path, monkeypatch):
    # Kto skopiuje config/core.json.example bez zmian, ma dostać błąd startu,
    # a nie klucz znany z publicznego repo.
    with open(os.path.join(KORZEN, 'config', 'core.json.example'), encoding='utf-8') as f:
        przyklad = json.load(f)
    assert 'SECRET_KEY' in przyklad

    root = _katalog_z_core_json(tmp_path, **przyklad)
    monkeypatch.delenv(ZMIENNA, raising=False)

    with pytest.raises(app_modul.BrakKluczaSesjiError):
        app_modul.wczytaj_klucz_sesji(root)


# ----------------------------------------------------------------------------
# create_app() — zatrzymanie startu i faktycznie użyty klucz
# ----------------------------------------------------------------------------

def test_create_app_bez_klucza_rzuca(app_modul, monkeypatch):
    monkeypatch.delenv(ZMIENNA, raising=False)
    monkeypatch.setattr(app_modul, '_wczytaj_core_json', lambda root: None)

    with pytest.raises(app_modul.BrakKluczaSesjiError):
        app_modul.create_app()


def test_create_app_z_za_krotkim_kluczem_rzuca(app_modul, monkeypatch):
    monkeypatch.setenv(ZMIENNA, secrets.token_hex(8))
    monkeypatch.setattr(app_modul, '_wczytaj_core_json', lambda root: None)

    with pytest.raises(app_modul.BrakKluczaSesjiError):
        app_modul.create_app()


def test_create_app_klucz_ze_zmiennej_nie_jest_nadpisany_przez_core_json(app_modul,
                                                                        monkeypatch):
    # create_app() robi app.config.update(<cały core.json>), co wgrałoby też
    # SECRET_KEY z pliku. Zmienna środowiskowa musi to przeżyć.
    z_pliku = secrets.token_hex(32)
    ze_zmiennej = secrets.token_hex(32)
    monkeypatch.setenv(ZMIENNA, ze_zmiennej)
    monkeypatch.setattr(app_modul, '_wczytaj_core_json',
                        lambda root: _konfiguracja_testowa(SECRET_KEY=z_pliku))

    # Jedyne pełne create_app() w tym pliku (baza w pamięci, bez migracji):
    # każde kolejne dokłada globalny stan (singleton AIService, blueprinty),
    # a samo branie klucza z pliku sprawdzają testy wczytaj_klucz_sesji() wyżej.
    nowa = app_modul.create_app()

    assert nowa.secret_key == ze_zmiennej
    assert nowa.config['SECRET_KEY'] == ze_zmiennej


def test_aplikacja_modulowa_wstaje_z_kluczem_z_konfiguracji(app_modul):
    # `app = create_app()` na końcu app.py — to ta instancja idzie do gunicorna.
    # conftest dał klucz przez zmienną środowiskową, więc to on musi być użyty.
    assert app_modul.app.secret_key == os.environ[ZMIENNA]
    assert len(app_modul.app.secret_key) >= app_modul.MIN_DLUGOSC_KLUCZA_SESJI


# ----------------------------------------------------------------------------
# Tokeny resetu hasła
# ----------------------------------------------------------------------------

def test_token_resetu_dziala_z_kluczem_aplikacji(app_modul):
    klucz = app_modul.app.secret_key

    token = app_modul.generate_reset_token('jan.kowalski@example.com', klucz)

    assert app_modul.verify_reset_token(token, klucz) == 'jan.kowalski@example.com'


def test_token_podpisany_innym_kluczem_jest_odrzucany(app_modul):
    # Tak wyglądają stare linki resetu po rotacji klucza: podpis się nie zgadza.
    obcy_klucz = secrets.token_hex(32)
    token = app_modul.generate_reset_token('jan.kowalski@example.com', obcy_klucz)

    assert app_modul.verify_reset_token(token, app_modul.app.secret_key) is None


# ----------------------------------------------------------------------------
# Nic zaszytego w kodzie
# ----------------------------------------------------------------------------

def _zrodlo_app_py():
    with open(os.path.join(KORZEN, 'app.py'), encoding='utf-8') as f:
        return f.read()


def test_app_py_nie_ustawia_klucza_sesji_literalem():
    """Żadne `x.secret_key = "..."` ani `x.config['SECRET_KEY'] = "..."` w app.py."""
    drzewo = ast.parse(_zrodlo_app_py())
    naruszenia = []

    for wezel in ast.walk(drzewo):
        if not isinstance(wezel, ast.Assign):
            continue
        if not (isinstance(wezel.value, ast.Constant) and isinstance(wezel.value.value, str)):
            continue
        for cel in wezel.targets:
            if isinstance(cel, ast.Attribute) and cel.attr == 'secret_key':
                naruszenia.append(wezel.lineno)
            if isinstance(cel, ast.Subscript):
                indeks = getattr(cel.slice, 'value', cel.slice)  # ast.Index w Pythonie 3.8
                if isinstance(indeks, ast.Constant) and indeks.value == 'SECRET_KEY':
                    naruszenia.append(wezel.lineno)

    assert naruszenia == [], f'Klucz sesji ustawiany literałem w app.py, linie: {naruszenia}'


def test_docker_compose_nie_zawiera_wartosci_klucza():
    # Lokalny Docker bierze klucz z .env (poza gitem) — w compose tylko odwołanie.
    with open(os.path.join(KORZEN, 'docker-compose.yml'), encoding='utf-8') as f:
        linie = [l.strip() for l in f if l.strip().startswith(f'{ZMIENNA}:')]

    assert linie == [f'{ZMIENNA}: "${{{ZMIENNA}:-}}"']
