# -*- coding: utf-8 -*-
"""
Obsada stanowisk na dashboardzie produkcji — kto stoi TERAZ przy maszynie.

Źródłem jest sesja pracy bez `ended_at`, a nie ostatni event stanowiska:
pracownik, który zamknął zmianę, nie ma już stać na liście, choćby jego
eventy były najświeższe na hali.

Obsada jest LISTĄ, nie polem. Praca zespołowa to N sesji z jednym
`session_group` (komentarz przy ProductionWorkerSession), więc funkcja
zwracająca jedno nazwisko gubiłaby resztę brygady — i to po cichu, bo nic
by o tym nie krzyknęło.
"""
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionWorker, ProductionWorkerSession, get_local_now,
)
from modules.production.services.worker_stats_service import obsada_stanowisk
from modules.users.models import User
# Importy „na sucho": prod_workers.user_id celuje w users, users.multiplier_id
# w multipliers i dalej. SQLAlchemy nie zbuduje tabeli, dopóki cel klucza
# obcego nie jest zarejestrowany w metadanych — same tabele tworzymy poniżej.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (User, ProductionWorker, ProductionWorkerSession)]


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


# Doba testowa liczy się od DZISIAJ, nie od literału. obsada_stanowisk()
# zawęża wynik do bieżącej doby po get_local_now(), więc sesje z zaszytą datą
# przestawały być „dzisiejsze" nazajutrz po napisaniu testu — sześć z dziesięciu
# testów w tym pliku zaczynało padać następnego dnia, bez żadnej zmiany w kodzie.
# Testy, które pinują zegar monkeypatchem, muszą pinować go do TEJ SAMEJ doby,
# inaczej wracamy do tego samego rozjazdu.
_DZIS = get_local_now().date()


def _o(godzina, minuta=0, dzien=None):
    """Moment na dzisiejszej (albo wskazanej) dobie — zamiast literału daty."""
    return datetime.combine(dzien or _DZIS, time(godzina, minuta))


def _pracownik(imie, nazwisko, kolor=None):
    w = ProductionWorker(first_name=imie, last_name=nazwisko, color_hex=kolor)
    db.session.add(w)
    db.session.flush()
    return w


def _sesja(pracownik, stanowisko, godzina=8, grupa='g1', zamknieta=False):
    start = _o(godzina)
    s = ProductionWorkerSession(
        worker_id=pracownik.id,
        station_code=stanowisko,
        session_group=grupa,
        started_at=start,
        last_activity_at=start,
        ended_at=_o(16) if zamknieta else None,
        work_date=_DZIS,
    )
    db.session.add(s)
    db.session.flush()
    return s


def test_obsada_bierze_tylko_sesje_otwarte(app):
    """Zamknięta zmiana znika z kafelka od razu, bez czekania na dobę raportową."""
    stoi = _pracownik('Anna', 'Wilk')
    poszedl = _pracownik('Marek', 'Duda')
    _sesja(stoi, 'gluing')
    _sesja(poszedl, 'gluing', zamknieta=True)

    obsada = obsada_stanowisk()

    assert [o['nazwisko'] for o in obsada['gluing']] == ['Wilk']


def test_obsada_stanowiska_moze_byc_wieloosobowa(app):
    """
    Brygada na jednym tablecie to kilka sesji z tym samym session_group.
    Kolejność po starcie sesji, żeby lista nie skakała między odświeżeniami.
    """
    a = _pracownik('Anna', 'Wilk')
    b = _pracownik('Marek', 'Duda')
    c = _pracownik('Rafał', 'Nowak')
    _sesja(a, 'assembly', godzina=6, grupa='brygada')
    _sesja(b, 'assembly', godzina=7, grupa='brygada')
    _sesja(c, 'assembly', godzina=8, grupa='brygada')

    obsada = obsada_stanowisk()

    assert [o['nazwisko'] for o in obsada['assembly']] == ['Wilk', 'Duda', 'Nowak']


def test_stanowisko_bez_sesji_nie_ma_wpisu(app):
    """
    Brak klucza, a nie pusta lista — widok ma rozróżniać „nikt nie stoi" od
    „stanowiska nie ma w ogóle", i robi to jednym `.get(kod, [])`.
    """
    _sesja(_pracownik('Anna', 'Wilk'), 'gluing')

    obsada = obsada_stanowisk()

    assert 'edges' not in obsada


def test_obsada_niesie_inicjaly_i_kolor_pracownika(app):
    """
    color_hex istnieje w katalogu pracowników jako „tło kafelka z inicjałami" —
    dashboard ma go używać, zamiast dokładać drugie, własne kodowanie.
    """
    _sesja(_pracownik('Grzegorz', 'Lis', kolor='#3E7C59'), 'painting')

    osoba = obsada_stanowisk()['painting'][0]

    assert osoba['inicjaly'] == 'GL'
    assert osoba['kolor'] == '#3E7C59'
    assert osoba['imie'] == 'Grzegorz'


def test_stara_sesja_z_kodem_finishing_laduje_na_krawedziach(app):
    """
    Tablety sprzed rozdziału wykańczalni nadal mówią 'finishing'. Katalog
    zamienia ten kod na 'edges' NA WEJŚCIU (STATION_CODE_ALIASES) i obsada
    musi robić to samo — inaczej brygada z takiego tabletu nie pokaże się
    na żadnym wierszu, bo klucza 'finishing' nikt w widoku nie szuka.
    """
    _sesja(_pracownik('Kamil', 'Wrona'), 'finishing')

    obsada = obsada_stanowisk()

    assert 'finishing' not in obsada
    assert [o['nazwisko'] for o in obsada['edges']] == ['Wrona']


def test_wczorajsza_niedomknieta_sesja_nie_stoi_dzis_na_kafelku(app, monkeypatch):
    """
    Nocne domknięcie sesji wykonuje TABLET (mobile_api przyjmuje
    end_reason='night_cutoff' od klienta), a nie serwer. Tablet wyłączony
    przed północą zostawia sesję otwartą na zawsze — bez zawężenia do
    dzisiejszej doby wczorajsza brygada stałaby na kafelku przez kolejne dni,
    i to bez żadnego sygnału, że coś jest nie tak.
    """
    from modules.production.services import worker_stats_service as serwis

    wczoraj = _pracownik('Stefan', 'Zalega')
    s = _sesja(wczoraj, 'gluing')
    s.work_date = _DZIS - timedelta(days=1)
    db.session.flush()

    monkeypatch.setattr(serwis, 'get_local_now',
                        lambda: _o(10))

    assert 'gluing' not in obsada_stanowisk()


def test_obsada_niesie_czasy_do_dymka(app, monkeypatch):
    """
    Dymek ma mówić coś więcej niż nazwisko: od kiedy ktoś jest dziś na hali
    i kiedy ostatnio coś zrobił.

    `last_activity_at` odświeża KAŻDA akcja produkcyjna, a nie dotknięcie
    ekranu (komentarz przy ProductionWorkerSession), więc „ostatnia akcja"
    to naprawdę ostatnia wykonana sztuka, a nie ostatni ruch palcem.
    """
    from modules.production.services import worker_stats_service as serwis

    kto = _pracownik('Anna', 'Wilk')
    s = _sesja(kto, 'gluing', godzina=10)
    s.last_activity_at = _o(11, 38)
    db.session.flush()

    monkeypatch.setattr(serwis, 'get_local_now',
                        lambda: _o(11, 53))

    osoba = obsada_stanowisk()['gluing'][0]

    assert osoba['pierwsze'] == '10:00'
    assert osoba['ostatnia'] == '11:38'
    assert osoba['temu'] == 15


def test_pierwsze_logowanie_liczy_sie_z_calej_doby(app, monkeypatch):
    """
    Pracownik krąży w ciągu dnia między stanowiskami, a tablet zakłada nową
    sesję przy każdej zmianie profilu (zmierzone na produkcji: 30 sesji na
    7 osób jednej doby, 10 z nich krótszych niż dwie minuty). „Pierwsze
    logowanie" ma więc opisywać POCZĄTEK DNIA, a nie start bieżącej sesji —
    inaczej człowiek pracujący od 6:00 pokazywałby godzinę 11:10 tylko
    dlatego, że przełożył profil na innym tablecie.
    """
    from modules.production.services import worker_stats_service as serwis

    kto = _pracownik('Marek', 'Duda')
    rano = _sesja(kto, 'cutting', godzina=6, grupa='r')
    rano.ended_at = _o(9)
    _sesja(kto, 'gluing', godzina=9, grupa='p')
    db.session.flush()

    monkeypatch.setattr(serwis, 'get_local_now',
                        lambda: _o(12))

    assert obsada_stanowisk()['gluing'][0]['pierwsze'] == '06:00'


def test_obsada_nie_podaje_startu_biezacej_sesji(app):
    """
    Start bieżącej sesji świadomie NIE wychodzi z serwisu. Mierzy
    przeskakiwanie profilu na tablecie, nie czas pracy, a wystawiony
    w danych prosiłby się o wyświetlenie z powrotem.
    """
    _sesja(_pracownik('Anna', 'Wilk'), 'gluing')

    assert 'od' not in obsada_stanowisk()['gluing'][0]


def test_ten_sam_pracownik_liczy_sie_raz_na_stanowisku(app):
    """
    Dwie otwarte sesje tej samej osoby na jednym stanowisku to stan
    awaryjny (nieudane domknięcie przy zmianie tabletu), ale widok ma z tego
    wyjść z jednym awatarem, a nie z duplikatem obok duplikatu.
    """
    kto = _pracownik('Anna', 'Wilk')
    _sesja(kto, 'cutting', godzina=6, grupa='g1')
    _sesja(kto, 'cutting', godzina=9, grupa='g2')

    assert len(obsada_stanowisk()['cutting']) == 1
