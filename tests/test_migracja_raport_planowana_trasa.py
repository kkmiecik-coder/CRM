# -*- coding: utf-8 -*-
"""Jednorazowa migracja nazwy statusu 417343 w historycznych wierszach STAREGO raportu sprzedażowego
(tabela `baselinker_reports_orders`; logistyka etap 4, krok 4.4b). Towarzyszka
`2026-10-01-analiza-planowana-trasa.sql`, która robi to samo w `sales_orders`.

Tabelę `baselinker_reports_orders` zakłada wyłącznie `create_all()` z modelu (żadna migracja jej nie
tworzy), więc polecenie UPDATE stoi za osłoną z `information_schema`, wykonaną przez PREPARE/EXECUTE
(wzorzec `2026-09-23-unikalnosc-klucza-pozycji.sql`). SQLite nie zna ani `information_schema`, ani PREPARE,
więc testy dzielą się na dwie części:

- kształt pliku: nazwa, brak zmiany separatora, układ poleceń, osłona, brak gołego odwołania do tabeli
  poza literałem tekstowym (goły UPDATE na nieistniejącej tabeli = błąd 1146 = przerwany deploy),
- zachowanie UPDATE-a: wyjmujemy go Z PLIKU (literał tekstowy z gałęzi „tabela jest”) i wykonujemy na
  SQLite, więc test nie trzyma własnej kopii warunku.

Cały plik, razem z osłoną (tabela jest i jej nie ma), wykonuje się osobno na MySQL 8.4 w kontenerze `db`.
"""
import os
import re
from datetime import date, datetime

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from migrations.migration_service import MigrationService
from modules.reports.models import BaselinkerReportOrder
from modules.reports.service import STATUSY_BASELINKER

# Rejestr mapperów: bez tych modeli konfiguracja SQLAlchemy nie znajduje klas z relacji (np. User -> Multiplier).
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
from modules.production.models import ProductionOrder  # noqa: F401
from modules.users.models import User  # noqa: F401
import modules.quotes.models  # noqa: F401

KATALOG_MIGRACJI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations')
MIGRACJA = os.path.join(KATALOG_MIGRACJI, '2026-10-02-raport-planowana-trasa.sql')
TABELA = 'baselinker_reports_orders'
STARA_NAZWA = 'Status 417343'
NOWA_NAZWA = 'Planowana trasa'
ID_STATUSU = 417343
ID_ZALADOWANE = 524520
ZNACZNIK_ZAPISU = datetime(2026, 9, 25, 8, 0, 0)

# Literał tekstowy MySQL: apostrof w środku zapisujemy podwójnie.
_LITERAL = re.compile(r"'((?:[^']|'')*)'")


def _tresc():
    with open(MIGRACJA, encoding='utf-8') as f:
        return f.read()


def _polecenia():
    return [' '.join(p.split()) for p in MigrationService.split_statements(_tresc())]


def _literaly(polecenie):
    """Literały tekstowe polecenia, już z odpodwojonymi apostrofami."""
    return [m.replace("''", "'") for m in _LITERAL.findall(polecenie)]


def _update_z_pliku():
    """Polecenie UPDATE zapisane w migracji jako literał tekstowy (wykonuje je PREPARE)."""
    kandydaci = [l for p in _polecenia() for l in _literaly(p) if l.upper().startswith('UPDATE ')]
    assert len(kandydaci) == 1, kandydaci
    return kandydaci[0]


# --- kształt pliku ---------------------------------------------------------

def test_plik_istnieje():
    assert os.path.exists(MIGRACJA), 'brak pliku migracji'


def test_runner_rozpoznaje_nazwe_pliku():
    """STRAŻNIK: nazwa spoza wzorca runnera = migracja POMINIĘTA po cichu."""
    assert MigrationService(db=None)._match(os.path.basename(MIGRACJA)) is not None


def test_nie_uzywa_zmiany_separatora_polecen():
    assert 'DELIMITER' not in _tresc().upper()


def test_plik_to_utf8_bez_bom_i_z_lf():
    surowe = open(MIGRACJA, 'rb').read()
    assert not surowe.startswith(b'\xef\xbb\xbf'), 'BOM na początku pliku'
    assert b'\r' not in surowe, 'CRLF w pliku'
    surowe.decode('utf-8')


def test_uklad_polecen_odczyt_oslona_prepare_execute_deallocate():
    """5 poleceń: SET (odczyt information_schema), SET @sql = IF(...), PREPARE, EXECUTE, DEALLOCATE."""
    polecenia = _polecenia()
    assert len(polecenia) == 5, polecenia
    assert polecenia[0].startswith('SET @') and 'information_schema.COLUMNS' in polecenia[0]
    assert polecenia[1].startswith('SET @sql = IF(')
    assert re.match(r'PREPARE \w+ FROM @sql$', polecenia[2]), polecenia[2]
    assert re.match(r'EXECUTE \w+$', polecenia[3]), polecenia[3]
    assert re.match(r'DEALLOCATE PREPARE \w+$', polecenia[4]), polecenia[4]


def test_oslona_sprawdza_tabele_i_obie_kolumny_statusu():
    odczyt = _polecenia()[0]
    assert "TABLE_NAME = 'baselinker_reports_orders'" in odczyt
    assert 'TABLE_SCHEMA = DATABASE()' in odczyt
    assert "COLUMN_NAME IN ('current_status', 'baselinker_status_id')" in odczyt
    # UPDATE wykona się tylko, gdy są OBIE kolumny; inaczej gałąź „pomijam”.
    assert re.search(r'IF\(@\w+ = 2,', _polecenia()[1]), _polecenia()[1]


def test_nie_odwoluje_sie_do_tabeli_poza_literalem_tekstowym():
    """Goły UPDATE/SELECT z tabelą na bazie bez tej tabeli to błąd 1146, a nieudana migracja jest ponawiana
    przy każdym deployu i przerywa go przed restartem. Nazwa tabeli może więc stać tylko w literałach."""
    for polecenie in _polecenia():
        bez_literalow = _LITERAL.sub("''", polecenie)
        assert TABELA not in bez_literalow, polecenie


def test_update_ma_dokladnie_wlasciwy_warunek():
    assert _update_z_pliku() == (
        "UPDATE baselinker_reports_orders SET current_status = 'Planowana trasa' "
        "WHERE baselinker_status_id = 417343 AND current_status = 'Status 417343'")


def test_nazwa_w_migracji_jest_taka_sama_jak_w_mapie_statusow():
    """Bajt w bajt: inaczej wiersze po migracji i nowe wiersze z ingestu trafiłyby do dwóch kubełków."""
    assert STATUSY_BASELINKER[ID_STATUSU] == NOWA_NAZWA
    update = _update_z_pliku()
    assert re.search(r"SET current_status = '([^']*)'", update).group(1) == STATUSY_BASELINKER[ID_STATUSU]
    # Stara nazwa to dokładnie to, co ingest zapisywał dla identyfikatora spoza mapy.
    assert re.search(r"current_status = '([^']*)'$", update).group(1) == f'Status {ID_STATUSU}'


# --- zachowanie UPDATE-a na SQLite -----------------------------------------

@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=[BaselinkerReportOrder.__table__])
        yield app
        db.session.remove()


def _wiersz(bl_id, status, status_id):
    # Dwa wiersze na zamówienie (stary raport trzyma 1 wiersz = 1 pozycja) — poprawka ma objąć każdy.
    for _ in range(2):
        db.session.add(BaselinkerReportOrder(
            baselinker_order_id=bl_id, date_created=date(2026, 9, 20),
            current_status=status, baselinker_status_id=status_id,
            created_at=ZNACZNIK_ZAPISU, updated_at=ZNACZNIK_ZAPISU))


def _stan():
    """Per numer zamówienia Base.: posortowana lista (nazwa, id statusu, updated_at); bez cache'u sesji."""
    db.session.expire_all()
    wynik = {}
    for w in BaselinkerReportOrder.query.order_by(BaselinkerReportOrder.id).all():
        wynik.setdefault(w.baselinker_order_id, []).append((w.current_status, w.baselinker_status_id, w.updated_at))
    return wynik


def _wykonaj_update():
    """Ten sam UPDATE, który w MySQL wykonuje PREPARE/EXECUTE; zwraca liczbę zmienionych wierszy."""
    wynik = db.session.execute(db.text(_update_z_pliku()))
    db.session.commit()
    return wynik.rowcount


def test_zmienia_tylko_wiersze_ze_stara_nazwa_i_tym_identyfikatorem(app):
    _wiersz(1, STARA_NAZWA, ID_STATUSU)             # to jedyne, które ma się zmienić
    _wiersz(2, STARA_NAZWA, ID_ZALADOWANE)          # stara nazwa, inny identyfikator
    _wiersz(3, 'Reklamacja', ID_STATUSU)            # ten identyfikator, ale inna nazwa
    _wiersz(4, STARA_NAZWA, None)                   # brak identyfikatora
    _wiersz(5, NOWA_NAZWA, ID_STATUSU)              # już poprawiony (świeży ingest)
    _wiersz(6, 'Odebrane', 149779)                  # zupełnie inny status
    _wiersz(7, None, ID_STATUSU)                    # bez nazwy
    db.session.commit()
    przed = _stan()

    assert _wykonaj_update() == 2                   # oba wiersze zamówienia 1, nic więcej

    po = _stan()
    assert po[1] == [(NOWA_NAZWA, ID_STATUSU, ZNACZNIK_ZAPISU)] * 2
    # Pozostałe wiersze nietknięte, co do pola.
    for numer in (2, 3, 4, 5, 6, 7):
        assert po[numer] == przed[numer], numer
    assert sum(1 for w in po.values() for s in w if s[0] == STARA_NAZWA) == 4   # zamówienia 2 i 4
    assert sum(len(w) for w in po.values()) == 14


def test_nie_rusza_updated_at(app):
    """Stary raport czyta `updated_at` (m.in. przy porównaniach i backfillu). Surowy UPDATE nie odpala
    `onupdate` modelu, a kolumna w MySQL nie ma ON UPDATE CURRENT_TIMESTAMP — znacznik zostaje."""
    _wiersz(1, STARA_NAZWA, ID_STATUSU)
    db.session.commit()

    _wykonaj_update()

    assert {s[2] for s in _stan()[1]} == {ZNACZNIK_ZAPISU}


def test_drugie_uruchomienie_nic_nie_zmienia(app):
    _wiersz(1, STARA_NAZWA, ID_STATUSU)
    _wiersz(2, STARA_NAZWA, ID_STATUSU)
    _wiersz(3, 'Odebrane', 149779)
    db.session.commit()

    assert _wykonaj_update() == 4
    po_pierwszym = _stan()

    assert _wykonaj_update() == 0
    assert _stan() == po_pierwszym
    assert all(s[0] == NOWA_NAZWA for s in po_pierwszym[1] + po_pierwszym[2])


def test_pusta_tabela_nie_przeszkadza(app):
    assert _wykonaj_update() == 0
    assert BaselinkerReportOrder.query.count() == 0
