# -*- coding: utf-8 -*-
"""
Agregat i eksport dziennego raportu produkcji.

Testy pilnują tego, na czym raport stoi i co już raz wywróciło się w projekcie:
filtr auto_skip/system, cofnięcia niewidoczne w netto, praca bez atrybucji,
oraz różnica między pustą komórką a zerem.
"""
import io
import os
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from openpyxl import load_workbook
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionReworkLog, ProductionStationEvent,
    ProductionStationEventWorker, ProductionWorker, ProductionWorkerSession,
)
from modules.production.sawmill.models import (
    SawmillAudit, SawmillCounter, SawmillDelivery, SawmillLog, SawmillOrder,
    SawmillSpecies, SawmillSupplier,
)
from modules.production.services import daily_report_export, daily_report_service
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker, ProductionReworkLog,
    SawmillSupplier, SawmillSpecies, SawmillCounter, SawmillDelivery,
    SawmillOrder, SawmillLog, SawmillAudit,
)]

# shipping_label_base64 jest typem MySQL-owym (LONGTEXT) — SQLite go nie zna.
# Ta sama podmiana co w tests/test_reports_service.py:51.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

# Data odniesienia. Stała, nie get_local_now(): raport kubełkuje po dobach,
# więc test liczony „od dziś" przechodziłby przez inne gałęzie w poniedziałek
# niż w sobotę.
PONIEDZIALEK = date(2026, 8, 10)


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


# ============================================================================
# POMOCNICZE
# ============================================================================

_licznik_zamowien = [0]


def _produkt(status='czeka_na_sklejanie', volume=0.5, quantity=10,
             deadline=None, wartosc=1000.0):
    """Zamówienie + pozycja. Własny licznik, bo baselinker_order_id jest UNIQUE."""
    _licznik_zamowien[0] += 1
    numer = _licznik_zamowien[0]
    order = ProductionOrder(baselinker_order_id=numer,
                            internal_order_number=f'26/{numer:05d}',
                            client_name='Klient Testowy')
    db.session.add(order)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=order.id, short_product_id=f'26{numer:03d}_1',
        product_sequence_in_order=1,
        original_product_name='Blat', quantity=quantity, volume_m3=volume,
        total_value_net=wartosc,
        current_status=status, deadline_date=deadline,
        created_at=datetime.combine(PONIEDZIALEK, time(9, 0)))
    db.session.add(produkt)
    db.session.commit()
    return produkt


def _event(produkt, station, delta, kiedy, source='mobile', worker=None):
    ev = ProductionStationEvent(
        production_item_id=produkt.id, station_code=station, delta=delta,
        quantity_done_after=max(0, delta), created_at=kiedy, source=source)
    db.session.add(ev)
    db.session.flush()
    if worker is not None:
        db.session.add(ProductionStationEventWorker(
            event_id=ev.id, worker_id=worker.id, share=1.0))
    db.session.commit()
    return ev


def _pracownik(imie='Adam'):
    w = ProductionWorker(first_name=imie, last_name='Nowak')
    db.session.add(w)
    db.session.commit()
    return w


def _sesja(pracownik, station, dzien, od=time(8, 0), godzin=8):
    start = datetime.combine(dzien, od)
    sesja = ProductionWorkerSession(
        worker_id=pracownik.id, station_code=station,
        session_group=f'g-{station}-{dzien}',
        started_at=start, last_activity_at=start,
        ended_at=start + timedelta(hours=godzin), work_date=dzien)
    db.session.add(sesja)
    db.session.commit()
    return sesja


def _stanowisko(dane, kod):
    """Wiersz stanowiska z wyniku zbierz_dane()."""
    return next(s for s in dane['stanowiska'] if s['kod'] == kod)


# ============================================================================
# PRZERÓB PER STANOWISKO
# ============================================================================

def test_przerob_per_stanowisko(app):
    with app.app_context():
        p = _produkt()
        _event(p, 'gluing', 6, datetime.combine(PONIEDZIALEK, time(10, 0)))

        dane = daily_report_service.zbierz_dane(PONIEDZIALEK)

        gluing = _stanowisko(dane, 'gluing')
        assert gluing['sztuki'] == 6
        assert gluing['m3'] == pytest.approx(3.0)          # 6 × 0.5
        assert gluing['wartosc_netto'] == pytest.approx(600.0)  # 1000 × 6/10


def test_zdarzenia_automatu_nie_licza_sie_do_przerobu(app):
    """
    complete_task() generuje eventy dla stanowisk POMIJANYCH (cut_to_size=False
    przeskakuje formatowanie i wykańczanie). Bez filtra formatowanie dostaje
    sztuki, których nikt nie tknął.
    """
    with app.app_context():
        p = _produkt()
        _event(p, 'formatting', 10, datetime.combine(PONIEDZIALEK, time(11, 0)),
               source='auto_skip')
        _event(p, 'finishing', 10, datetime.combine(PONIEDZIALEK, time(11, 0)),
               source='system')

        dane = daily_report_service.zbierz_dane(PONIEDZIALEK)

        assert _stanowisko(dane, 'formatting')['sztuki'] == 0
        assert _stanowisko(dane, 'finishing')['sztuki'] == 0


def test_wszystkie_stanowiska_obecne_takze_bez_pracy(app):
    """
    Arkusz ma stały układ wierszy — stanowisko bez pracy pokazuje zera,
    a nie znika. Kolejność 1:1 z procesem produkcyjnym.
    """
    with app.app_context():
        dane = daily_report_service.zbierz_dane(PONIEDZIALEK)

        kody = [s['kod'] for s in dane['stanowiska']]
        assert kody == ['cutting', 'assembly', 'gluing', 'formatting',
                        'finishing', 'painting', 'packaging']
        assert all(s['sztuki'] == 0 for s in dane['stanowiska'])


def test_praca_z_sasiedniego_dnia_nie_wchodzi(app):
    """Granica doby: 23:59:59 należy do dnia, 00:00:00 do następnego."""
    with app.app_context():
        p = _produkt()
        _event(p, 'gluing', 3, datetime.combine(PONIEDZIALEK, time(23, 59, 59)))
        _event(p, 'gluing', 5,
               datetime.combine(PONIEDZIALEK + timedelta(days=1), time(0, 0, 0)))

        dane = daily_report_service.zbierz_dane(PONIEDZIALEK)

        assert _stanowisko(dane, 'gluing')['sztuki'] == 3


# ============================================================================
# KOLEJKI, TERMINY, COFNIĘCIA
# ============================================================================

def test_cofniecia_liczone_osobno_od_netto(app):
    """
    Sztuki liczymy netto, więc dzień „10 zrobione, 4 cofnięte" i dzień
    „6 zrobione bez problemów" dają identyczne 6. Bez osobnej liczby cofnięć
    te dwa dni są w raporcie nieodróżnialne.
    """
    with app.app_context():
        p = _produkt()
        _event(p, 'gluing', 10, datetime.combine(PONIEDZIALEK, time(10, 0)))
        _event(p, 'gluing', -4, datetime.combine(PONIEDZIALEK, time(14, 0)))

        dane = daily_report_service.zbierz_dane(PONIEDZIALEK)

        gluing = _stanowisko(dane, 'gluing')
        assert gluing['sztuki'] == 6        # netto
        assert gluing['cofniecia'] == 4     # liczba dodatnia, nie -4


def test_kolejka_liczona_z_biezacego_statusu(app):
    """
    Definicja 1:1 z panelem (reports_service.dni_zapasu_stanowisk:313-321):
    pozycja czeka jako CAŁOŚĆ, z pełnym quantity, nawet jeśli jest w połowie
    zrobiona. Zawyża, i tak ma być — inaczej mail i dashboard pokazałyby dwie
    różne kolejki.
    """
    with app.app_context():
        _produkt(status='czeka_na_sklejanie', quantity=10, volume=0.5)
        _produkt(status='czeka_na_sklejanie', quantity=4, volume=0.25)
        _produkt(status='czeka_na_pakowanie', quantity=7, volume=0.1)

        dane = daily_report_service.zbierz_dane(PONIEDZIALEK)

        gluing = _stanowisko(dane, 'gluing')
        assert gluing['kolejka_szt'] == 14
        assert gluing['kolejka_m3'] == pytest.approx(6.0)   # 10×0.5 + 4×0.25

        assert _stanowisko(dane, 'packaging')['kolejka_szt'] == 7
        assert _stanowisko(dane, 'cutting')['kolejka_szt'] == 0


def test_koszyki_terminow(app):
    """Granice koszyków wg reports_service._koszyk_terminu — jedna definicja."""
    with app.app_context():
        _produkt(deadline=PONIEDZIALEK - timedelta(days=1))   # po terminie
        _produkt(deadline=PONIEDZIALEK)                        # dziś
        _produkt(deadline=PONIEDZIALEK + timedelta(days=2))    # 1-2 dni
        _produkt(deadline=PONIEDZIALEK + timedelta(days=7))    # 3-7 dni
        _produkt(deadline=PONIEDZIALEK + timedelta(days=8))    # 8+
        _produkt(deadline=None)                                # bez terminu

        terminy = daily_report_service.zbierz_dane(PONIEDZIALEK)['terminy']

        assert terminy == {'po_terminie': 1, 'dzis': 1, '1_2_dni': 1,
                           '3_7_dni': 1, '8_dni_plus': 1, 'bez_terminu': 1}


def test_pozycje_spakowane_nie_licza_sie_do_terminow(app):
    """
    Koszyki opisują to, co ZOSTAŁO do zrobienia. Pozycja spakowana albo
    anulowana nie jest zaległością i nie ma czego pilnować w jej terminie.
    """
    with app.app_context():
        _produkt(status='spakowane', deadline=PONIEDZIALEK - timedelta(days=5))
        _produkt(status='anulowane', deadline=PONIEDZIALEK - timedelta(days=5))
        _produkt(status='czeka_na_sklejanie', deadline=PONIEDZIALEK - timedelta(days=5))

        terminy = daily_report_service.zbierz_dane(PONIEDZIALEK)['terminy']

        assert terminy['po_terminie'] == 1


def test_wstrzymane_pozycje_licza_sie_do_terminow(app):
    """
    Wstrzymana pozycja po terminie MA być widoczna. Panel trzyma ją jako osobny
    segment wykresu „Termin vs postęp" (reports_service.py:120-124) — gdyby mail
    ją pomijał, to samo zamówienie byłoby po terminie na ekranie i nieobecne
    w raporcie.
    """
    with app.app_context():
        _produkt(status='wstrzymane', deadline=PONIEDZIALEK - timedelta(days=3))

        terminy = daily_report_service.zbierz_dane(PONIEDZIALEK)['terminy']

        assert terminy['po_terminie'] == 1


# ============================================================================
# LUDZIE I LICZBY ZBIORCZE
# ============================================================================

def test_wiersz_pracownika(app):
    with app.app_context():
        adam = _pracownik('Adam')
        _sesja(adam, 'gluing', PONIEDZIALEK, godzin=4)
        p = _produkt()
        _event(p, 'gluing', 8, datetime.combine(PONIEDZIALEK, time(10, 0)),
               worker=adam)

        ludzie = daily_report_service.zbierz_dane(PONIEDZIALEK)['ludzie']

        assert ludzie['osoby'] == 1
        wiersz = ludzie['wiersze'][0]
        assert wiersz['nazwa'] == 'Adam Nowak'
        assert wiersz['sztuki'] == pytest.approx(8.0)
        assert wiersz['zdarzenia'] == 1
        assert wiersz['godziny'] == pytest.approx(4.0)


def test_praca_bez_atrybucji_trafia_do_nieprzypisanych(app):
    """
    Bez tego wiersza suma z arkusza „Ludzie" nie zgadza się z sumą z arkusza
    „Stanowiska" i raport wygląda na zepsuty. Zasada z worker_stats_service:20-25.
    """
    with app.app_context():
        p = _produkt()
        _event(p, 'gluing', 5, datetime.combine(PONIEDZIALEK, time(10, 0)))

        ludzie = daily_report_service.zbierz_dane(PONIEDZIALEK)['ludzie']

        assert ludzie['wiersze'] == []
        assert ludzie['nieprzypisane']['sztuki'] == pytest.approx(5.0)
        assert ludzie['nieprzypisane']['m3'] == pytest.approx(2.5)


def test_tempo_bez_atrybucji_jest_puste_a_nie_zerowe(app):
    """
    Pracownik z sesją, ale bez ani jednej odbitej sztuki, ma dostać tempo
    „—", nie „0,0 m³/h". Zero przy nazwisku to zarzut bezczynności
    postawiony na podstawie braku danych.
    """
    with app.app_context():
        adam = _pracownik('Adam')
        _sesja(adam, 'gluing', PONIEDZIALEK, godzin=8)

        ludzie = daily_report_service.zbierz_dane(PONIEDZIALEK)['ludzie']

        wiersz = ludzie['wiersze'][0]
        assert wiersz['godziny'] == pytest.approx(8.0)
        assert wiersz['tempo'] is None


def test_wykonanie_zbiorcze_dnia(app):
    """Sumy nagłówkowe: sztuki, m³, wartość, pozycje, zamówienia, cofnięcia."""
    with app.app_context():
        p1 = _produkt(quantity=10, volume=0.5, wartosc=1000.0)
        p2 = _produkt(quantity=10, volume=0.2, wartosc=500.0)
        _event(p1, 'gluing', 6, datetime.combine(PONIEDZIALEK, time(10, 0)))
        _event(p2, 'packaging', 4, datetime.combine(PONIEDZIALEK, time(11, 0)))
        _event(p2, 'packaging', -1, datetime.combine(PONIEDZIALEK, time(15, 0)))

        wykonanie = daily_report_service.zbierz_dane(PONIEDZIALEK)['wykonanie']

        assert wykonanie['sztuki'] == 9              # 6 + 4 - 1
        assert wykonanie['m3'] == pytest.approx(3.6)  # 6×0.5 + 3×0.2
        assert wykonanie['wartosc_netto'] == pytest.approx(750.0)
        assert wykonanie['pozycje'] == 2
        assert wykonanie['zamowienia'] == 2
        assert wykonanie['cofniecia'] == 1


def test_dzien_bez_ruchu_daje_zera_a_nie_wyjatek(app):
    """Raport idzie także w dniu bez produkcji — brak maila ma znaczyć awarię."""
    with app.app_context():
        dane = daily_report_service.zbierz_dane(PONIEDZIALEK)

        assert dane['wykonanie']['sztuki'] == 0
        assert dane['ludzie']['osoby'] == 0
        assert dane['ludzie']['wiersze'] == []


# ============================================================================
# TRAKOWNIA
# ============================================================================

_licznik_klod = [0]


def _zlecenie_trakowni():
    """
    Dostawca → gatunek → dostawa → zlecenie. Pełny łańcuch, bo SawmillOrder ma
    delivery_id i species_id jako NOT NULL. Wzór: tests/test_sawmill_orders.py:68-80.
    """
    from decimal import Decimal

    supplier = SawmillSupplier(name='Tartak Testowy')
    species = SawmillSpecies(name='Dąb')
    db.session.add_all([supplier, species])
    db.session.flush()
    delivery = SawmillDelivery(supplier_id=supplier.id,
                               delivery_date=PONIEDZIALEK)
    db.session.add(delivery)
    db.session.flush()
    order = SawmillOrder(order_number='TRK/2026/001', delivery_id=delivery.id,
                         species_id=species.id,
                         declared_volume_m3=Decimal('80.000'))
    db.session.add(order)
    db.session.commit()
    return order


def _kloda(zlecenie, volume=1.5, kiedy=None, usunieta=False):
    """
    Kłoda mierzona na tablecie. measured_at, nie created_at — patrz test niżej.

    order_id i sequence_no są NOT NULL, więc kłoda zawsze wisi przy zleceniu,
    a numer w sekwencji nadaje własny licznik (para order_id+sequence_no jest
    UNIQUE).
    """
    _licznik_klod[0] += 1
    log = SawmillLog(
        order_id=zlecenie.id, sequence_no=_licznik_klod[0],
        mid_circumference_cm=120.0, length_cm=400.0,
        volume_m3=volume, is_deleted=usunieta,
        measured_at=kiedy or datetime.combine(PONIEDZIALEK, time(10, 0)))
    db.session.add(log)
    db.session.commit()
    return log


def test_blok_trakowni(app):
    with app.app_context():
        zlecenie = _zlecenie_trakowni()
        _kloda(zlecenie, volume=1.5)
        _kloda(zlecenie, volume=2.0)

        trakownia = daily_report_service.zbierz_dane(PONIEDZIALEK)['trakownia']

        assert trakownia['klody'] == 2
        assert trakownia['m3'] == pytest.approx(3.5)


def test_trakownia_liczy_po_measured_at_nie_created_at(app):
    """
    Tablet potrafi rano wysłać pomiary z wczorajszego popołudnia (kolejka
    offline). Mają się policzyć do dnia, w którym faktycznie powstały —
    ta sama zasada co w sawmill_dashboard_stats.
    """
    with app.app_context():
        zlecenie = _zlecenie_trakowni()
        _kloda(zlecenie, volume=1.0,
               kiedy=datetime.combine(PONIEDZIALEK - timedelta(days=1), time(16, 0)))
        _kloda(zlecenie, volume=3.0,
               kiedy=datetime.combine(PONIEDZIALEK, time(9, 0)))

        trakownia = daily_report_service.zbierz_dane(PONIEDZIALEK)['trakownia']

        assert trakownia['klody'] == 1
        assert trakownia['m3'] == pytest.approx(3.0)


def test_usuniete_klody_nie_licza_sie(app):
    with app.app_context():
        zlecenie = _zlecenie_trakowni()
        _kloda(zlecenie, volume=1.0)
        _kloda(zlecenie, volume=9.0, usunieta=True)

        trakownia = daily_report_service.zbierz_dane(PONIEDZIALEK)['trakownia']

        assert trakownia['klody'] == 1
        assert trakownia['m3'] == pytest.approx(1.0)


def test_modele_trakowni_uzywaja_czasu_lokalnego(app):
    """
    Kontener chodzi na UTC, reszta bazy zapisuje czas Europe/Warsaw. Dopóki
    trakownia używała datetime.now, jej wpisy były o 2 h wcześniejsze niż
    wszystko inne — a między 22:00 a północą wpadały do sąsiedniego dnia.
    """
    from modules.production.sawmill import models as sawmill_models

    kolumny = [
        sawmill_models.SawmillLog.__table__.c.created_at,
        sawmill_models.SawmillOrder.__table__.c.created_at,
        sawmill_models.SawmillAudit.__table__.c.created_at,
    ]
    # Po nazwie, nie po tożsamości obiektu: SQLAlchemy opakowuje callable
    # w ColumnDefault i porównanie `is` bywa zależne od wersji.
    for kolumna in kolumny:
        assert kolumna.default.arg.__name__ == 'get_local_now', (
            f'{kolumna} nadal używa czasu kontenera zamiast get_local_now')


def test_serwisy_trakowni_nie_nadpisuja_created_at(app, zegar):
    """
    Test wyżej patrzy WYŁĄCZNIE na definicję kolumny i przeszedłby także
    wtedy, gdyby ktoś z powrotem wstawił `created_at=datetime.now()` do
    konstruktora w add_log()/write_audit() — a to był właśnie znaleziony błąd:
    jawna wartość w konstruktorze unieważnia `default=` kolumny i SQLAlchemy
    nigdy jej nie woła.

    Dlatego tu jedziemy przez PRAWDZIWE serwisy, z zamrożonym zegarem
    lokalnym ustawionym na chwilę, w którą realny zegar kontenera nie ma jak
    trafić. Asercja czyta wartość PO commicie, czyli to, co faktycznie
    wylądowało w bazie.
    """
    from modules.production.sawmill.services.orders import add_log, write_audit

    chwila = zegar(datetime(2026, 1, 15, 3, 17, 42))

    with app.app_context():
        zlecenie = _zlecenie_trakowni()

        log = add_log(
            zlecenie,
            {'mid_circumference_cm': 120.0, 'length_cm': 400.0},
            measured_at=datetime.combine(PONIEDZIALEK, time(10, 0)))
        wpis = write_audit(zlecenie.id, 'log_create', log_id=log.id)
        db.session.commit()

        assert log.created_at == chwila, (
            'add_log() ustawia created_at jawnie zamiast zostawić default= kolumny')
        assert wpis.created_at == chwila, (
            'write_audit() ustawia created_at jawnie zamiast zostawić default= kolumny')
        # measured_at przychodzi Z ZEWNĄTRZ (czas z tabletu) i NIE ma się
        # równać zegarowi serwera — inaczej pomiar z kolejki offline
        # przypisałby się do doby wysyłki zamiast doby pomiaru.
        assert log.measured_at == datetime.combine(PONIEDZIALEK, time(10, 0))


# ============================================================================
# EKSPORT XLSX
# ============================================================================

def _pusty_raport():
    """Minimalny dict o kształcie kontraktu zbierz_dane() — bez bazy."""
    return {
        'dzien': PONIEDZIALEK,
        'wykonanie': {'sztuki': 0, 'm3': 0.0, 'wartosc_netto': 0.0,
                      'pozycje': 0, 'zamowienia': 0, 'cofniecia': 0},
        'ludzie': {'osoby': 0, 'godziny': 0.0, 'pokrycie_proc': 0.0,
                   'wiersze': [], 'nieprzypisane': {'sztuki': 0.0, 'm3': 0.0}},
        'trakownia': {'klody': 0, 'm3': 0.0},
        'stanowiska': [{'kod': 'gluing', 'etykieta': 'Sklejanie', 'sztuki': 6,
                        'm3': 3.0, 'wartosc_netto': 600.0, 'cofniecia': 1,
                        'kolejka_szt': 14, 'kolejka_m3': 6.0}],
        'terminy': {'po_terminie': 2, 'dzis': 1, '1_2_dni': 0,
                    '3_7_dni': 3, '8_dni_plus': 5, 'bez_terminu': 1},
    }


def test_naglowki_uzywaja_slowa_roznica():
    """Symbol delty jest zakazany w eksportach — czyta je księgowość."""
    wszystkie = daily_report_export.NAGLOWKI_STANOWISKA + daily_report_export.NAGLOWKI_LUDZIE
    assert not any('Δ' in h for h in wszystkie)


def test_plik_ma_trzy_arkusze_o_ustalonych_nazwach():
    wb = load_workbook(io.BytesIO(
        daily_report_export.build_daily_xlsx(_pusty_raport())))
    assert wb.sheetnames == ['Dzień', 'Stanowiska', 'Ludzie']


def test_arkusz_stanowiska_ma_naglowek_i_wiersze():
    wb = load_workbook(io.BytesIO(
        daily_report_export.build_daily_xlsx(_pusty_raport())))
    ws = wb['Stanowiska']

    assert [c.value for c in ws[1]] == list(daily_report_export.NAGLOWKI_STANOWISKA)
    assert ws.cell(row=2, column=1).value == 'Sklejanie'
    assert ws.cell(row=2, column=2).value == 6


def test_wartosci_stanowiska_zaokraglane_tak_samo_jak_suma():
    """
    get_station_work_per_day() liczy wartosc_netto jako total_value_net * delta
    / quantity, a kolejka_m3 jako sumę volume_m3 * quantity — oba to surowe
    wyniki dzielenia zmiennoprzecinkowego, bez zaokrąglenia. Wiersz SUMA JEST
    zaokrąglany, więc bez zaokrąglenia wiersza pojedynczego stanowiska komórka
    stanowiska pokazywała więcej cyfr po przecinku niż komórka SUMY tej samej
    kolumny, mimo że dla „ładnych" liczb (6, 600.0, 3.0) różnicy nie widać —
    dlatego test używa wartości, która się realnie nie dzieli.
    """
    dane = _pusty_raport()
    dane['stanowiska'][0]['wartosc_netto'] = 1000.0 * 7 / 3   # 2333.3333333333335
    dane['stanowiska'][0]['m3'] = 1 / 3                        # 0.3333333333333333
    dane['stanowiska'][0]['kolejka_m3'] = 2 / 3                # 0.6666666666666666
    dane['trakownia'] = {'klody': 12, 'm3': 8.4}

    wb = load_workbook(io.BytesIO(daily_report_export.build_daily_xlsx(dane)))
    ws = wb['Stanowiska']

    assert ws.cell(row=2, column=3).value == pytest.approx(0.333)      # m³
    assert ws.cell(row=2, column=4).value == pytest.approx(2333.33)    # wartość netto
    assert ws.cell(row=2, column=7).value == pytest.approx(0.667)      # kolejka m³

    # Zaokrąglanie nie może zamienić pustych komórek trakowni w zera —
    # _zaokr() musi przepuszczać None bez rzucania TypeError (round(None, 2)
    # rzuciłby wprost).
    wiersz_trakowni = ws.max_row - 1
    assert ws.cell(row=wiersz_trakowni, column=1).value == 'Trakownia'
    assert ws.cell(row=wiersz_trakowni, column=4).value is None
    assert ws.cell(row=wiersz_trakowni, column=6).value is None
    assert ws.cell(row=wiersz_trakowni, column=7).value is None


def test_trakownia_ma_puste_komorki_kolejki_a_nie_zera():
    """
    Trakownia nie ma statusów kolejki. Zero znaczyłoby „policzone i wyszło
    zero", a prawda brzmi „nie dotyczy" — openpyxl zapisuje None jako pustą
    komórkę. Ta sama zasada co w sawmill/services/exports.py:106-112.

    Wiersz trakowni składa EKSPORT z bloku dane['trakownia'] — agregat nie
    udaje, że trakownia jest ósmym stanowiskiem.
    """
    dane = _pusty_raport()
    dane['trakownia'] = {'klody': 12, 'm3': 8.4}

    wb = load_workbook(io.BytesIO(daily_report_export.build_daily_xlsx(dane)))
    ws = wb['Stanowiska']
    wiersz_trakowni = ws.max_row - 1   # przedostatni; ostatni to SUMA

    assert ws.cell(row=wiersz_trakowni, column=1).value == 'Trakownia'
    assert ws.cell(row=wiersz_trakowni, column=2).value == 12    # kłody
    assert ws.cell(row=wiersz_trakowni, column=4).value is None  # wartość netto
    assert ws.cell(row=wiersz_trakowni, column=6).value is None  # kolejka szt.
    assert ws.cell(row=wiersz_trakowni, column=7).value is None  # kolejka m³


def test_arkusz_stanowiska_konczy_sie_wierszem_suma():
    """
    Suma obejmuje wyłącznie stanowiska produkcyjne. Trakownia mierzy surowiec
    przed wejściem na halę — doliczenie jej m³ liczyłoby ten sam materiał
    drugi raz.
    """
    dane = _pusty_raport()
    dane['trakownia'] = {'klody': 12, 'm3': 8.4}
    dane['stanowiska'].append({
        'kod': 'packaging', 'etykieta': 'Pakowanie', 'sztuki': 4, 'm3': 1.0,
        'wartosc_netto': 200.0, 'cofniecia': 0,
        'kolejka_szt': 7, 'kolejka_m3': 0.7,
    })

    wb = load_workbook(io.BytesIO(daily_report_export.build_daily_xlsx(dane)))
    ws = wb['Stanowiska']

    assert ws.cell(row=ws.max_row, column=1).value == 'SUMA'
    assert ws.cell(row=ws.max_row, column=2).value == 10   # 6 + 4, bez trakowni
    assert ws.cell(row=ws.max_row, column=3).value == pytest.approx(4.0)  # bez 8.4


def test_arkusz_ludzie_ma_wiersz_nieprzypisane():
    """
    Bez tego wiersza suma arkusza „Ludzie" nie zgadza się z sumą arkusza
    „Stanowiska" i raport wygląda na zepsuty.
    """
    dane = _pusty_raport()
    dane['ludzie']['wiersze'] = [{
        'nazwa': 'Adam Nowak', 'stanowiska': 'Sklejanie', 'sztuki': 8.0,
        'm3': 4.0, 'zdarzenia': 3, 'godziny': 7.5, 'tempo': 0.533,
    }]
    dane['ludzie']['nieprzypisane'] = {'sztuki': 5.0, 'm3': 2.5}

    wb = load_workbook(io.BytesIO(daily_report_export.build_daily_xlsx(dane)))
    ws = wb['Ludzie']
    etykiety = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)]

    assert 'Adam Nowak' in etykiety
    assert 'Nieprzypisane' in etykiety


def test_puste_tempo_zostaje_pusta_komorka():
    dane = _pusty_raport()
    dane['ludzie']['wiersze'] = [{
        'nazwa': 'Adam Nowak', 'stanowiska': '', 'sztuki': 0.0, 'm3': 0.0,
        'zdarzenia': 0, 'godziny': 8.0, 'tempo': None,
    }]

    wb = load_workbook(io.BytesIO(daily_report_export.build_daily_xlsx(dane)))
    ws = wb['Ludzie']

    assert ws.cell(row=2, column=7).value is None


def test_polskie_znaki_przechodza_bez_okaleczenia():
    """
    W repo jest safe_str(), które wycina diakrytyki — to legacy, nie wymóg
    openpyxl. Ten test pilnuje, żeby nikt go tu nie skopiował.
    """
    dane = _pusty_raport()
    dane['stanowiska'][0]['etykieta'] = 'Wykańczanie — dąb, jesion'

    wb = load_workbook(io.BytesIO(daily_report_export.build_daily_xlsx(dane)))

    assert wb['Stanowiska'].cell(row=2, column=1).value == 'Wykańczanie — dąb, jesion'


def test_nazwa_pliku_jest_ascii():
    """
    Polskie znaki w nagłówku Content-Disposition rwą odpowiedź (WSGI koduje
    nagłówki w latin-1) — patrz tests/test_nda_filename_header.py.
    """
    nazwa = daily_report_export.nazwa_pliku(PONIEDZIALEK)

    assert nazwa == 'Raport_produkcji_2026-08-10.xlsx'
    nazwa.encode('ascii')   # rzuci UnicodeEncodeError, jeśli się zepsuje
