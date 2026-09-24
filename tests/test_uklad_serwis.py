# -*- coding: utf-8 -*-
"""Odczyt i zapis prywatnego układu pulpitu.

Testy jadą na SQLite w pamięci, budowanej z modeli. NIE dowodzą niczego
o zachowaniu MySQL-a (walidacja JSON-a, kaskada) — to sprawdza Zadanie 3
na prawdziwej bazie.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
# `users.multiplier_id` ma klucz obcy do `multipliers` — bez rejestracji tej
# tabeli w metadanych `create_all(tables=[User.__table__, ...])` pada
# NoReferencedTableError, gdy plik jedzie sam (w pełnym pakiecie maskuje to
# import z innego pliku). Ten sam wzorzec co tests/test_sawmill_hooks.py.
from modules.calculator.models import Multiplier  # noqa: F401 — rejestracja tabeli 'multipliers'
# calculator.models wnosi mapper Quote, który przy konfiguracji mapperów szuka
# klas Client i modeli wycen — bez nich pierwsze zapytanie pada InvalidRequestError.
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów
from modules.reports.models_uklad import UkladDashboardu
from modules.reports.uklad import (
    KATALOG, UKLAD_DOMYSLNY, Instancja, uklad_do_json,
)
from modules.reports.uklad_service import (
    przywroc_domyslny, uklad_uzytkownika, zapisz_uklad,
)
from modules.users.models import User

TYP_WYMIAROWY = next(k for k, t in KATALOG.items() if t.wymiarowy)
WYMIAR = KATALOG[TYP_WYMIAROWY].domyslny_wymiar


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine,
                               tables=[User.__table__, UkladDashboardu.__table__])
        yield app
        db.session.remove()


@pytest.fixture()
def uzytkownik(app):
    user = User(email='kontroler@woodpower.pl', password='x', role='admin', active=True)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def drugi_uzytkownik(app):
    user = User(email='drugi@woodpower.pl', password='x', role='user', active=True)
    db.session.add(user)
    db.session.commit()
    return user


def test_uzytkownik_bez_wiersza_dostaje_uklad_domyslny(uzytkownik):
    uklad, pominietych = uklad_uzytkownika(uzytkownik)
    assert uklad == list(UKLAD_DOMYSLNY)
    assert pominietych == 0


def test_brak_zalogowanego_daje_uklad_domyslny(app):
    """Nie wywalamy się — pulpit ma się pokazać."""
    assert uklad_uzytkownika(None)[0] == list(UKLAD_DOMYSLNY)


def test_zapis_tworzy_wiersz(uzytkownik):
    zapisz_uklad(uzytkownik, [Instancja('kpi')])
    assert UkladDashboardu.query.filter_by(user_id=uzytkownik.id).count() == 1


def test_zapisany_uklad_wraca_z_odczytu(uzytkownik):
    wlasny = [Instancja(TYP_WYMIAROWY, WYMIAR), Instancja('kpi')]
    zapisz_uklad(uzytkownik, wlasny)
    assert uklad_uzytkownika(uzytkownik)[0] == wlasny


def test_drugi_zapis_nadpisuje_wiersz_zamiast_dokladac(uzytkownik):
    zapisz_uklad(uzytkownik, [Instancja('kpi')])
    zapisz_uklad(uzytkownik, [Instancja('wnioski')])
    assert UkladDashboardu.query.filter_by(user_id=uzytkownik.id).count() == 1
    assert uklad_uzytkownika(uzytkownik)[0] == [Instancja('wnioski')]


def test_uklad_jest_prywatny(uzytkownik, drugi_uzytkownik):
    """Rozstrzygnięcie 3: układ jest wyłącznie prywatny."""
    zapisz_uklad(uzytkownik, [Instancja('kpi')])
    assert uklad_uzytkownika(drugi_uzytkownik)[0] == list(UKLAD_DOMYSLNY)


def test_pusty_uklad_zapisuje_sie_i_wraca_pusty(uzytkownik):
    """NAJWAŻNIEJSZY test tego pliku: brak wiersza (układ domyślny) musi być
    odróżnialny od wiersza z pustą listą (użytkownik usunął wszystko).
    Bez tego rozróżnienia »Przywróć domyślny« i »usuń ostatni kafelek«
    dawałyby ten sam wynik."""
    zapisz_uklad(uzytkownik, [])
    uklad, pominietych = uklad_uzytkownika(uzytkownik)
    assert uklad == []
    assert pominietych == 0


def test_przywrocenie_domyslnego_kasuje_wiersz(uzytkownik):
    """Kasujemy wiersz, a NIE zapisujemy w nim dzisiejszej listy domyślnej —
    dzięki temu przyszła zmiana układu domyślnego dosięgnie też tych, którzy
    kiedyś kliknęli »Przywróć«."""
    zapisz_uklad(uzytkownik, [Instancja('kpi')])
    assert przywroc_domyslny(uzytkownik) is True
    assert UkladDashboardu.query.filter_by(user_id=uzytkownik.id).count() == 0
    assert uklad_uzytkownika(uzytkownik)[0] == list(UKLAD_DOMYSLNY)


def test_przywrocenie_domyslnego_bez_wiersza_nie_wywala_sie(uzytkownik):
    assert przywroc_domyslny(uzytkownik) is False


def test_przywrocenie_domyslnego_nie_rusza_cudzego_wiersza(uzytkownik, drugi_uzytkownik):
    zapisz_uklad(drugi_uzytkownik, [Instancja('kpi')])
    przywroc_domyslny(uzytkownik)
    assert uklad_uzytkownika(drugi_uzytkownik)[0] == [Instancja('kpi')]


def test_odczyt_liczy_pominiete_pozycje(uzytkownik):
    """Pozycja po zmianie katalogu ma zniknąć z renderu, ale NIE z bazy."""
    db.session.add(UkladDashboardu(
        user_id=uzytkownik.id,
        uklad=[{'typ': 'kpi', 'wymiar': None},
               {'typ': 'karta-ktorej-nie-ma', 'wymiar': None}]))
    db.session.commit()
    uklad, pominietych = uklad_uzytkownika(uzytkownik)
    assert [i.typ for i in uklad] == ['kpi']
    assert pominietych == 1


def test_odczyt_nie_przepisuje_wiersza_po_pominieciu(uzytkownik):
    """Wiersz przepisuje się dopiero wtedy, gdy użytkownik SAM zapisze układ.
    Pole może wrócić do rejestru — wtedy kafelek ma się odnaleźć."""
    db.session.add(UkladDashboardu(
        user_id=uzytkownik.id,
        uklad=[{'typ': 'kpi', 'wymiar': None},
               {'typ': 'karta-ktorej-nie-ma', 'wymiar': None}]))
    db.session.commit()
    uklad_uzytkownika(uzytkownik)
    wiersz = UkladDashboardu.query.filter_by(user_id=uzytkownik.id).first()
    assert len(wiersz.uklad) == 2, 'odczyt przyciął zapisany układ w bazie'


def test_zapis_zapisuje_dokladnie_to_co_daje_uklad_do_json(uzytkownik):
    wlasny = [Instancja(TYP_WYMIAROWY, WYMIAR), Instancja('lejek')]
    zapisz_uklad(uzytkownik, wlasny)
    wiersz = UkladDashboardu.query.filter_by(user_id=uzytkownik.id).first()
    assert wiersz.uklad == uklad_do_json(wlasny)


def test_wyscig_przy_pierwszym_zapisie_konczy_sie_nadpisaniem(uzytkownik, monkeypatch):
    """Druga karta przeglądarki wstawiła wiersz między naszym odczytem
    a zapisem. UNIQUE(user_id) odrzuca nasz INSERT — serwis ma wrócić po
    istniejący wiersz i go nadpisać, a nie oddać 500 ani zostawić dwóch
    wierszy. Wyścig symulujemy nieaktualnym odczytem: pierwsze `_wiersz`
    „nie widzi" wiersza, który już jest w bazie."""
    import modules.reports.uklad_service as serwis
    db.session.add(UkladDashboardu(user_id=uzytkownik.id,
                                   uklad=[{'typ': 'kpi', 'wymiar': None}]))
    db.session.commit()

    prawdziwy = serwis._wiersz
    wywolania = []

    def nieaktualny_pierwszy_odczyt(user):
        wywolania.append(user.id)
        return None if len(wywolania) == 1 else prawdziwy(user)

    monkeypatch.setattr(serwis, '_wiersz', nieaktualny_pierwszy_odczyt)
    zapisz_uklad(uzytkownik, [Instancja('wnioski')])

    assert len(wywolania) == 2, 'serwis nie wrócił po wiersz po IntegrityError'
    assert UkladDashboardu.query.filter_by(user_id=uzytkownik.id).count() == 1
    assert uklad_uzytkownika(uzytkownik)[0] == [Instancja('wnioski')]


def test_zapis_rownolegly_z_przywroceniem_domyslnego_nie_konczy_sie_500(uzytkownik, monkeypatch):
    """Przegląd gałęzi, D1. „Zapisz układ" w jednej karcie przeglądarki
    i „Przywróć domyślny" w drugiej: wiersz znika między naszym odczytem
    a UPDATE-em, który trafia w zero wierszy — SQLAlchemy rzuca wtedy
    StaleDataError, czyli 500 (zmierzone na MySQL 8.4). Wygrywa ostatni zapis,
    tak jak przy każdym innym wyścigu dwóch kart: wiersz powstaje od nowa.

    Symulacja: odczyt oddaje wiersz, po czym wiersz znika z bazy, a sesja
    trzyma jego nieaktualną kopię — dokładnie stan, w którym UPDATE nie ma
    czego zmienić."""
    import modules.reports.uklad_service as serwis
    zapisz_uklad(uzytkownik, [Instancja('kpi')])
    prawdziwy = serwis._wiersz
    skasowane = []

    def odczyt_i_skasowanie_przez_druga_karte(user):
        wiersz = prawdziwy(user)
        if wiersz is not None and not skasowane:
            skasowane.append(wiersz.id)
            db.session.expunge(wiersz)
            UkladDashboardu.query.filter_by(user_id=user.id).delete()
            db.session.commit()
            db.session.add(wiersz)   # sesja nadal wierzy, że wiersz jest w bazie
        return wiersz

    monkeypatch.setattr(serwis, '_wiersz', odczyt_i_skasowanie_przez_druga_karte)
    zapisz_uklad(uzytkownik, [Instancja('wnioski')])

    assert skasowane, 'symulacja nie zadziałała — wiersz nie zniknął'
    monkeypatch.setattr(serwis, '_wiersz', prawdziwy)
    db.session.expire_all()
    assert UkladDashboardu.query.filter_by(user_id=uzytkownik.id).count() == 1
    assert uklad_uzytkownika(uzytkownik)[0] == [Instancja('wnioski')]


def test_wiersz_z_null_w_kolumnie_to_uszkodzony_wiersz_a_nie_brak_wiersza(uzytkownik, caplog):
    """Przegląd gałęzi, D3. Kolumna jest NOT NULL, więc Python `None` może
    przyjść wyłącznie z dokumentu JSON `null` — czyli z ręcznej edycji bazy.
    To uszkodzony wiersz: pusty pulpit, JEDNA pominięta pozycja i ostrzeżenie
    w logu. Do przeglądu był to po cichu pusty pulpit bez śladu.

    Brak wiersza zostaje czymś innym: układ domyślny (test niżej w pliku
    i `test_uzytkownik_bez_wiersza_dostaje_uklad_domyslny`)."""
    import logging
    from sqlalchemy import text
    db.session.execute(text(
        "INSERT INTO reports_dashboard_layouts (user_id, uklad, updated_at) "
        "VALUES (:u, 'null', '2026-09-23 10:00:00')"), {'u': uzytkownik.id})
    db.session.commit()
    with caplog.at_level(logging.WARNING, logger='reports.uklad'):
        uklad, pominietych = uklad_uzytkownika(uzytkownik)
    assert uklad == []
    assert pominietych == 1
    assert any(r.name == 'reports.uklad' and r.levelno >= logging.WARNING
               for r in caplog.records)


def test_brak_wiersza_nadal_daje_uklad_domyslny_bez_pominietych(uzytkownik, caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger='reports.uklad'):
        uklad, pominietych = uklad_uzytkownika(uzytkownik)
    assert uklad == list(UKLAD_DOMYSLNY)
    assert pominietych == 0
    assert not [r for r in caplog.records if r.name == 'reports.uklad']


def test_zapis_odswieza_znacznik_czasu(uzytkownik):
    """Drugi zapis ma PODBIĆ znacznik czasu z pierwszego. Rozdzielczość
    zegara testu bywa zbyt gruba, żeby dwa zapisy z rzędu naturalnie dały
    różne `datetime.utcnow()` — cofamy więc ręcznie znacznik po pierwszym
    zapisie, żeby drugi zapis miał jednoznacznie niższy próg do przebicia,
    zamiast tylko sprawdzać, że znacznik JEST, co przechodziłoby nawet
    bez działającego `onupdate`."""
    zapisz_uklad(uzytkownik, [Instancja('kpi')])
    wiersz = UkladDashboardu.query.filter_by(user_id=uzytkownik.id).first()
    assert wiersz.updated_at is not None
    stary_znacznik = datetime.utcnow() - timedelta(days=1)
    wiersz.updated_at = stary_znacznik
    db.session.commit()

    zapisz_uklad(uzytkownik, [Instancja('wnioski')])
    wiersz = UkladDashboardu.query.filter_by(user_id=uzytkownik.id).first()
    assert wiersz.updated_at > stary_znacznik
