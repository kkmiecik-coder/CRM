# -*- coding: utf-8 -*-
"""
Uprawnienia druku etykiet po rozdziale Wykańczania na Krawędzie i Lakiernię.

LABEL_PRINTER_ALLOWED_STATIONS to wartość RUNTIME w prod_config, edytowalna
z panelu admina. Grep po repo jej nie znajdzie, a zmiana nazwy stanowiska
w kodzie jej nie rusza. Stary kod 'finishing' zostawiony w tym wierszu znaczy
po rozdziale Wykańczania „tablet Krawędzi nie ma prawa drukować" — i to bez
żadnego błędu w logach, bo guard w print_labels_batch tylko porównuje stringi.

Migracja przepisuje tę wartość, ale jej REPLACE operuje na CSV bez spacji
(',finishing,'), więc wpis 'formatting, finishing' ją omija. Normalizacja
przy odczycie jest jedyną rzeczą, która łapie taki wariant.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import ProductionConfig
from modules.production.services.label_print_service import (
    StationNotAllowed,
    _load_config,
    print_labels_batch,
)
from modules.users.models import User
# Importy wymagane, żeby topologiczne sortowanie FK w create_all znalazło tabelę
# 'users' (ProductionConfig.updated_by ma ForeignKey('users.id'), models.py:743)
# — ten sam powód co w tests/test_mobile_complete_bl_sync_queue.py.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (User, ProductionConfig)]

AKTOR = {'type': 'user', 'id': 1}


@pytest.fixture()
def app():
    aplikacja = Flask(__name__)
    aplikacja.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    aplikacja.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    aplikacja.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    db.init_app(aplikacja)
    with aplikacja.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield aplikacja
        db.session.remove()


def _ustaw_dozwolone_stanowiska(wartosc):
    db.session.query(ProductionConfig).delete()
    db.session.add(ProductionConfig(
        config_key='LABEL_PRINTER_ALLOWED_STATIONS',
        config_value=wartosc,
    ))
    db.session.commit()


def test_stary_kod_finishing_w_konfiguracji_czyta_sie_jako_edges(app):
    _ustaw_dozwolone_stanowiska('formatting,packaging,finishing')

    assert _load_config()['allowed_stations'] == ['formatting', 'packaging', 'edges']


def test_spacja_po_przecinku_nie_chroni_starego_kodu(app):
    """Migracja podmienia dosłownie ',finishing,' — taki wpis ją omija."""
    _ustaw_dozwolone_stanowiska('formatting, finishing')

    assert _load_config()['allowed_stations'] == ['formatting', 'edges']


def test_tablet_krawedzi_drukuje_gdy_w_konfiguracji_zostal_stary_kod(app):
    """
    Guard stoi PRZED wcześniejszym wyjściem dla pustej listy produktów
    (label_print_service.py:458 vs :464), więc pusta lista wystarczy,
    żeby zbadać samo uprawnienie i nie dotknąć gniazda TCP drukarki.
    """
    _ustaw_dozwolone_stanowiska('formatting,packaging,finishing')

    wynik = print_labels_batch([], 'edges', AKTOR)

    assert wynik['success'] is False
    assert wynik['message'] == 'Brak produktów do wydrukowania.'


def test_stary_kod_nie_jest_juz_uprawnieniem_na_poziomie_serwisu(app):
    """
    Granica odpowiedzialności: serwis przyjmuje WYŁĄCZNIE kody kanoniczne.
    Alias rozwija router (mobile_print_label_single mobile_api.py:681
    i mobile_print_labels_for_order :708 — oba omijają _resolve_station_code
    i czytają g.device.station_code wprost, więc muszą być owinięte osobno).
    Gdyby normalizacja siedziała też tutaj, połowiczne wdrożenie W2 przeszłoby
    niezauważone i wyszłoby dopiero po zdjęciu aliasu.
    """
    _ustaw_dozwolone_stanowiska('formatting,packaging,finishing')

    with pytest.raises(StationNotAllowed):
        print_labels_batch([], 'finishing', AKTOR)


def test_stanowisko_spoza_listy_nadal_dostaje_wyjatek(app):
    _ustaw_dozwolone_stanowiska('formatting,packaging,finishing')

    with pytest.raises(StationNotAllowed):
        print_labels_batch([], 'cutting', AKTOR)


def test_pusta_konfiguracja_wraca_do_defaultu_a_nie_pustej_listy(app):
    """
    Wzmocnienie: `str(allowed_raw).split(',') if s.strip()` dla pustego
    configu (same przecinki albo pusty string) daje listę pustą, a `or
    list(DEFAULT_CONFIG['allowed_stations'])` ma to wyłapać. Implementacja,
    która przenosi normalizację PRZED wyrażenie `or` (np. najpierw buduje
    listę znormalizowanych kodów z pustego wejścia, a dopiero potem sprawdza
    prawdziwość), łatwo gubi ten fallback, bo pusta lista jest falsy tak samo
    przed jak i po normalizacji — ale warto mieć na to jawny test.
    """
    _ustaw_dozwolone_stanowiska('')

    assert _load_config()['allowed_stations'] == ['formatting', 'packaging']


def test_sam_stary_kod_bez_innych_stanowisk_daje_liste_z_edges(app):
    """
    Wzmocnienie: konfiguracja złożona WYŁĄCZNIE ze starego kodu (bez żadnego
    kanonicznego stanowiska obok) też ma się znormalizować, a nie np. trafić
    w gałąź fallbacku do DEFAULT_CONFIG (co przywróciłoby 'packaging', którego
    admin świadomie nie chciał tu mieć).
    """
    _ustaw_dozwolone_stanowiska('finishing')

    assert _load_config()['allowed_stations'] == ['edges']
