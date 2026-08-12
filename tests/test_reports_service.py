# -*- coding: utf-8 -*-
"""
Agregaty wykresów zakładki Raporty (modules/production/services/reports_service).

Testy pilnują trzech rzeczy, na których ten moduł stoi i które już raz się
w projekcie wywróciły:

1. JEDNA DEFINICJA „ZROBIONE" — filtr source NOT IN ('auto_skip','system')
   w KAŻDYM zapytaniu liczącym pracę człowieka. Bez niego dwa sąsiednie widgety
   pokazują dwie różne liczby dla tego samego pytania (błąd P4 z audytu).
2. PUSTE STANY — każdy wykres ma ich kilka i znaczą CO INNEGO: „brak kolejki"
   to nie to samo co „stanowisko nic nie zrobiło", a dzień bez produkcji to
   dziura w linii, nie zero.
3. BADGE „TRWA NAUKA" — liczony z danych, dwa wymiary naraz, ma umieć WRÓCIĆ.
   Tabela prawdy niżej jest wprost kontraktem uzgodnionym z właścicielem.

Wszystko chodzi na SQLite w pamięci — stąd brak DAYOFWEEK/TIMESTAMPDIFF
w samym serwisie.
"""
import os
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy import event
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionReworkLog, ProductionStationEvent,
    ProductionStationEventWorker, ProductionWorker, ProductionWorkerSession,
)
from modules.production.services import reports_service
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker, ProductionReworkLog,
)]

ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

# Data odniesienia wszystkich testów. Stała, nie get_local_now(): wykresy
# kubełkują po dobach i po dniach tygodnia, więc test liczony „od dziś"
# przechodziłby przez inne gałęzie w poniedziałek niż w sobotę.
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
        # HOUR()/MINUTE() istnieją w MySQL, ale nie w SQLite — a timeline
        # widgetu „Wykonanie stanowiska w dniu" liczy z nich kubełki co pół
        # godziny. Bez tych dwóch funkcji ŻADEN test nie mógł dotknąć tego
        # endpointu i dlatego przez cały czas nie miał ani jednego (grep po
        # 'station-output' w tests/ dawał zero trafień), mimo że to najczęściej
        # otwierany widget zakładki. Rejestrujemy je zamiast omijać endpoint.
        @event.listens_for(db.engine, 'connect')
        def _funkcje_czasu(polaczenie, _rekord):
            polaczenie.create_function(
                'hour', 1, lambda s: int(str(s)[11:13]) if s else 0)
            polaczenie.create_function(
                'minute', 1, lambda s: int(str(s)[14:16]) if s else 0)

        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


@pytest.fixture()
def zalogowany(monkeypatch):
    """
    Endpointy logują `current_user.id` (także na ścieżce błędu), a testowa
    aplikacja nie ma login_managera. Podmieniamy proxy w przestrzeni modułu,
    żeby test dotykał prawdziwego ciała endpointu, a nie jego kopii.
    """
    from modules.production.routers.api import reports_api

    monkeypatch.setattr(reports_api, 'current_user',
                        type('UzytkownikTestowy', (), {'id': 1, 'role': 'admin'})())
    return reports_api


# ============================================================================
# POMOCNICZE
# ============================================================================

_licznik_zamowien = [0]


def _produkt(status='czeka_na_sklejanie', volume=0.5, quantity=10,
             deadline=None, utworzono=None):
    # Własny licznik, bo baselinker_order_id jest UNIQUE — testy z kilkoma
    # pozycjami wywracałyby się na kolizji, a nie na tym, co sprawdzają.
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
        current_status=status, deadline_date=deadline,
        created_at=utworzono or datetime.combine(PONIEDZIALEK, time(9, 0)))
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
        worker_id=pracownik.id, station_code=station, session_group=f'g-{station}-{dzien}',
        started_at=start, last_activity_at=start,
        ended_at=start + timedelta(hours=godzin), work_date=dzien)
    db.session.add(sesja)
    db.session.commit()
    return sesja


# ============================================================================
# WYKRES 1 — DNI ZAPASU PRZED STANOWISKIEM
# ============================================================================

def test_dni_zapasu_na_pustej_bazie_nie_wywala_sie(app):
    """
    Brak eventów = brak tempa. Zwracamy puste okno, a front pisze „za mało
    danych" — bo policzenie zera i podzielenie przez nie byłoby gorsze niż
    przyznanie się, że nie wiadomo.
    """
    with app.app_context():
        wynik = reports_service.dni_zapasu_stanowisk(end_date=PONIEDZIALEK)

        assert wynik == {'stations': [], 'okno_dni': 0,
                         'okno_od': None, 'okno_do': None}


def test_dni_zapasu_liczy_kolejke_przez_tempo(app):
    with app.app_context():
        # 10 szt. × 0.5 m³ czeka na sklejanie, a sklejanie robi 1 m³ dziennie.
        _produkt(status='czeka_na_sklejanie', volume=0.5, quantity=10)
        robiony = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(robiony, 'gluing', 2, datetime.combine(PONIEDZIALEK, time(9, 0)))

        wynik = reports_service.dni_zapasu_stanowisk(end_date=PONIEDZIALEK)
        gluing = next(s for s in wynik['stations'] if s['station_code'] == 'gluing')

        assert wynik['okno_dni'] == 1
        assert gluing['pending_m3'] == 5.0
        assert gluing['window_m3'] == 1.0
        assert gluing['days_of_supply'] == 5.0
        assert gluing['reason'] is None


def test_dni_zapasu_odroznia_brak_przerobu_od_pustki(app):
    """
    Dwa RÓŻNE zera. Kolejka bez przerobu to najgorszy możliwy stan (słupek na
    górze, bez liczby), a stanowisko bez kolejki i bez pracy nie jest wąskim
    gardłem i ma nie dominować wykresu.
    """
    with app.app_context():
        _produkt(status='czeka_na_lakiernie', volume=0.5, quantity=4)
        robiony = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(robiony, 'gluing', 2, datetime.combine(PONIEDZIALEK, time(9, 0)))

        wynik = reports_service.dni_zapasu_stanowisk(end_date=PONIEDZIALEK)
        painting = next(s for s in wynik['stations'] if s['station_code'] == 'painting')
        cutting = next(s for s in wynik['stations'] if s['station_code'] == 'cutting')

        assert painting['reason'] == 'brak_przerobu'
        assert painting['days_of_supply'] is None
        assert cutting['reason'] == 'pusto'
        assert cutting['days_of_supply'] == 0.0
        # Brak przerobu idzie na samą górę, pustki na sam dół.
        assert wynik['stations'][0]['station_code'] == 'painting'
        assert wynik['stations'][-1]['reason'] == 'pusto'


def test_dni_zapasu_nie_daje_kredytu_eventom_automatu(app):
    """
    170 eventów auto_skip i 1503 'system' w bazie produkcyjnej. Wliczone do
    mianownika podnoszą tempo stanowiska, którego nikt nie tknął, i kolejka
    „rozpuszcza się" na wykresie.
    """
    with app.app_context():
        _produkt(status='czeka_na_formatowanie', volume=0.5, quantity=4)
        robiony = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(robiony, 'formatting', 50, datetime.combine(PONIEDZIALEK, time(9, 0)),
               source='auto_skip')
        _event(robiony, 'gluing', 2, datetime.combine(PONIEDZIALEK, time(9, 0)))

        wynik = reports_service.dni_zapasu_stanowisk(end_date=PONIEDZIALEK)
        formatting = next(s for s in wynik['stations']
                          if s['station_code'] == 'formatting')

        assert formatting['window_m3'] == 0.0
        assert formatting['reason'] == 'brak_przerobu'


def test_dni_zapasu_ujemny_mianownik_idzie_w_brak_przerobu(app):
    """
    Seria cofnięć potrafi dać w wąskim oknie mianownik ujemny. Ujemne „dni
    zapasu" nie znaczą nic — warunek jest napisany jako <= 0, nie == 0.
    """
    with app.app_context():
        _produkt(status='czeka_na_sklejanie', volume=0.5, quantity=4)
        robiony = _produkt(status='spakowane', volume=0.5, quantity=200)
        # Doba jako całość jest normalna (pakowanie zrobiło swoje), ale samo
        # sklejanie wyszło na minus po serii cofnięć.
        _event(robiony, 'packaging', 100, datetime.combine(PONIEDZIALEK, time(9, 0)))
        _event(robiony, 'gluing', 2, datetime.combine(PONIEDZIALEK, time(9, 0)))
        _event(robiony, 'gluing', -5, datetime.combine(PONIEDZIALEK, time(11, 0)))

        gluing = next(s for s in reports_service.dni_zapasu_stanowisk(
            end_date=PONIEDZIALEK)['stations'] if s['station_code'] == 'gluing')

        assert gluing['window_m3'] < 0
        assert gluing['reason'] == 'brak_przerobu'
        assert gluing['days_of_supply'] is None


def test_dzien_roboczy_odsiewa_sobote_serwisowa(app):
    """
    2026-08-01 (sobota): 0.043 m³ przy średniej ~4 m³. Taka doba nie tylko
    zaniża średnią, ale WYPYCHA z okna jeden realny dzień roboczy.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=1.0, quantity=1000)
        _event(produkt, 'gluing', 100, datetime.combine(date(2026, 8, 6), time(9, 0)))
        _event(produkt, 'gluing', 100, datetime.combine(date(2026, 8, 7), time(9, 0)))
        # Sobota serwisowa — ułamek dobowej średniej (na produkcji: 0.043 m³
        # przy średniej ~4 m³), więc do mianownika tempa nie wchodzi.
        _event(produkt, 'gluing', 1, datetime.combine(date(2026, 8, 8), time(10, 0)))

        dni = reports_service.dni_robocze_hali(end_date=date(2026, 8, 10))

        assert dni == [date(2026, 8, 6), date(2026, 8, 7)]


# ============================================================================
# WYKRES 2 — TERMIN VS POSTĘP
# ============================================================================

def test_termin_zawsze_ma_szesc_koszykow(app):
    """
    Oś jest SKALĄ PILNOŚCI, nie listą kategorii z danych. Gdyby puste koszyki
    wypadały, przy dobrej robocie oś miałaby dwa słupki, przy złej sześć —
    i nie dałoby się porównać dwóch dni.
    """
    with app.app_context():
        wynik = reports_service.termin_vs_postep()

        assert wynik['buckets'] == list(reports_service.KOSZYKI_TERMINU)
        assert len(wynik['bucket_labels']) == 6
        assert wynik['totals']['m3'] == [0.0] * 6
        assert wynik['datasets'] == []
        assert wynik['items'] == []


def test_termin_pomija_spakowane_i_anulowane(app):
    """
    2133 spakowane pozycje mają termin w przeszłości. Bez tego filtra słupek
    „Po terminie" pokazuje 83.7 m³ zamiast 0.889 — 94-krotne zawyżenie i wykres
    opowiada o historii zamiast o dzisiaj.
    """
    with app.app_context():
        from modules.production.models import get_local_now
        wczoraj = get_local_now().date() - timedelta(days=1)
        _produkt(status='spakowane', deadline=wczoraj, volume=1.0, quantity=1)
        _produkt(status='anulowane', deadline=wczoraj, volume=1.0, quantity=1)
        _produkt(status='czeka_na_sklejanie', deadline=wczoraj, volume=0.25, quantity=2)

        wynik = reports_service.termin_vs_postep()

        assert wynik['totals']['items_total'] == 1
        assert wynik['totals']['m3'][0] == 0.5      # koszyk „Po terminie"


def test_termin_pokazuje_etapy_spoza_stanowisk(app):
    """
    Mapa dashboardu zna sześć stanowisk i wycięłaby po cichu logistykę (89%
    słupka „Po terminie") oraz lakiernię (49% słupka 3-7 dni). Statusy, które
    stanowiskiem nie są, dostają własny, jawnie nazwany segment.
    """
    with app.app_context():
        from modules.production.models import get_local_now
        dzis = get_local_now().date()
        _produkt(status='czeka_na_logistyke', deadline=dzis, volume=0.5, quantity=2)
        _produkt(status='czeka_na_lakiernie', deadline=dzis, volume=0.5, quantity=2)

        etykiety = {d['label'] for d in reports_service.termin_vs_postep()['datasets']}

        assert etykiety == {'Logistyka', 'Lakiernia'}


def test_termin_przycina_liste_pozycji_z_flaga(app):
    """Limit ma być JAWNY — po cichu ucięta lista to najgorsza wersja obu opcji."""
    with app.app_context():
        for _ in range(3):
            _produkt(status='czeka_na_sklejanie', volume=0.5, quantity=1)

        wynik = reports_service.termin_vs_postep(limit_pozycji=2)

        assert len(wynik['items']) == 2
        assert wynik['items_truncated'] is True


# ============================================================================
# WYKRES 3 — WEJŚCIE VS WYJŚCIE
# ============================================================================

def test_przeplyw_ma_pelna_os_z_weekendami(app):
    """
    Weekendów NIE wolno wyciąć — odwrotnie niż przy wykresach 1 i 4. Hala
    pracuje pn-pt, ale zamówienia wpadają też w niedzielę i wycięcie weekendu
    skasowałoby realny napływ: wykres skłamałby w stronę „nadążamy".
    """
    with app.app_context():
        niedziela = date(2026, 8, 9)
        # Starsza pozycja, żeby oś nie została przycięta do pierwszego produktu.
        _produkt(status='spakowane', volume=0.5, quantity=2,
                 utworzono=datetime.combine(date(2026, 8, 1), time(12, 0)))
        _produkt(status='czeka_na_sklejanie', volume=0.5, quantity=2,
                 utworzono=datetime.combine(niedziela, time(12, 0)))

        wynik = reports_service.wejscie_vs_wyjscie(date(2026, 8, 7), date(2026, 8, 11))
        daty = [d['date'] for d in wynik['days']]

        assert len(daty) == 5
        assert '2026-08-08' in daty and '2026-08-09' in daty
        assert wynik['days'][2]['in_m3'] == 1.0        # niedzielne wejście
        assert wynik['total_out_m3'] == 0.0


def test_przeplyw_kumuluje_po_stronie_serwera(app):
    """
    cumulative_diff_m3 liczy serwer, żeby dwa widgety nie skumulowały tego
    samego inaczej. Linia startuje od zera w pierwszym dniu ZAKRESU — mierzy
    dryf w oknie, a nie stan magazynu.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=4,
                           utworzono=datetime.combine(PONIEDZIALEK, time(8, 0)))
        _event(produkt, 'packaging', 2,
               datetime.combine(PONIEDZIALEK + timedelta(days=1), time(9, 0)))

        wynik = reports_service.wejscie_vs_wyjscie(PONIEDZIALEK,
                                                   PONIEDZIALEK + timedelta(days=1))

        assert [d['cumulative_diff_m3'] for d in wynik['days']] == [2.0, 1.0]
        assert wynik['cumulative_end_m3'] == 1.0


def test_przeplyw_nie_liczy_anulowanych_po_stronie_wejscia(app):
    """Anulowana pozycja nigdy nie przejdzie przez pakowanie — trzymanie jej
    po stronie wejścia trwale i nieodwracalnie zawyżałoby linię skumulowaną."""
    with app.app_context():
        _produkt(status='anulowane', volume=1.0, quantity=3,
                 utworzono=datetime.combine(PONIEDZIALEK, time(8, 0)))

        wynik = reports_service.wejscie_vs_wyjscie(PONIEDZIALEK, PONIEDZIALEK)

        assert wynik['total_in_m3'] == 0.0


def test_przeplyw_zakres_sprzed_pierwszego_produktu_zwraca_zera(app):
    """Pusta lista dni wygląda u frontu jak awaria; pełna oś zer to informacja."""
    with app.app_context():
        _produkt(utworzono=datetime.combine(PONIEDZIALEK, time(8, 0)))

        wynik = reports_service.wejscie_vs_wyjscie(date(2026, 1, 1), date(2026, 1, 3))

        assert len(wynik['days']) == 3
        assert wynik['total_in_m3'] == 0.0
        assert wynik['range_trimmed'] is False


def test_przeplyw_agreguje_tygodniowo_przy_dlugim_zakresie(app):
    """365 słupków dziennych zlewa się w kaszę — serwer oddaje ten sam kształt
    JSON, tylko `date` to poniedziałek tygodnia."""
    with app.app_context():
        _produkt(utworzono=datetime.combine(PONIEDZIALEK - timedelta(days=250),
                                            time(8, 0)))

        wynik = reports_service.wejscie_vs_wyjscie(
            PONIEDZIALEK - timedelta(days=200), PONIEDZIALEK)

        assert wynik['granularity'] == 'tydzien'
        assert all(date.fromisoformat(d['date']).weekday() == 0
                   for d in wynik['days'])


# ============================================================================
# WYKRES 4 — HEATMAPA GODZINA × DZIEŃ TYGODNIA
# ============================================================================

def test_heatmapa_normalizuje_przez_krotnosc_dnia_tygodnia(app):
    """
    Okno 30-dniowe potrafi mieć pięć poniedziałków i cztery czwartki. Surowe
    sumy zawyżałyby początek tygodnia o 25% i heatmapa skłamałaby dokładnie
    o tym, o co się ją pyta — o rytm tygodnia.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=1.0, quantity=100)
        for tydzien in range(2):
            _event(produkt, 'gluing', 1,
                   datetime.combine(PONIEDZIALEK + timedelta(days=7 * tydzien),
                                    time(7, 30)))

        wynik = reports_service.heatmapa_godzinowa(PONIEDZIALEK,
                                                   PONIEDZIALEK + timedelta(days=13))

        assert wynik['weekday_occurrences'] == [2, 2, 2, 2, 2, 2, 2]
        assert wynik['grid_m3'][0][7] == 1.0      # 2 m³ / 2 poniedziałki
        assert wynik['grid_events'][0][7] == 2


def test_heatmapa_ma_wlasna_skale_dla_komorek_ujemnych(app):
    """
    max liczony z WARTOŚCI BEZWZGLĘDNYCH: przy max(v) komórka ujemna dostałaby
    ten sam kolor co zerowa i cofnięcia stałyby się niewidoczne.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=1.0, quantity=100)
        _event(produkt, 'gluing', 1, datetime.combine(PONIEDZIALEK, time(7, 0)))
        _event(produkt, 'gluing', -3, datetime.combine(PONIEDZIALEK, time(22, 0)))

        wynik = reports_service.heatmapa_godzinowa(PONIEDZIALEK, PONIEDZIALEK)

        assert wynik['has_negative'] is True
        assert wynik['max_abs_m3'] == 3.0
        assert wynik['grid_m3'][0][22] == -3.0


def test_heatmapa_pomija_eventy_automatu(app):
    """
    Eventy 'system' powstają w chwili complete_task(), czyli w godzinie, w której
    człowiek zamknął CAŁKIEM INNE stanowisko. Bez filtra heatmapa świeciłaby
    fantomowym ciepłem w godzinach pakowania.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=1.0, quantity=100)
        _event(produkt, 'finishing', 5, datetime.combine(PONIEDZIALEK, time(14, 0)),
               source='system')

        wynik = reports_service.heatmapa_godzinowa(PONIEDZIALEK, PONIEDZIALEK)

        assert wynik['events_total'] == 0
        assert wynik['max_abs_m3'] == 0.0
        assert wynik['has_negative'] is False
        assert len(wynik['grid_m3']) == 7 and len(wynik['grid_m3'][0]) == 24


# ============================================================================
# WYKRES 5 — OBSADA VS PRZERÓB
# ============================================================================

def test_obsada_laczy_godziny_z_przerobem(app):
    with app.app_context():
        adam = _pracownik()
        _sesja(adam, 'gluing', PONIEDZIALEK, godzin=4)
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(produkt, 'gluing', 4, datetime.combine(PONIEDZIALEK, time(9, 0)),
               worker=adam)

        wynik = reports_service.obsada_vs_przerob(PONIEDZIALEK, PONIEDZIALEK)
        gluing = next(w for w in wynik['rows'] if w['station_code'] == 'gluing')

        assert gluing['person_hours'] == 4.0
        assert gluing['m3'] == 2.0
        assert gluing['m3_per_person_hour'] == 0.5
        assert wynik['summary']['person_hours'] == 4.0


def test_obsada_pokazuje_stanowisko_bez_sesji_i_bez_eventow(app):
    """
    Dwa różne, ważne stany: praca bez zalogowania (dzisiejsza norma) i sesja
    bez wyniku (ktoś usiadł i jeszcze nic nie odbił). Tempa nie liczymy tam,
    gdzie nie ma godzin — zero sugerowałoby pomiar, a to brak pomiaru.
    """
    with app.app_context():
        adam = _pracownik()
        _sesja(adam, 'packaging', PONIEDZIALEK, godzin=2)
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(produkt, 'gluing', 4, datetime.combine(PONIEDZIALEK, time(9, 0)))

        wynik = reports_service.obsada_vs_przerob(PONIEDZIALEK, PONIEDZIALEK)
        kody = {w['station_code']: w for w in wynik['rows']}

        assert set(kody) == {'gluing', 'packaging'}
        assert kody['gluing']['person_hours'] == 0.0
        assert kody['gluing']['m3_per_person_hour'] is None
        assert kody['packaging']['m3'] == 0.0
        assert kody['packaging']['m3_per_person_hour'] == 0.0
        assert wynik['summary']['stations_with_hours'] == 1
        assert wynik['summary']['stations_with_work'] == 1


def test_obsada_wyklucza_trakownie_z_tempa(app):
    """
    Trakownia ma sesje, ale nie ma eventów stanowiskowych (to rejestr surowca),
    więc wyszłoby „8 h / 0 m³" czytane jako bezczynność ludzi.
    """
    with app.app_context():
        adam = _pracownik()
        _sesja(adam, 'sawmill', PONIEDZIALEK, godzin=8)

        wiersz = reports_service.obsada_vs_przerob(
            PONIEDZIALEK, PONIEDZIALEK)['rows'][0]

        assert wiersz['station_code'] == 'sawmill'
        assert wiersz['in_pipeline'] is False
        assert wiersz['person_hours'] == 8.0
        assert wiersz['m3_per_person_hour'] is None


def test_obsada_sumuje_z_minut_nie_z_zaokraglonych_godzin(app):
    """Siedem stanowisk × do 0.05 h błędu dawało 234.6 zamiast 234.7 i kafelek
    kłócił się z tabelą pod nim."""
    with app.app_context():
        adam = _pracownik()
        for kod in ('gluing', 'packaging', 'formatting'):
            sesja = _sesja(adam, kod, PONIEDZIALEK, godzin=1)
            sesja.ended_at = sesja.started_at + timedelta(minutes=33)
        db.session.commit()

        wynik = reports_service.obsada_vs_przerob(PONIEDZIALEK, PONIEDZIALEK)

        assert wynik['summary']['person_minutes'] == 99
        assert wynik['summary']['person_hours'] == round(99 / 60, 1)
        # Suma zaokrąglonych wierszy dałaby 1.8 h — o 0.2 h więcej niż realne
        # 99 minut. Kafelek liczony tak kłóciłby się z tabelą pod nim.
        assert wynik['summary']['person_hours'] != sum(
            w['person_hours'] for w in wynik['rows'])


# ============================================================================
# WYKRES 6 — POKRYCIE ATRYBUCJĄ
# ============================================================================

def test_pokrycie_nie_przekracza_stu_procent_przy_cofnieciach(app):
    """
    Poprzednia ścieżka brała ABS dopiero z sumy netto per (dzień, stanowisko),
    więc cofnięcia kasowały się z dorobkami W MIANOWNIKU i pokrycie potrafiło
    przekroczyć 100%. ABS na poziomie EVENTU czyni licznik podzbiorem
    mianownika — wynik jest zamknięty w 0-100% z definicji.
    """
    with app.app_context():
        adam = _pracownik()
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        kiedy = datetime.combine(PONIEDZIALEK, time(9, 0))
        _event(produkt, 'gluing', 10, kiedy, worker=adam)     # z podpisem
        _event(produkt, 'gluing', 20, kiedy)                  # bez podpisu
        _event(produkt, 'gluing', -19, kiedy)                 # cofnięcie, bez podpisu

        punkt = reports_service.pokrycie_atrybucji_dziennie(
            PONIEDZIALEK, PONIEDZIALEK)['points'][0]

        # Netto bez atrybucji to +1, ale RUCHU bez atrybucji jest 39 sztuk.
        assert punkt['pieces_abs'] == 49
        assert punkt['pieces_attributed'] == 10
        assert punkt['coverage_pct'] == 20.4
        assert punkt['negative_events'] == 1


def test_pokrycie_dzien_bez_produkcji_to_dziura_nie_zero(app):
    """
    Płaska linia na zerze czyta się jak „pracowali i nikt się nie podpisał",
    a to nieprawda. Dzień bez produkcji zostaje na osi z coverage_pct = None.
    """
    with app.app_context():
        adam = _pracownik()
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(produkt, 'gluing', 4, datetime.combine(PONIEDZIALEK, time(9, 0)),
               worker=adam)

        wynik = reports_service.pokrycie_atrybucji_dziennie(
            PONIEDZIALEK, PONIEDZIALEK + timedelta(days=1))

        assert [p['coverage_pct'] for p in wynik['points']] == [100.0, None]
        assert wynik['summary']['days_with_data'] == 1
        assert wynik['summary']['days_in_range'] == 2


def test_pokrycie_pomija_eventy_automatu(app):
    """
    1503 eventy 'system' i 170 'auto_skip' nigdy nie dostaną atrybucji, bo
    nikt ich nie wykonał. Bez filtra pokrycie sufitowałoby kilka punktów
    poniżej 100% NA ZAWSZE i nigdy nie dałoby zielonego światła.
    """
    with app.app_context():
        adam = _pracownik()
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        kiedy = datetime.combine(PONIEDZIALEK, time(9, 0))
        _event(produkt, 'gluing', 4, kiedy, worker=adam)
        _event(produkt, 'formatting', 4, kiedy, source='auto_skip')
        _event(produkt, 'finishing', 4, kiedy, source='system')

        wynik = reports_service.pokrycie_atrybucji_dziennie(PONIEDZIALEK, PONIEDZIALEK)

        assert wynik['summary']['coverage_pct'] == 100.0
        assert wynik['summary']['pieces_abs'] == 4


def test_pokrycie_oznacza_mala_probke(app):
    """Dzień z kilkoma sztukami daje skoki 0%/100%, które nie znaczą nic —
    front ma o tym wiedzieć z danych, nie zgadywać z wykresu."""
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(produkt, 'gluing', 2, datetime.combine(PONIEDZIALEK, time(9, 0)))

        punkt = reports_service.pokrycie_atrybucji_dziennie(
            PONIEDZIALEK, PONIEDZIALEK)['points'][0]

        assert punkt['small_sample'] is True
        assert punkt['coverage_pct'] == 0.0


def test_pokrycie_filtruje_po_stanowisku(app):
    with app.app_context():
        adam = _pracownik()
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        kiedy = datetime.combine(PONIEDZIALEK, time(9, 0))
        _event(produkt, 'gluing', 10, kiedy, worker=adam)
        _event(produkt, 'packaging', 10, kiedy)

        wynik = reports_service.pokrycie_atrybucji_dziennie(
            PONIEDZIALEK, PONIEDZIALEK, station='packaging')

        assert wynik['station'] == 'packaging'
        assert wynik['summary']['coverage_pct'] == 0.0
        assert wynik['summary']['pieces_abs'] == 10


# ============================================================================
# WYKRES 7 — DORÓBKI
# ============================================================================

def test_dorobki_nie_zapalaja_wykresu_ponizej_progu(app):
    """
    Sześć zgłoszeń z piętnastu tygodni to nie jest wykres — to panel. Słupek
    „prawie zero doróbek" czyta się jako „jakość świetna", a znaczy „sześć
    z siedmiu stanowisk nie ma jak zgłosić".
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        db.session.add(ProductionReworkLog(
            original_product_id=produkt.id, rework_product_id=produkt.id,
            quantity=2, rejected_at_station='formatting',
            returned_to_station='cutting', reason_category='wymiary',
            created_at=datetime.combine(PONIEDZIALEK, time(13, 0))))
        _event(produkt, 'formatting', 20, datetime.combine(PONIEDZIALEK, time(9, 0)))
        db.session.commit()

        wynik = reports_service.rejestracja_dorobek(PONIEDZIALEK, PONIEDZIALEK)

        assert wynik['entries'] == 1
        assert wynik['pieces'] == 2
        assert wynik['formatted_pieces'] == 20
        assert wynik['rate_pct'] == 10.0
        assert wynik['threshold_met'] is False
        assert [s['station_code'] for s in wynik['reporting_stations']] == ['formatting']
        assert wynik['stations_total'] == 7


def test_dorobki_mianownik_ma_filtr_zrodla(app):
    """
    Licznik (prod_rework_log) filtru nie potrzebuje — nie ma kolumny source
    i nie ma automatycznego pisarza. Ale mianownik to już eventy: bez filtra
    urośnie o auto_skip i wskaźnik doróbek sztucznie spadnie. Ten sam błąd
    co P4, tylko w drugiej pozycji ułamka.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(produkt, 'formatting', 20, datetime.combine(PONIEDZIALEK, time(9, 0)))
        _event(produkt, 'formatting', 80, datetime.combine(PONIEDZIALEK, time(9, 5)),
               source='auto_skip')

        assert reports_service.rejestracja_dorobek(
            PONIEDZIALEK, PONIEDZIALEK)['formatted_pieces'] == 20


def test_dorobki_pusty_zakres_nie_dzieli_przez_zero(app):
    with app.app_context():
        wynik = reports_service.rejestracja_dorobek(PONIEDZIALEK, PONIEDZIALEK)

        assert wynik['entries'] == 0
        assert wynik['rate_pct'] is None
        assert wynik['weeks'] == []
        assert wynik['first_entry'] is None


# ============================================================================
# BADGE „TRWA NAUKA" — TABELA PRAWDY
# ============================================================================

@pytest.mark.parametrize('opis,dni,prog,z_profilami,pracujace,oczekiwane', [
    ('start wdrożenia',                      3, 14, 5, 7, True),
    ('przed wdrożeniem',                     0, 14, 0, 7, True),
    ('komplet dni, jeden tablet padł',      14, 14, 6, 7, True),
    ('komplet obu wymiarów — badge gaśnie', 14, 14, 7, 7, False),
    ('komplet stanowisk, za mało dni',       9, 14, 7, 7, True),
    ('nikt nic nie robił w oknie',          14, 14, 0, 0, False),
    ('COFNIĘCIE: tablet wypadł po 100%',    14, 14, 5, 6, True),
])
def test_tabela_prawdy_badge_nauki(opis, dni, prog, z_profilami, pracujace, oczekiwane):
    """
    Kontrakt uzgodniony z właścicielem: dwa wymiary naraz, oba Z DANYCH.
    Badge znika, gdy OBA są spełnione, i WRACA, gdy którykolwiek się cofnie —
    dlatego ostatni wiersz jest najważniejszy. Żadnego odliczania „zostało X
    dni": taka reguła nie potrafi wrócić, gdy jeden tablet wypadnie.
    """
    wynik = reports_service.zloz_stan_nauki(dni, prog, z_profilami, pracujace)

    assert wynik['learning'] is oczekiwane, opis


def test_badge_nie_pokazuje_wiecej_dni_niz_prog():
    """„Dane z 16 z 14 dni" to komunikat, który podważa sam siebie."""
    wynik = reports_service.zloz_stan_nauki(16, 14, 7, 7)

    assert 'dane z 14 z 14 dni' in wynik['text']
    assert wynik['days_with_data'] == 16      # surowa liczba zostaje w danych


def test_badge_bez_pracy_w_oknie_nie_mowi_o_stanowiskach():
    """
    Pusty tydzień (urlop, przestój) nie ma jak zmierzyć pokrycia. Klauzula
    o stanowiskach znika z tekstu, a wymiar uznajemy za spełniony — inaczej
    badge wisiałby w nieskończoność, nie niosąc żadnej informacji.
    """
    wynik = reports_service.zloz_stan_nauki(0, 14, 0, 0)

    assert 'profile na' not in wynik['text']
    assert wynik['stations_ok'] is True


def test_stan_nauki_na_pustej_bazie(app):
    with app.app_context():
        wynik = reports_service.stan_nauki(end_date=PONIEDZIALEK)

        assert wynik['learning'] is True
        assert wynik['days_with_data'] == 0
        assert wynik['production_days_in_window'] == 0
        assert wynik['window_start'] is None
        assert wynik['window_end'] == PONIEDZIALEK.isoformat()


def test_stan_nauki_liczy_dni_produkcyjne_a_nie_kalendarzowe(app):
    """
    Hala pracuje pn-pt, więc w 14 dniach kalendarza mieści się góra 10 dni
    roboczych — „14 z 14 dni" liczone po kalendarzu NIGDY by się nie spełniło
    i badge zostałby na ekranie na zawsze. Okno to ostatnie 14 dni, w których
    cokolwiek się wydarzyło.
    """
    with app.app_context():
        adam = _pracownik()
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        # Trzy dni produkcyjne rozrzucone przez dwa tygodnie, sesja w jednym.
        for przesuniecie in (0, 7, 10):
            _event(produkt, 'gluing', 2,
                   datetime.combine(PONIEDZIALEK - timedelta(days=przesuniecie),
                                    time(9, 0)))
        _sesja(adam, 'gluing', PONIEDZIALEK)

        wynik = reports_service.stan_nauki(end_date=PONIEDZIALEK, prog_dni=14)

        assert wynik['production_days_in_window'] == 3
        assert wynik['days_with_data'] == 1
        assert wynik['stations_working'] == 1
        assert wynik['stations_with_profiles'] == 1
        assert wynik['learning'] is True        # czas jeszcze nie dobił do progu


def test_stan_nauki_przecina_stanowiska_z_mianownikiem(app):
    """
    Sesja na trakowni — której prod_station_events w ogóle nie zna — dałaby
    „2 z 1 stanowisk", czyli badge z liczbą powyżej 100%.
    """
    with app.app_context():
        adam = _pracownik()
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(produkt, 'gluing', 2, datetime.combine(PONIEDZIALEK, time(9, 0)))
        _sesja(adam, 'gluing', PONIEDZIALEK)
        _sesja(adam, 'sawmill', PONIEDZIALEK)

        wynik = reports_service.stan_nauki(end_date=PONIEDZIALEK)

        assert wynik['stations_working'] == 1
        assert wynik['stations_with_profiles'] == 1


def test_stan_nauki_wymienia_stanowiska_bez_profili(app):
    """Tooltip z listą gasi pytanie „czemu 1 z 2" zanim padnie."""
    with app.app_context():
        adam = _pracownik()
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        kiedy = datetime.combine(PONIEDZIALEK, time(9, 0))
        _event(produkt, 'gluing', 2, kiedy)
        _event(produkt, 'painting', 2, kiedy)
        _sesja(adam, 'gluing', PONIEDZIALEK)

        wynik = reports_service.stan_nauki(end_date=PONIEDZIALEK)

        assert wynik['stations_without_profiles'] == ['Lakiernia']


# ============================================================================
# BADGE — OBA WYMIARY OSOBNO I POWRÓT PO COFNIĘCIU
# ============================================================================
#
# Tabela prawdy wyżej pilnuje samej decyzji „świeci / nie świeci". Ta sekcja
# pilnuje dwóch rzeczy, których tabela nie obejmuje, a które są całym sensem
# tego rozwiązania:
#   1. badge musi POWIEDZIEĆ, KTÓRY wymiar nie domknął — inaczej nie da się
#      go zgasić, bo nie wiadomo, czy czekać, czy iść włączyć tablet;
#   2. badge musi umieć WRÓCIĆ. To jedyna przewaga liczenia z danych nad
#      odliczaniem „zostało X dni" — kalendarz nigdy nie cofa się sam.

@pytest.mark.parametrize('opis,dni,z_profilami,pracujace,czas_ok,pokrycie_ok', [
    ('czas OK, pokrycie jeszcze nie',  14, 5, 7, True,  False),
    ('pokrycie OK, czas jeszcze nie',   9, 7, 7, False, True),
])
def test_badge_rozroznia_ktory_wymiar_nie_domknal(opis, dni, z_profilami,
                                                  pracujace, czas_ok, pokrycie_ok):
    """
    Dwa wymiary są liczone i raportowane NIEZALEŻNIE. Jeden wspólny boolean
    „uczy się" kazałby zgadywać, czy hala ma czekać kolejny tydzień, czy
    podnieść tablet, który nie wstał — a to dwie różne czynności dla dwóch
    różnych osób.
    """
    wynik = reports_service.zloz_stan_nauki(dni, 14, z_profilami, pracujace)

    assert wynik['learning'] is True, opis
    assert wynik['days_ok'] is czas_ok, opis
    assert wynik['stations_ok'] is pokrycie_ok, opis
    # Oba liczniki są w tekście ZAWSZE — także ten, który już się domknął.
    # Bez tego użytkownik nie wie, czy wymiar jest zaliczony, czy pominięty.
    assert f'dane z {min(dni, 14)} z 14 dni' in wynik['text'], opis
    assert f'profile na {z_profilami} z {pracujace} pracujących' in wynik['text'], opis


def test_badge_wraca_gdy_nowe_stanowisko_rusza_bez_profili(app):
    """
    NAJWAŻNIEJSZY test badge'a — POWRÓT po cofnięciu się POKRYCIA.

    Scenariusz z hali: wszystko domknięte, badge zgaszony. Rusza ósme
    stanowisko (albo tablet po reinstalacji APK bez profili) i pokrycie
    spada z 1/1 na 1/2. Badge MUSI zapalić się z powrotem — odliczanie
    kalendarzowe („zostało X dni") w tym miejscu milczy, bo jego licznik
    już doszedł do zera i nie umie się cofnąć.

    Trzeci krok pilnuje, że to nie jest zatrzask: po dołożeniu profilu na
    nowym stanowisku badge znowu gaśnie.
    """
    with app.app_context():
        adam = _pracownik()
        produkt = _produkt(status='spakowane', volume=0.5, quantity=1000)
        dni = [PONIEDZIALEK - timedelta(days=i) for i in (2, 1, 0)]
        for dzien in dni:
            _event(produkt, 'gluing', 2, datetime.combine(dzien, time(9, 0)))
            _sesja(adam, 'gluing', dzien)

        zgaszony = reports_service.stan_nauki(end_date=PONIEDZIALEK, prog_dni=3)
        assert zgaszony['learning'] is False
        assert (zgaszony['days_ok'], zgaszony['stations_ok']) == (True, True)

        # Lakiernia zaczyna raportować pracę, ale nikt się na niej nie loguje.
        _event(produkt, 'painting', 2, datetime.combine(PONIEDZIALEK, time(10, 0)))

        wrocil = reports_service.stan_nauki(end_date=PONIEDZIALEK, prog_dni=3)
        assert wrocil['learning'] is True
        assert wrocil['days_ok'] is True              # czas się nie cofnął
        assert wrocil['stations_ok'] is False         # cofnęło się pokrycie
        assert (wrocil['stations_with_profiles'], wrocil['stations_working']) == (1, 2)
        assert wrocil['stations_without_profiles'] == ['Lakiernia']

        # Profil na lakierni — badge gaśnie ponownie, bez restartu i bez czekania.
        _sesja(adam, 'painting', PONIEDZIALEK)

        assert reports_service.stan_nauki(
            end_date=PONIEDZIALEK, prog_dni=3)['learning'] is False


def test_badge_wraca_gdy_dzien_bez_sesji_wchodzi_do_okna(app):
    """
    POWRÓT po cofnięciu się CZASU — druga połowa tej samej gwarancji.

    Okno to ostatnie `prog_dni` dni PRODUKCYJNYCH, więc gdy hala przepracuje
    kolejny dzień bez ani jednej sesji, ten dzień wpycha do okna dziurę
    i wymiar czasu spada z 3/3 na 2/3. Licznik kalendarzowy pokazałby w tym
    momencie „gotowe" i skłamałby: dzień pracy BEZ profili właśnie się zdarzył.
    """
    with app.app_context():
        adam = _pracownik()
        produkt = _produkt(status='spakowane', volume=0.5, quantity=1000)
        dni = [PONIEDZIALEK - timedelta(days=i) for i in (3, 2, 1)]
        for dzien in dni:
            _event(produkt, 'gluing', 2, datetime.combine(dzien, time(9, 0)))
            _sesja(adam, 'gluing', dzien)

        assert reports_service.stan_nauki(
            end_date=PONIEDZIALEK - timedelta(days=1), prog_dni=3)['learning'] is False

        # Kolejny dzień produkcyjny — praca jest, sesji nie ma (tablet nie wstał).
        _event(produkt, 'gluing', 2, datetime.combine(PONIEDZIALEK, time(9, 0)))

        wrocil = reports_service.stan_nauki(end_date=PONIEDZIALEK, prog_dni=3)

        assert wrocil['learning'] is True
        assert wrocil['days_with_data'] == 2
        assert wrocil['production_days_in_window'] == 3
        assert wrocil['days_ok'] is False
        assert wrocil['stations_ok'] is True          # pokrycie się nie cofnęło
        assert 'dane z 2 z 3 dni' in wrocil['text']


# ============================================================================
# WYKRES 8 — WKŁAD OSÓB NA JEDNYM STANOWISKU
# ============================================================================

def _brygada(produkt, station, delta, kiedy, pracownicy, source='mobile'):
    """Jeden event podpisany przez KILKA osób — udział 1/N, jak w produkcji."""
    ev = ProductionStationEvent(
        production_item_id=produkt.id, station_code=station, delta=delta,
        quantity_done_after=max(0, delta), created_at=kiedy, source=source)
    db.session.add(ev)
    db.session.flush()
    for pracownik in pracownicy:
        db.session.add(ProductionStationEventWorker(
            event_id=ev.id, worker_id=pracownik.id, share=1.0 / len(pracownicy)))
    db.session.commit()
    return ev


def test_wklad_sortuje_osoby_malejaco_po_m3(app):
    """
    W obrębie JEDNEGO stanowiska porównanie osób jest uczciwe i o to w tym
    widgecie chodzi — kolejność ustala backend, żeby dwa odświeżenia tego
    samego zakresu nie dały dwóch różnych wykresów.
    """
    with app.app_context():
        adam = _pracownik('Adam')
        borys = _pracownik('Borys')
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        kiedy = datetime.combine(PONIEDZIALEK, time(9, 0))
        _event(produkt, 'gluing', 2, kiedy, worker=adam)
        _event(produkt, 'gluing', 6, kiedy, worker=borys)

        wynik = reports_service.wklad_pracownikow_na_stanowisku(
            'gluing', PONIEDZIALEK, PONIEDZIALEK)

        assert [o['worker_name'] for o in wynik['workers']] == \
            ['Borys Nowak', 'Adam Nowak']
        assert [o['m3'] for o in wynik['workers']] == [3.0, 1.0]
        assert [o['pieces'] for o in wynik['workers']] == [6.0, 2.0]
        assert wynik['station_label'] == 'Sklejanie'
        assert wynik['summary']['workers_count'] == 2


def test_wklad_nie_liczy_eventow_automatu(app):
    """
    Filtr source NOT IN ('auto_skip','system') jest OBOWIĄZKOWY. Bez niego ten
    widget pokazuje inne liczby niż sąsiedni „Wykonanie stanowiska w dniu"
    i nikt nie umie wytłumaczyć różnicy — to był potwierdzony błąd P4.
    """
    with app.app_context():
        adam = _pracownik('Adam')
        produkt = _produkt(status='spakowane', volume=0.5, quantity=1000)
        kiedy = datetime.combine(PONIEDZIALEK, time(9, 0))
        _event(produkt, 'formatting', 4, kiedy, worker=adam)

        przed = reports_service.wklad_pracownikow_na_stanowisku(
            'formatting', PONIEDZIALEK, PONIEDZIALEK)

        # Automat na tym samym stanowisku, w tej samej dobie — raz z atrybucją,
        # raz bez. Filtr po SOURCE musi zatrzymać oba: gdyby odsiewał tylko
        # „eventy bez wiersza atrybucji", pierwszy z nich dałby pracownikowi
        # kredyt za 400 sztuk, których fizycznie nikt nie wykonał.
        _event(produkt, 'formatting', 400, kiedy, source='auto_skip', worker=adam)
        _event(produkt, 'formatting', 400, kiedy, source='system')

        po = reports_service.wklad_pracownikow_na_stanowisku(
            'formatting', PONIEDZIALEK, PONIEDZIALEK)

        assert po == przed
        assert po['workers'][0]['pieces'] == 4.0
        assert po['workers'][0]['m3'] == 2.0
        assert po['summary']['station_pieces'] == 4.0
        assert po['unassigned']['present'] is False


def test_wklad_dokleja_slupek_nieprzypisanych_do_sumy_stanowiska(app):
    """
    Wykres z samymi ludźmi kłamie: sugeruje, że podpisana robota to cała
    produkcja stanowiska. Osoby + „Nieprzypisane" muszą złożyć się na tę samą
    liczbę, którą pokazuje „Wykonanie stanowiska w dniu".
    """
    with app.app_context():
        adam = _pracownik('Adam')
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        kiedy = datetime.combine(PONIEDZIALEK, time(9, 0))
        _event(produkt, 'packaging', 4, kiedy, worker=adam)
        _event(produkt, 'packaging', 6, kiedy)          # bez podpisu

        wynik = reports_service.wklad_pracownikow_na_stanowisku(
            'packaging', PONIEDZIALEK, PONIEDZIALEK)
        p = wynik['summary']

        assert wynik['unassigned']['pieces'] == 6.0
        assert wynik['unassigned']['m3'] == 3.0
        assert wynik['unassigned']['present'] is True
        assert wynik['unassigned']['negative'] is False
        assert p['attributed_m3'] + p['unassigned_m3'] == p['station_m3'] == 5.0
        assert p['station_pieces'] == 10.0
        assert p['attribution_coverage_pct'] == 40.0
        assert p['sums_match'] is True
        assert p['empty_reason'] is None


def test_wklad_odroznia_brak_pracy_od_braku_profili(app):
    """
    Dwa RÓŻNE puste stany: „stanowisko nic nie zrobiło" to informacja
    o produkcji, „zrobiło, ale nikt się nie podpisał" — o wdrożeniu profili.
    Zlanie ich w jedno „brak danych" podpowiadałoby, że wystarczy zmienić
    zakres dat, a w drugim przypadku nie wystarczy.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(produkt, 'gluing', 4, datetime.combine(PONIEDZIALEK, time(9, 0)))

        bez_pracy = reports_service.wklad_pracownikow_na_stanowisku(
            'painting', PONIEDZIALEK, PONIEDZIALEK)
        bez_profili = reports_service.wklad_pracownikow_na_stanowisku(
            'gluing', PONIEDZIALEK, PONIEDZIALEK)

        assert bez_pracy['summary']['empty_reason'] == 'brak_pracy'
        assert bez_pracy['summary']['station_events'] == 0
        assert bez_pracy['unassigned']['present'] is False

        # (b) niesie LICZBY — front ma czym powiedzieć, ile pracy przeszło
        # bez podpisu, zamiast napisać „brak danych".
        assert bez_profili['summary']['empty_reason'] == 'brak_profili'
        assert bez_profili['workers'] == []
        assert bez_profili['summary']['station_m3'] == 2.0
        assert bez_profili['unassigned']['m3'] == 2.0
        assert bez_profili['summary']['attribution_coverage_pct'] == 0.0


def test_wklad_praca_cofnieta_do_zera_to_nadal_praca(app):
    """
    Dzień, w którym wszystko dorobiono i cofnięto, ma netto zero — ale pracą
    był. Pusty stan rozstrzyga LICZBA EVENTÓW, nie suma delt, inaczej taki
    dzień czytałby się jako „stanowisko stało".
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        kiedy = datetime.combine(PONIEDZIALEK, time(9, 0))
        _event(produkt, 'gluing', 4, kiedy)
        _event(produkt, 'gluing', -4, kiedy, source='admin')

        wynik = reports_service.wklad_pracownikow_na_stanowisku(
            'gluing', PONIEDZIALEK, PONIEDZIALEK)

        assert wynik['summary']['station_events'] == 2
        assert wynik['summary']['station_m3'] == 0.0
        assert wynik['summary']['empty_reason'] == 'brak_profili'


def test_wklad_nie_chowa_osoby_z_ujemnym_netto(app):
    """
    Cofnięcia (source='admin', korekty na tablecie) potrafią wyprowadzić
    pracownika na minus. Takiej osoby NIE ukrywamy i nie zerujemy jej słupka:
    ujemny wynik to informacja, a schowanie go rozjechałoby sumę z przerobem
    stanowiska. Sortowanie malejąco po m³ i tak zsuwa taki słupek na koniec.
    """
    with app.app_context():
        adam = _pracownik('Adam')
        borys = _pracownik('Borys')
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        kiedy = datetime.combine(PONIEDZIALEK, time(9, 0))
        _event(produkt, 'formatting', 6, kiedy, worker=adam)
        _event(produkt, 'formatting', -2, kiedy, source='admin', worker=borys)

        wynik = reports_service.wklad_pracownikow_na_stanowisku(
            'formatting', PONIEDZIALEK, PONIEDZIALEK)
        osoby = wynik['workers']

        assert [o['worker_name'] for o in osoby] == ['Adam Nowak', 'Borys Nowak']
        assert osoby[-1]['m3'] == -1.0
        assert osoby[-1]['negative'] is True
        assert osoby[0]['negative'] is False
        assert wynik['summary']['workers_negative'] == 1
        # Suma osób nadal równa przerobowi stanowiska — słupek pod zerem jest
        # częścią bilansu, a nie wyjątkiem od niego.
        assert wynik['summary']['attributed_m3'] == wynik['summary']['station_m3'] == 2.0
        # Pokrycie liczy TA SAMA funkcja, co wykres „Pokrycie atrybucją" —
        # patrz test_pokrycie_kafelka_jest_ta_sama_liczba_co_wykres.
        assert wynik['summary']['attribution_coverage_pct'] == 100.0


def test_wklad_brygady_dzieli_sie_udzialem(app):
    """
    Jeden event podpisany przez trzy osoby daje po 1/3 sztuki na osobę. Stąd
    nazwa kolumny „Wkład (szt.)", a nie „Sztuki" — nikt nie zrobił jednej
    trzeciej deski, każdy uczestniczył w całej.
    """
    with app.app_context():
        brygada = [_pracownik('Adam'), _pracownik('Borys'), _pracownik('Cezary')]
        produkt = _produkt(status='spakowane', volume=0.9, quantity=100)
        _brygada(produkt, 'assembly', 3,
                 datetime.combine(PONIEDZIALEK, time(9, 0)), brygada)

        wynik = reports_service.wklad_pracownikow_na_stanowisku(
            'assembly', PONIEDZIALEK, PONIEDZIALEK)

        assert [o['pieces'] for o in wynik['workers']] == [1.0, 1.0, 1.0]
        assert [o['m3'] for o in wynik['workers']] == [0.9, 0.9, 0.9]
        assert wynik['summary']['station_pieces'] == 3.0
        assert wynik['summary']['sums_match'] is True


def test_wklad_nie_miesza_stanowisk(app):
    """
    Robota z innego stanowiska nie ma prawa wejść do wykresu — cały sens tego
    widgetu polega na tym, że porównanie odbywa się WEWNĄTRZ jednego stanowiska.
    """
    with app.app_context():
        adam = _pracownik('Adam')
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        kiedy = datetime.combine(PONIEDZIALEK, time(9, 0))
        _event(produkt, 'gluing', 4, kiedy, worker=adam)
        _event(produkt, 'packaging', 20, kiedy, worker=adam)

        wynik = reports_service.wklad_pracownikow_na_stanowisku(
            'gluing', PONIEDZIALEK, PONIEDZIALEK)

        assert wynik['workers'][0]['pieces'] == 4.0
        assert wynik['summary']['station_pieces'] == 4.0


def test_wklad_odrzuca_zbiorcze_wszystkie_stanowiska(app):
    """
    Audyt odrzucił porównywanie ludzi MIĘDZY stanowiskami — m³ na sklejaniu
    i m³ na pakowaniu to inna robota. Wykres zbiorczy BYŁBY tamtym odrzuconym
    leaderboardem, więc 'all' leci błędem, a nie sumą.
    """
    with app.app_context():
        for zle in ('all', '', None):
            with pytest.raises(reports_service.ZakresError):
                reports_service.wklad_pracownikow_na_stanowisku(
                    zle, PONIEDZIALEK, PONIEDZIALEK)


def test_wklad_odrzuca_nieznane_stanowisko_po_stronie_serwisu(app):
    """
    Bramka stanowiska musi być PO OBU STRONACH, nie tylko w routerze.

    Zmierzone przed poprawką na kopii produkcji: `station='nie_ma_takiego'`
    przechodziło przez serwis i wracało kompletem zer z
    `empty_reason='brak_pracy'` — czyli odpowiedzią „stanowisko nic nie
    zrobiło" na pytanie o stanowisko, którego nie ma. Literówka w kodzie
    wyglądała jak spokojny dzień na hali.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(produkt, 'gluing', 4, datetime.combine(PONIEDZIALEK, time(9, 0)))

        for zle in ('nie_ma_takiego', 'GLUING ', 'sklejanie'):
            with pytest.raises(reports_service.ZakresError) as blad:
                reports_service.wklad_pracownikow_na_stanowisku(
                    zle, PONIEDZIALEK, PONIEDZIALEK)
            assert 'Nieznane stanowisko' in str(blad.value)

        # Kontrola, że test nie przechodzi „bo wszystko rzuca": poprawny kod
        # z tej samej listy ma nadal działać.
        assert reports_service.wklad_pracownikow_na_stanowisku(
            'gluing', PONIEDZIALEK, PONIEDZIALEK)['summary']['station_pieces'] == 4.0


def test_wklad_pokazuje_osobe_z_sesja_i_zerowym_wynikiem(app):
    """
    Właściciel prosił o „wykresy wszystkich osób, które danego dnia miały
    AKTYWNOŚĆ na danym stanowisku". Otwarta sesja JEST aktywnością — a lista
    budowana wyłącznie z wierszy atrybucji gubiła człowieka, który przestał
    zmianę przy maszynie i nie odbił ani jednej sztuki.

    To ten sam błąd, który naprawialiśmy już raz w tabeli wydajności
    (test_pracownik_z_sesja_bez_wyniku_jest_widoczny): wiersz „8 h / 0 m³"
    sam rzuca się w oczy i o to chodzi.
    """
    with app.app_context():
        pracujacy = _pracownik('Adam')
        bezczynny = _pracownik('Borys')
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(produkt, 'gluing', 6, datetime.combine(PONIEDZIALEK, time(9, 0)),
               worker=pracujacy)
        _sesja(bezczynny, 'gluing', PONIEDZIALEK)
        # Sesja na INNYM stanowisku nie ma prawa dołożyć nazwiska do tej osi —
        # wykres jest o jednym stanowisku i tylko o nim.
        _sesja(_pracownik('Cezary'), 'packaging', PONIEDZIALEK)

        wynik = reports_service.wklad_pracownikow_na_stanowisku(
            'gluing', PONIEDZIALEK, PONIEDZIALEK)
        nazwiska = [o['worker_name'] for o in wynik['workers']]

        assert nazwiska == ['Adam Nowak', 'Borys Nowak']
        bezczynny_wiersz = wynik['workers'][1]
        assert bezczynny_wiersz['m3'] == 0.0
        assert bezczynny_wiersz['pieces'] == 0.0
        assert bezczynny_wiersz['events'] == 0
        # Słupek o wysokości zero jest NIEWIDOCZNY — bez tej flagi nazwisko
        # wisi na osi bez niczego obok i wygląda jak usterka wykresu.
        assert bezczynny_wiersz['zero'] is True
        assert bezczynny_wiersz['negative'] is False
        assert wynik['summary']['workers_count'] == 2
        assert wynik['summary']['workers_zero'] == 1
        # Zera nie ruszają bilansu: suma słupków nadal równa przerobowi.
        assert wynik['summary']['sums_match'] is True
        assert wynik['summary']['attributed_m3'] == 3.0


def test_wklad_osoba_z_netto_zero_zostaje_z_flaga(app):
    """
    Netto zero (tyle samo cofnięte, co odhaczone) to nie to samo co ujemne
    netto i nie to samo co brak aktywności — a wygląda tak samo, bo słupek ma
    wysokość zero. Bez flagi taka osoba wypadała z bilansu ostrzeżeń: nie
    liczyła się jako ujemna, nie liczyła się jako nic, a jej nazwisko zostawało
    na osi.
    """
    with app.app_context():
        adam = _pracownik('Adam')
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        kiedy = datetime.combine(PONIEDZIALEK, time(9, 0))
        _event(produkt, 'formatting', 4, kiedy, worker=adam)
        _event(produkt, 'formatting', -4, kiedy, source='admin', worker=adam)

        wynik = reports_service.wklad_pracownikow_na_stanowisku(
            'formatting', PONIEDZIALEK, PONIEDZIALEK)
        osoba = wynik['workers'][0]

        assert osoba['m3'] == 0.0
        assert osoba['pieces'] == 0.0
        assert osoba['events'] == 2          # pracował, tylko wyszło na zero
        assert osoba['zero'] is True
        assert osoba['negative'] is False    # zero to nie minus
        assert wynik['summary']['workers_zero'] == 1
        assert wynik['summary']['workers_negative'] == 0


def test_wklad_flagi_liczone_po_zaokragleniu(app):
    """
    `negative` liczone z surowej sumy zmiennoprzecinkowej malowało na czerwono
    słupek, który użytkownik widzi jako 0.000: -1e-16 < 0 jest prawdą, a po
    zaokrągleniu do trzech miejsc zostaje zero. Front dostaje flagi zgodne
    z liczbami, które sam wyświetli — inaczej tooltip mówi „ta osoba więcej
    cofnęła, niż odhaczyła" przy zerowym słupku.

    Test dotyka wprost fabryki słupka, bo wywołanie tej sytuacji z bazy
    wymagałoby ustawienia objętości tak, żeby suma trafiła w epsilon — a to
    testowałoby arytmetykę SQLite, nie naszą regułę.
    """
    slupek = reports_service._slupek_osoby(1, 'Adam Nowak', -1e-16, -1e-16, 3)

    assert slupek['m3'] == 0.0
    assert slupek['pieces'] == 0.0
    assert slupek['negative'] is False
    assert slupek['zero'] is True

    # Kontrola przeciwna: realny minus nadal jest minusem.
    ujemny = reports_service._slupek_osoby(1, 'Adam Nowak', -2.0, -1.0, 3)
    assert ujemny['negative'] is True
    assert ujemny['zero'] is False


def test_wklad_szary_slupek_dostaje_te_same_flagi_co_osoby(app):
    """
    Praca bez podpisu też potrafi wyjść na minus — gdy w zakresie było więcej
    cofnięć niż dorobków, a żadne z nich nie miało profilu. Front zaszywał tam
    `negative: false`, więc słupek szedł pod zero w kolorze „normalnie",
    bez tooltipa i bez wzmianki w bilansie ostrzeżeń.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        wczoraj = PONIEDZIALEK - timedelta(days=1)
        # Dorobek w poprzedniej dobie, cofnięcie w oglądanej — inaczej oba
        # zdarzenia wpadłyby do jednej grupy (dzień, stanowisko) i wyzerowały się.
        _event(produkt, 'packaging', 6, datetime.combine(wczoraj, time(9, 0)))
        _event(produkt, 'packaging', -4, datetime.combine(PONIEDZIALEK, time(9, 0)),
               source='admin')

        wynik = reports_service.wklad_pracownikow_na_stanowisku(
            'packaging', PONIEDZIALEK, PONIEDZIALEK)

        assert wynik['unassigned']['pieces'] == -4.0
        assert wynik['unassigned']['m3'] == -2.0
        assert wynik['unassigned']['present'] is True
        assert wynik['unassigned']['negative'] is True
        assert wynik['unassigned']['zero'] is False


def test_wklad_zna_date_pierwszego_podpisu_na_stanowisku(app):
    """
    Przypis pod wykresem („pracy sprzed tej daty nie da się przypisać wstecz")
    liczy się Z DANYCH, nie z zaszytej stałej — każde stanowisko rusza
    z profilami w swoim tempie, a data wdrożenia nie jest jedna dla całej hali.
    """
    with app.app_context():
        adam = _pracownik('Adam')
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        wczoraj = PONIEDZIALEK - timedelta(days=1)
        _event(produkt, 'gluing', 4, datetime.combine(wczoraj, time(9, 0)))
        _event(produkt, 'gluing', 4, datetime.combine(PONIEDZIALEK, time(6, 25)),
               worker=adam)
        _event(produkt, 'packaging', 9, datetime.combine(PONIEDZIALEK, time(9, 0)))

        ze_sklejania = reports_service.wklad_pracownikow_na_stanowisku(
            'gluing', wczoraj, PONIEDZIALEK)
        z_pakowania = reports_service.wklad_pracownikow_na_stanowisku(
            'packaging', wczoraj, PONIEDZIALEK)

        assert ze_sklejania['summary']['first_attribution_at'] == \
            datetime.combine(PONIEDZIALEK, time(6, 25)).isoformat()
        # Stanowisko bez ani jednego podpisu — front pisze wtedy inne zdanie.
        assert z_pakowania['summary']['first_attribution_at'] is None


# ============================================================================
# JEDNA DEFINICJA POKRYCIA ATRYBUCJĄ
# ============================================================================
#
# Kafelek „ruchu (szt.) z podpisem" w wykresie 8 i wykres „Pokrycie atrybucją
# w czasie" odpowiadają na TO SAMO pytanie: ile pracy tego stanowiska ma
# podpis. Do 12.08.2026 odpowiadały na nie DWIEMA różnymi liczbami, bo kafelek
# miał własną implementację — udział m³ netto (ABS nakładany dopiero na sumę
# per osoba) zamiast ruchu w sztukach z ABS na poziomie eventu.
#
# Zmierzone na kopii produkcji 2026-08-12, przed usunięciem drugiej definicji:
#     zakres        stanowisko    kafelek   wykres
#     06-12.08      assembly       28.4%     25.4%
#     06-12.08      formatting      8.8%      6.6%
#     06-12.08      gluing          9.1%     10.7%
#     06-12.08      packaging       0.7%      0.8%
#     29.04-12.08   assembly        2.0%      1.6%
#     29.04-12.08   formatting      0.7%      0.5%
#     29.04-12.08   gluing          0.6%      0.7%
#
# Rozwiązanie: kafelek NIE liczy pokrycia, tylko bierze je z tej samej funkcji,
# z której liczy wykres. Test niżej łamie się przy każdej próbie przywrócenia
# drugiej implementacji.
# ============================================================================

def test_pokrycie_kafelka_jest_ta_sama_liczba_co_wykres(app):
    """
    Ten sam zakres, to samo stanowisko, dwa wejścia — jedna liczba.

    Dane celowo zawierają cofnięcia PO OBU stronach (podpisane i nie), bo to
    właśnie one rozjeżdżały obie definicje: przy liczeniu na sumie netto
    cofnięcie kasuje się z dorobkiem w mianowniku, przy ABS na poziomie eventu
    — nie. Bez nich test przechodziłby także dla starej, błędnej wersji.
    """
    with app.app_context():
        adam = _pracownik('Adam')
        borys = _pracownik('Borys')
        produkt = _produkt(status='spakowane', volume=0.5, quantity=1000)
        wtorek = PONIEDZIALEK + timedelta(days=1)

        for dzien in (PONIEDZIALEK, wtorek):
            _event(produkt, 'gluing', 9, datetime.combine(dzien, time(9, 0)),
                   worker=adam)
            _event(produkt, 'gluing', -7, datetime.combine(dzien, time(10, 0)),
                   source='admin', worker=borys)
            _event(produkt, 'gluing', 12, datetime.combine(dzien, time(11, 0)))
            _event(produkt, 'gluing', -11, datetime.combine(dzien, time(12, 0)),
                   source='admin')
            # Automat po obu stronach — nie ma prawa ruszyć ani licznika,
            # ani mianownika.
            _event(produkt, 'gluing', 400, datetime.combine(dzien, time(13, 0)),
                   source='auto_skip')

        for zakres in ((PONIEDZIALEK, PONIEDZIALEK), (PONIEDZIALEK, wtorek)):
            kafelek = reports_service.wklad_pracownikow_na_stanowisku(
                'gluing', *zakres)['summary']
            wykres = reports_service.pokrycie_atrybucji_dziennie(
                *zakres, station='gluing')['summary']

            assert kafelek['attribution_coverage_pct'] == wykres['coverage_pct']
            assert kafelek['coverage_pieces_abs'] == wykres['pieces_abs']
            assert kafelek['coverage_pieces_attributed'] == \
                wykres['pieces_attributed']

        # Kontrola, że to nie jest porównanie dwóch None ani dwóch stów:
        # ruch bez podpisu jest w tych danych większy niż podpisany, więc
        # pokrycie musi wypaść w środku przedziału.
        jeden_dzien = reports_service.wklad_pracownikow_na_stanowisku(
            'gluing', PONIEDZIALEK, PONIEDZIALEK)['summary']
        assert jeden_dzien['coverage_pieces_abs'] == 39      # 9+7+12+11
        assert jeden_dzien['coverage_pieces_attributed'] == 16   # 9+7
        assert jeden_dzien['attribution_coverage_pct'] == 41.0

        # I że STARA definicja dałaby tu co innego — inaczej test przepuściłby
        # jej powrót. Udział m³ netto: |1.0| / (|1.0| + |0.5|) = 66.7%.
        assert jeden_dzien['attributed_m3'] == 1.0
        assert jeden_dzien['unassigned_m3'] == 0.5
        stara_definicja = round(100 * abs(1.0) / (abs(1.0) + abs(0.5)), 1)
        assert stara_definicja == 66.7
        assert jeden_dzien['attribution_coverage_pct'] != stara_definicja


def test_pokrycie_kafelka_zgadza_sie_takze_z_tabela_wydajnosci(app):
    """
    Trzeci konsument tej samej liczby: kafelek „pokrycia atrybucją" w tabeli
    wydajności (podzakładka Ludzie). Wszystkie trzy widoki muszą podać tę samą
    wartość dla tego samego zakresu i stanowiska — użytkownik przechodzi
    między podzakładkami jednym kliknięciem.
    """
    from modules.production.services import worker_stats_service

    with app.app_context():
        adam = _pracownik('Adam')
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        kiedy = datetime.combine(PONIEDZIALEK, time(9, 0))
        _event(produkt, 'assembly', 5, kiedy, worker=adam)
        _event(produkt, 'assembly', -3, kiedy, source='admin')
        _event(produkt, 'assembly', 12, kiedy)

        kafelek = reports_service.wklad_pracownikow_na_stanowisku(
            'assembly', PONIEDZIALEK, PONIEDZIALEK)['summary']
        tabela = worker_stats_service.raport_wydajnosci(
            PONIEDZIALEK, PONIEDZIALEK, station='assembly')['summary']

        assert kafelek['attribution_coverage_pct'] == \
            tabela['attribution_coverage_pct'] == 25.0   # 5 z 20 jednostek ruchu


def test_wklad_w_sztukach_jest_ten_sam_w_obu_podzakladkach(app):
    """
    Brygada dzieli event przez share = 1/N, więc wkład bywa ułamkowy — i przy
    różnym zaokrągleniu ta sama osoba miała 0.33 na wykresie stanowiskowym
    i 0.3 w tabeli wydajności. Dwie liczby na to samo pytanie, dwa kliknięcia
    od siebie.
    """
    from modules.production.services import worker_stats_service

    with app.app_context():
        brygada = [_pracownik('Adam'), _pracownik('Borys'), _pracownik('Cezary')]
        produkt = _produkt(status='spakowane', volume=0.9, quantity=100)
        _brygada(produkt, 'assembly', 1,
                 datetime.combine(PONIEDZIALEK, time(9, 0)), brygada)

        wykres = reports_service.wklad_pracownikow_na_stanowisku(
            'assembly', PONIEDZIALEK, PONIEDZIALEK)
        tabela = worker_stats_service.wydajnosc_pracownikow(
            PONIEDZIALEK, PONIEDZIALEK, station='assembly')

        z_wykresu = {o['worker_name']: o['pieces'] for o in wykres['workers']}
        z_tabeli = {w['worker_name']: w['pieces'] for w in tabela}

        assert z_wykresu == z_tabeli
        assert set(z_wykresu.values()) == {0.33}


# ============================================================================
# JEDNA DEFINICJA „ZROBIONE" — MACIERZ WSZYSTKICH NOWYCH AGREGATÓW
# ============================================================================
#
# Testy wyżej sprawdzają filtr źródła punktowo, wykres po wykresie. Ta sekcja
# robi to SYSTEMOWO: jeden dosyp eventów automatu przechodzi przez KAŻDY
# agregat liczący pracę człowieka i żaden nie ma prawa drgnąć ani o cyfrę.
# Powód jest historyczny — błąd P4 nie polegał na tym, że jeden widget liczył
# źle, tylko na tym, że każdy liczył inaczej i nikt nie umiał wytłumaczyć,
# skąd różnica.
#
# Skala zjawiska na kopii produkcyjnej (2026-08-12, okno 05-11.08, surowy SQL):
#     z filtrem     Wykańczanie   53 szt. / 1.133 m³
#     bez filtra    Wykańczanie  400 szt. / 6.037 m³      ← 7.5× zawyżenia
# 1503 eventy 'system' i 170 'auto_skip' siedzą w CAŁOŚCI na wykańczaniu
# i formatowaniu, więc bez filtra dwa stanowiska kłamią, a pięć nie — i to
# jest najgorszy możliwy układ, bo wykres nadal wygląda wiarygodnie.

DZIEN_PRACY = PONIEDZIALEK                          # tu pracuje człowiek
DZIEN_AUTOMATU = PONIEDZIALEK + timedelta(days=1)   # tu wyłącznie automat


def _hala_z_praca_czlowieka():
    """Dwa stanowiska, po jednym prawdziwym evencie — punkt odniesienia."""
    produkt = _produkt(status='spakowane', volume=0.5, quantity=1000)
    for kod in ('packaging', 'formatting'):
        _event(produkt, kod, 4, datetime.combine(DZIEN_PRACY, time(9, 0)))
    return produkt


def _dosyp_eventow_automatu(produkt):
    """
    Automat na trzech stanowiskach i w dwóch dobach naraz — bo każdy agregat
    da się oszukać inaczej:
      - packaging/formatting: dołożenie do stanowisk, które PRACUJĄ (zawyża
        tempo, przerób, mianownik doróbek),
      - gluing: stanowisko widmo, którego nikt nie tknął (dokłada słupek,
        wiersz w tabeli obsady i stanowisko do mianownika badge'a),
      - DZIEN_AUTOMATU: doba widmo (dokłada dzień roboczy do okna wykresu 1
        i dzień produkcyjny do okna badge'a).
    """
    for dzien in (DZIEN_PRACY, DZIEN_AUTOMATU):
        for kod in ('packaging', 'formatting', 'gluing'):
            _event(produkt, kod, 400, datetime.combine(dzien, time(9, 30)),
                   source='auto_skip')
            _event(produkt, kod, 400, datetime.combine(dzien, time(14, 0)),
                   source='system')


def _miara_wykres_1_zapas():
    return sorted(
        (s['station_code'], s['window_m3'], s['avg_daily_m3'],
         s['days_of_supply'], s['reason'])
        for s in reports_service.dni_zapasu_stanowisk(
            end_date=DZIEN_AUTOMATU)['stations'])


def _miara_wykres_1_dni_robocze():
    return reports_service.dni_robocze_hali(end_date=DZIEN_AUTOMATU)


def _miara_wykres_3_wyjscie():
    wynik = reports_service.wejscie_vs_wyjscie(DZIEN_PRACY, DZIEN_AUTOMATU)
    return wynik['total_out_m3'], [d['out_m3'] for d in wynik['days']]


def _miara_wykres_4_heatmapa():
    wynik = reports_service.heatmapa_godzinowa(DZIEN_PRACY, DZIEN_AUTOMATU)
    return wynik['events_total'], wynik['max_abs_m3'], wynik['grid_m3']


def _miara_wykres_5_obsada():
    wynik = reports_service.obsada_vs_przerob(DZIEN_PRACY, DZIEN_AUTOMATU)
    return ([(w['station_code'], w['pieces'], w['m3']) for w in wynik['rows']],
            wynik['summary']['pieces'], wynik['summary']['m3'],
            wynik['summary']['stations_with_work'])


def _miara_wykres_6_pokrycie():
    wynik = reports_service.pokrycie_atrybucji_dziennie(DZIEN_PRACY, DZIEN_AUTOMATU)
    return (wynik['summary']['pieces_abs'], wynik['summary']['coverage_pct'],
            [p['events'] for p in wynik['points']])


def _miara_wykres_7_mianownik():
    return reports_service.rejestracja_dorobek(
        DZIEN_PRACY, DZIEN_AUTOMATU)['formatted_pieces']


def _miara_wykres_8_wklad():
    # Dwa stanowiska naraz: 'packaging' PRACUJE (automat dokłada mu sztuk),
    # 'gluing' jest widmem automatu (bez filtra urodziłby się z niczego).
    return [
        reports_service.wklad_pracownikow_na_stanowisku(
            kod, DZIEN_PRACY, DZIEN_AUTOMATU)
        for kod in ('packaging', 'gluing')
    ]


def _miara_badge():
    wynik = reports_service.stan_nauki(end_date=DZIEN_AUTOMATU, prog_dni=14)
    return (wynik['production_days_in_window'], wynik['stations_working'],
            wynik['days_with_data'], wynik['text'])


_MIARY_PRACY_CZLOWIEKA = {
    'wykres 1 — dni zapasu':        _miara_wykres_1_zapas,
    'wykres 1 — dni robocze hali':  _miara_wykres_1_dni_robocze,
    'wykres 3 — wyjście hali':      _miara_wykres_3_wyjscie,
    'wykres 4 — heatmapa':          _miara_wykres_4_heatmapa,
    'wykres 5 — obsada vs przerób': _miara_wykres_5_obsada,
    'wykres 6 — pokrycie atrybucją': _miara_wykres_6_pokrycie,
    'wykres 7 — mianownik doróbek': _miara_wykres_7_mianownik,
    'wykres 8 — wkład osób':        _miara_wykres_8_wklad,
    'badge „Trwa nauka"':           _miara_badge,
}


@pytest.mark.parametrize('nazwa', sorted(_MIARY_PRACY_CZLOWIEKA))
def test_automat_nie_wchodzi_do_zadnego_agregatu_pracy(app, nazwa):
    """
    Ten sam dosyp 4800 sztuk z auto_skip/system nie ma prawa ruszyć ANI JEDNEJ
    liczby w ANI JEDNYM agregacie pracy człowieka — ani wartości, ani składu
    stanowisk, ani składu dni. Test porównuje CAŁY kształt wyniku przed i po,
    nie pojedynczą sumę: filtr, który przepuszcza automat do listy stanowisk,
    ale nie do sumy m³, jest tak samo zły — dokłada widgetowi słupek, którego
    nikt nie zrobił.
    """
    with app.app_context():
        produkt = _hala_z_praca_czlowieka()
        miara = _MIARY_PRACY_CZLOWIEKA[nazwa]
        przed = miara()

        _dosyp_eventow_automatu(produkt)

        assert miara() == przed, nazwa


def test_automat_widziany_bez_filtra_faktycznie_zmienilby_liczby(app):
    """
    Kontrola samego testu wyżej: gdyby dosyp automatu był niewidoczny dla bazy
    (zły dzień, złe stanowisko, zły produkt), macierz przechodziłaby na zielono
    NICZEGO nie sprawdzając. Ten test liczy to samo BEZ filtra źródła i wymaga,
    żeby różnica była ogromna.
    """
    with app.app_context():
        produkt = _hala_z_praca_czlowieka()
        _dosyp_eventow_automatu(produkt)

        from sqlalchemy import func
        bez_filtra = db.session.query(
            func.sum(ProductionStationEvent.delta)
        ).filter(
            ProductionStationEvent.created_at >= datetime.combine(DZIEN_PRACY, time(0, 0)),
            ProductionStationEvent.created_at <= datetime.combine(DZIEN_AUTOMATU, time(23, 59)),
        ).scalar()

        # 8 sztuk pracy człowieka wobec 4808 razem — 601× zawyżenia.
        assert bez_filtra == 4808
        assert reports_service.obsada_vs_przerob(
            DZIEN_PRACY, DZIEN_AUTOMATU)['summary']['pieces'] == 8


def test_wykres_2_nie_ma_do_czego_przyczepic_filtra(app):
    """
    Jedyny nowy agregat BEZ filtra źródła i to jest świadome, nie przeoczenie:
    „Termin vs postęp" nie czyta prod_station_events ani razu — liczy stan
    pozycji z current_status i deadline_date. Test zamyka tę furtkę na przyszłość:
    jeśli ktoś kiedyś dołoży tu odczyt eventów, dosyp automatu ruszy liczby
    i ten test zapali się jako pierwszy.

    Udokumentowane w reports_service.py, nagłówek modułu, zasada 1.
    """
    with app.app_context():
        from modules.production.models import get_local_now
        produkt = _produkt(status='czeka_na_formatowanie', volume=0.5, quantity=4,
                           deadline=get_local_now().date())
        przed = reports_service.termin_vs_postep()['totals']

        _dosyp_eventow_automatu(produkt)

        assert reports_service.termin_vs_postep()['totals'] == przed
        assert przed['m3_total'] == 2.0


# ============================================================================
# GDZIE BADGE MA PRAWO SIĘ POJAWIĆ (kontrakt endpointów)
# ============================================================================

def _payload_endpointu(app, funkcja, zapytanie):
    """
    Ciało endpointu bez dekoratora @login_required. `current_user` jest w tych
    endpointach dotykany wyłącznie w gałęzi błędu (logowanie), więc ścieżka
    sukcesu nie wymaga ani sesji, ani blueprintu — a test sprawdza dokładnie
    to, co pojedzie do przeglądarki.
    """
    from modules.production.routers.api import reports_api

    with app.test_request_context(zapytanie):
        odpowiedz = getattr(reports_api, funkcja).__wrapped__()
        return odpowiedz.get_json()


def test_badge_jedzie_z_obsada_ale_nie_z_pokryciem_ani_dorobkami(app):
    """
    Kontrakt uzgodniony z właścicielem, zapisany w docstringach endpointów:
      - wykres 5 (obsada) badge NIESIE — jego liczby zależą od tego, czy ludzie
        się logują;
      - wykres 6 (pokrycie) badge'a NIE ma, bo to ON JEST miernikiem nauki
        i oznaczanie go byłoby błędnym kołem;
      - wykres 7 (doróbki) badge'a NIE ma, bo tam ograniczeniem jest zakres
        endpointu mobilnego, nie doświadczenie hali — czekanie nic nie zmieni.
    """
    with app.app_context():
        adam = _pracownik()
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(produkt, 'gluing', 4, datetime.combine(PONIEDZIALEK, time(9, 0)),
               worker=adam)
        _sesja(adam, 'gluing', PONIEDZIALEK)

        zakres = f'/?start_date={PONIEDZIALEK}&end_date={PONIEDZIALEK}'
        obsada = _payload_endpointu(app, 'reports_staffing_vs_output', zakres)
        pokrycie = _payload_endpointu(app, 'reports_attribution_coverage', zakres)
        dorobki = _payload_endpointu(app, 'reports_rework_registration', zakres)

        assert obsada['success'] is True
        assert obsada['learning']['label'] == 'Trwa nauka'
        assert 'learning' not in pokrycie
        assert 'learning' not in dorobki


def test_wklad_osob_niesie_badge_i_odrzuca_wszystkie_stanowiska(app):
    """
    Kontrakt endpointu wykresu 8:
      - badge NIESIE, bo widget stoi w całości na atrybucji — bez profili nie
        ma czego rysować;
      - 'all', brak stanowiska ORAZ nieznany kod to 400, a nie suma wszystkich
        stanowisk i nie ciche zero. Ta bramka pilnuje, żeby widget nie stał się
        odrzuconym przez audyt rankingiem ludzi między stanowiskami; bliźniacza
        stoi w serwisie (test_wklad_odrzuca_nieznane_stanowisko_po_stronie_serwisu)
        i to jest celowa redundancja, a nie duplikat — router chroni
        przeglądarkę, serwis chroni każdego innego konsumenta.
    """
    with app.app_context():
        adam = _pracownik()
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(produkt, 'gluing', 4, datetime.combine(PONIEDZIALEK, time(9, 0)),
               worker=adam)
        _sesja(adam, 'gluing', PONIEDZIALEK)

        zakres = f'start_date={PONIEDZIALEK}&end_date={PONIEDZIALEK}'
        ok = _payload_endpointu(
            app, 'reports_station_worker_output', f'/?station=gluing&{zakres}')
        assert ok['success'] is True
        assert ok['learning']['label'] == 'Trwa nauka'
        assert ok['workers'][0]['worker_name'] == 'Adam Nowak'

        from modules.production.routers.api import reports_api

        for zapytanie in (f'/?station=all&{zakres}', f'/?{zakres}'):
            with app.test_request_context(zapytanie):
                odpowiedz, kod = reports_api.reports_station_worker_output.__wrapped__()
            assert kod == 400
            assert 'JEDNO stanowisko' in odpowiedz.get_json()['error']

        # Nieznany kod nie ma prawa dojechać do agregatu i wrócić jako
        # „stanowisko nic nie zrobiło" — literówka ma być widoczna.
        with app.test_request_context(f'/?station=nie_ma_takiego&{zakres}'):
            odpowiedz, kod = reports_api.reports_station_worker_output.__wrapped__()
        assert kod == 400
        assert 'Nieprawidłowe stanowisko' in odpowiedz.get_json()['error']


# ============================================================================
# TEMPO m³/OSOBOGODZINĘ — LICZNIK I MIANOWNIK Z TEGO SAMEGO OKNA
# ============================================================================

def test_tempo_nie_rosnie_razem_z_zakresem(app):
    """
    REGRESJA: wskaźnik, który rośnie razem z oknem zamiast się stabilizować.

    Licznik (m³) brany był z CAŁEGO zakresu, a mianownik (osobogodziny) tylko
    z dób, w których ktoś otworzył sesję. Zmierzone 2026-08-12 na kopii
    produkcji: sklejanie 0.056 (Dziś) → 0.614 (7 dni) → 2.898 m³/h (30 dni),
    czyli 52× dla tego samego stanowiska, przy osobogodzinach stojących
    w miejscu (wszystkie sesje były z jednego dnia).

    Tutaj: sesja i praca w poniedziałek, sama praca w pozostałe dni tygodnia.
    Tempo poniedziałku ma być IDENTYCZNE niezależnie od tego, jak szeroki
    zakres wybierze użytkownik.
    """
    with app.app_context():
        adam = _pracownik()
        produkt = _produkt(status='spakowane', volume=0.5, quantity=1000)
        _sesja(adam, 'gluing', PONIEDZIALEK, godzin=8)
        _event(produkt, 'gluing', 8, datetime.combine(PONIEDZIALEK, time(10, 0)))
        # Trzy kolejne doby BEZ sesji — same eventy.
        for przesuniecie in (1, 2, 3):
            dzien = PONIEDZIALEK + timedelta(days=przesuniecie)
            _event(produkt, 'gluing', 20, datetime.combine(dzien, time(10, 0)))

        tempa = {}
        for etykieta, dni in (('1 dzień', 0), ('4 dni', 3)):
            wiersz = next(
                w for w in reports_service.obsada_vs_przerob(
                    PONIEDZIALEK, PONIEDZIALEK + timedelta(days=dni))['rows']
                if w['station_code'] == 'gluing')
            tempa[etykieta] = wiersz

        # 8 sztuk × 0.5 m³ = 4 m³ w dobie z sesją, 8 h pracy → 0.5 m³/h.
        assert tempa['1 dzień']['m3_per_person_hour'] == 0.5
        assert tempa['4 dni']['m3_per_person_hour'] == 0.5

        # Słupek m³ NADAL pokazuje cały zakres — to on ma się zgadzać
        # z resztą zakładki.
        assert tempa['1 dzień']['m3'] == 4.0
        assert tempa['4 dni']['m3'] == 34.0

        # Front musi mieć czym podpisać, z ilu dni pochodzi tempo.
        assert tempa['4 dni']['days_with_sessions'] == 1
        assert tempa['4 dni']['days_in_range'] == 4
        assert tempa['4 dni']['m3_in_session_days'] == 4.0


def test_obsada_liczy_stanowiska_z_praca_po_zdarzeniach_nie_po_netto(app):
    """
    REGRESJA: doba, w której tyle samo odhaczono, co cofnięto, ma netto ZERO
    przy realnej pracy. Kafelek „stanowisk z sesją / z pracą" liczył po netto
    i pokazywał „0 / 0" bez podświetlenia, czyli „wszystko się zgadza" —
    podczas gdy widget pokrycia atrybucją dla tej samej doby raportował
    4 sztuki ruchu. Dwa widgety obok siebie, dwie sprzeczne odpowiedzi.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(produkt, 'formatting', 4, datetime.combine(PONIEDZIALEK, time(9, 0)))
        _event(produkt, 'formatting', -4, datetime.combine(PONIEDZIALEK, time(15, 0)))

        wynik = reports_service.obsada_vs_przerob(PONIEDZIALEK, PONIEDZIALEK)
        wiersz = next(w for w in wynik['rows'] if w['station_code'] == 'formatting')

        assert wiersz['pieces'] == 0            # netto naprawdę zerowe
        assert wiersz['station_events'] == 2    # ale zdarzenia były
        assert wynik['summary']['stations_with_work'] == 1
        assert wynik['summary']['station_events'] == 2


# ============================================================================
# OKNO SKANU — AGREGATY „OSTATNIE N DNI PRODUKCYJNYCH"
# ============================================================================

def test_dolna_granica_skanu_nie_zmienia_wyniku_przy_starej_historii(app):
    """
    REGRESJA WYDAJNOŚCIOWA Z ASERCJĄ NA POPRAWNOŚĆ: dni_robocze_hali()
    i stan_nauki() dostały dolną granicę daty (skanowały całą historię eventów,
    czyli rosły z wiekiem instalacji, a nie z wybranym zakresem).

    Zawężenie okna nie ma prawa zmienić WYNIKU — tylko koszt. Ten test wpycha
    do bazy event sprzed dwóch lat i sprawdza, że oba agregaty dalej widzą
    świeże doby, a fallback (zapytanie bez granicy) dowozi komplet, gdy hala
    stała dłużej niż okno skanu.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=1000)

        # Trzy świeże doby robocze…
        for przesuniecie in (0, 1, 2):
            dzien = PONIEDZIALEK - timedelta(days=przesuniecie)
            _event(produkt, 'gluing', 10, datetime.combine(dzien, time(9, 0)))
        # …i jedna sprzed dwóch lat, daleko poza oknem skanu.
        prehistoria = PONIEDZIALEK - timedelta(days=730)
        _event(produkt, 'gluing', 10, datetime.combine(prehistoria, time(9, 0)))

        dni = reports_service.dni_robocze_hali(PONIEDZIALEK)
        assert PONIEDZIALEK in dni
        assert len(dni) == 4, 'fallback ma dowieźć także dobę sprzed dwóch lat'
        assert prehistoria in dni

        # stan_nauki liczy z tych samych dób produkcyjnych.
        nauka = reports_service.stan_nauki(end_date=PONIEDZIALEK, prog_dni=14)
        assert nauka['production_days_in_window'] == 4
        assert nauka['window_start'] == prehistoria.isoformat()


def test_okno_skanu_nie_gubi_dni_gdy_hala_pracuje_codziennie(app):
    """
    Wariant bez fallbacku: przy ciągłej pracy okno skanu z zapasem musi
    dowieźć pełny limit dni z PIERWSZEGO zapytania. Gdyby mnożnik był za mały,
    agregat po cichu oddawałby krótsze okno i tempo w „Dniach zapasu"
    skakałoby — a to jest liczba, na którą właściciel patrzy przy planowaniu.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=5000)
        for przesuniecie in range(20):
            dzien = PONIEDZIALEK - timedelta(days=przesuniecie)
            _event(produkt, 'gluing', 10, datetime.combine(dzien, time(9, 0)))

        dni = reports_service.dni_robocze_hali(PONIEDZIALEK,
                                               ile_dni=reports_service.OKNO_DNI_ROBOCZYCH)

        assert len(dni) == reports_service.OKNO_DNI_ROBOCZYCH
        assert dni[-1] == PONIEDZIALEK


# ============================================================================
# „WYKONANIE STANOWISKA W DNIU" — STAN, TRYB ZBIORCZY, STRONICOWANIE
# ============================================================================

def _stan_stanowiska(app, zapytanie):
    from modules.production.routers.api import reports_api

    with app.test_request_context(zapytanie):
        odpowiedz = reports_api.reports_station_output.__wrapped__()
    if isinstance(odpowiedz, tuple):
        return odpowiedz[0].get_json(), odpowiedz[1]
    return odpowiedz.get_json(), 200


def test_stan_pozycji_rozstrzyga_id_a_nie_znacznik_czasu(app, zalogowany):
    """
    REGRESJA: tablet zapisuje wsad kilkoma zdarzeniami w TEJ SAMEJ sekundzie —
    w bazie produkcyjnej jest 3053 takich grup, z czego 3050 ma różne
    quantity_done_after. Join po `created_at` oddawał wtedy wszystkie kolizje,
    a dedup w pętli brał PIERWSZY Z BRZEGU, czyli losowy.

    Zmierzone 2026-08-12 przed poprawką: pozycja 887_1 pokazywała „1 / 3" przy
    zdarzeniach kończących się na quantity_done_after = 3, a kafelek stanu
    całego dnia zaniżał o 12,4% sztuk i 11,8% m³.

    quantity_done_after to migawka zapisana w chwili INSERT-u, więc o „stanie
    po ostatnim zdarzeniu" rozstrzyga kolejność ZAPISU (id), nie znacznik
    czasu — ten admin może wpisać wstecz.
    """
    with app.app_context():
        produkt = _produkt(status='czeka_na_formatowanie', volume=0.25, quantity=3)
        chwila = datetime.combine(PONIEDZIALEK, time(8, 56, 59))
        for i in (1, 2, 3):
            ev = ProductionStationEvent(
                production_item_id=produkt.id, station_code='formatting',
                delta=1, quantity_done_after=i, created_at=chwila, source='mobile')
            db.session.add(ev)
            db.session.flush()
        db.session.commit()

        dane, kod = _stan_stanowiska(
            app, f'/?station=formatting&date={PONIEDZIALEK}')

        assert kod == 200
        assert len(dane['items']) == 1, 'remis nie ma prawa zdublować wiersza'
        assert dane['items'][0]['quantity_done_eod'] == 3
        assert dane['summary']['total_quantity_done_eod'] == 3
        assert dane['summary']['total_volume_done_eod_m3'] == 0.75


def test_tryb_zbiorczy_nie_sumuje_stanu_z_roznych_stanowisk(app, zalogowany):
    """
    REGRESJA: w trybie „Wszystkie stanowiska" ta sama pozycja daje wiersz na
    KAŻDE stanowisko, przez które przeszła, a kafelki sumowały te wiersze.
    Zmierzone na 30 dniach: 84.180 m³ „wykonane" przy 28.260 m³ PEŁNEJ
    objętości tych produktów — kafelek przekraczał fizyczne maksimum
    trzykrotnie, a jego tooltip obiecywał „ile z tych pozycji jest już
    wykonane".

    Stan (EOD) jest dziś liczony WYŁĄCZNIE dla jednego stanowiska; w trybie
    zbiorczym zostaje null i front chowa oba kafelki. Ruch (suma delt) jest
    addytywny i zostaje w obu trybach.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=4)
        for kod in ('gluing', 'formatting', 'packaging'):
            _event(produkt, kod, 4, datetime.combine(PONIEDZIALEK, time(9, 0)))

        zbiorczo, _ = _stan_stanowiska(app, f'/?station=all&date={PONIEDZIALEK}')
        assert zbiorczo['summary']['items_count'] == 3       # wiersze
        assert zbiorczo['summary']['distinct_items_count'] == 1   # produkty
        assert zbiorczo['summary']['total_day_delta'] == 12       # ruch: addytywny
        assert zbiorczo['summary']['total_quantity_done_eod'] is None
        assert zbiorczo['summary']['total_volume_done_eod_m3'] is None

        # Pojedyncze stanowisko dalej podaje stan — i mieści się w objętości
        # pozycji (4 szt. × 0.5 m³ = 2.0 m³), zamiast ją trzykrotnie przebijać.
        jedno, _ = _stan_stanowiska(app, f'/?station=gluing&date={PONIEDZIALEK}')
        assert jedno['summary']['total_quantity_done_eod'] == 4
        assert jedno['summary']['total_volume_done_eod_m3'] == 2.0


def test_lista_pozycji_jest_stronicowana_po_stronie_serwera(app, zalogowany):
    """
    REGRESJA WYDAJNOŚCIOWA: endpoint oddawał CAŁĄ listę pozycji, a front
    stronicował ją w przeglądarce po dziesięć wierszy. Jedno kliknięcie
    w preset „30 dni" ściągało 1.3 MB JSON-a (90 dni — 3.4 MB) po to, żeby
    pokazać dziesięć wierszy.

    Kafelki liczą się z osobnych agregatów, więc MUSZĄ być niezależne od
    strony — inaczej przewracanie stron zmieniałoby liczby u góry widgetu.
    """
    with app.app_context():
        for _ in range(25):
            produkt = _produkt(status='spakowane', volume=0.5, quantity=2)
            _event(produkt, 'gluing', 2, datetime.combine(PONIEDZIALEK, time(9, 0)))

        pierwsza, _ = _stan_stanowiska(
            app, f'/?station=gluing&date={PONIEDZIALEK}&limit=10&offset=0')
        trzecia, _ = _stan_stanowiska(
            app, f'/?station=gluing&date={PONIEDZIALEK}&limit=10&offset=20')

        assert len(pierwsza['items']) == 10
        assert len(trzecia['items']) == 5
        assert pierwsza['pagination']['total'] == 25
        assert trzecia['pagination']['total'] == 25

        # Kafelki identyczne na każdej stronie.
        assert pierwsza['summary'] == trzecia['summary']
        assert pierwsza['summary']['items_count'] == 25
        assert pierwsza['summary']['total_quantity_done_eod'] == 50


# ============================================================================
# WEJŚCIE: NIEPEŁNY ZAKRES, ZŁY PARAMETR, CZAS LOKALNY
# ============================================================================

def test_niepelny_zakres_dat_to_blad_a_nie_cichy_domysl(app, zalogowany):
    """
    REGRESJA: warunek `if start and end` wyrzucał do kosza całe podane wejście.
    ?start_date=2026-05-01 oddawało HTTP 200 z danymi ostatnich siedmiu dni,
    a eksport XLSX wychodził z DOMYŚLNYM zakresem w nazwie pliku — zapisany
    link odpowiadał na inne pytanie, niż zadano, i nic tego nie sygnalizowało.
    """
    from modules.production.routers.api import reports_api

    with app.app_context():
        for zapytanie in ('/?start_date=2026-05-01', '/?end_date=2026-05-01'):
            with app.test_request_context(zapytanie):
                odpowiedz, kod = reports_api.reports_worker_output.__wrapped__()
            assert kod == 400, zapytanie
            assert 'obie daty' in odpowiedz.get_json()['error']

        # station-output ma własne parsowanie (fallback na ?date=) — i tę samą
        # regułę.
        _, kod = _stan_stanowiska(app, '/?station=all&start_date=2026-05-01')
        assert kod == 400


def test_pasek_kpi_liczy_dobe_z_czasu_lokalnego(app, zegar, zalogowany, monkeypatch):
    """
    REGRESJA: pasek KPI liczył okno z date.today(), czyli z UTC, a wszystkie
    widgety pod nim z get_local_now(). Kontener chodzi na UTC (tzname
    ('UTC','UTC'), datetime.now() 09:07 przy get_local_now() 11:07), więc
    między północą a 02:00 czasu polskiego kafelek pokazywał okno przesunięte
    o dobę: zmierzone na prod_products 163 poz / 5.849 m³ wobec
    195 poz / 7.657 m³, czyli +19,6% i +30,9%.

    Test zamraża czas lokalny na 00:30 i sprawdza, że pozycja spakowana DZIŚ
    o 00:10 wchodzi do kafelka.
    """
    from modules.production.routers.api import reports_api

    with app.app_context():
        chwila = zegar(datetime.combine(PONIEDZIALEK, time(0, 30)))

        produkt = _produkt(status='spakowane', volume=2.0, quantity=1)
        produkt.packaging_completed_at = chwila.replace(minute=10)
        db.session.commit()

        # Endpoint renderuje szablon — podmieniamy go na sam kontekst, bo test
        # sprawdza LICZBY, a nie markup.
        zebrane = {}

        def fake_render(_szablon, **kontekst):
            zebrane.update(kontekst)
            return '<div></div>'

        monkeypatch.setattr(reports_api, 'render_template', fake_render)

        with app.test_request_context('/'):
            reports_api.reports_tab_content.__wrapped__()

        assert zebrane['reports_summary']['week_completed'] == 1
        assert zebrane['reports_summary']['week_volume'] == 2.0


def test_awaria_podzakladki_nie_wstrzykuje_tresci_wyjatku(app, zalogowany, monkeypatch):
    """
    REGRESJA BEZPIECZEŃSTWA: handler składał f-string
    `Błąd ładowania: {e}` i oddawał go jako HTML, a front wstawia ciało
    odpowiedzi przez `panel.innerHTML = await odp.text()` BEZWARUNKOWO
    (komentarz w kodzie: „treść wstawiamy zawsze"). innerHTML nie wykonuje
    <script>, ale onerror na <img> odpala się normalnie — odtworzone realnym
    żądaniem. To było jedyne miejsce w przepływie Raportów łamiące zasadę
    „escapuj wszystko, co przyszło z bazy".
    """
    from modules.production.routers.api import reports_api

    ladunek = '<img src=x onerror=alert(1)>'

    def wybuch():
        raise RuntimeError(ladunek)

    monkeypatch.setitem(reports_api._PODZAKLADKI, 'miks',
                        (wybuch, 'components/reports/mix.html'))

    with app.app_context():
        with app.test_request_context('/'):
            cialo, kod = reports_api.reports_subtab.__wrapped__('miks')

        assert kod == 500
        assert '<img' not in cialo
        assert ladunek not in cialo
        assert 'logach serwera' in cialo


def test_awaria_wykresu_nie_oddaje_zapytania_sql(app, zalogowany, monkeypatch):
    """
    Ta sama zasada po stronie JSON: przy błędzie SQLAlchemy str(e) niesie pełne
    zapytanie razem z bindami (nazwy klientów i produktów z BaseLinkera),
    a endpointy mają wyłącznie @login_required, bez sprawdzania roli.
    """
    from modules.production.routers.api import reports_api

    tajne = "SELECT nazwa_klienta FROM prod_orders WHERE x='Kowalski'"

    def wybuch(*_a, **_k):
        raise RuntimeError(tajne)

    monkeypatch.setattr(reports_service, 'heatmapa_godzinowa', wybuch)

    with app.app_context():
        with app.test_request_context(
                f'/?start_date={PONIEDZIALEK}&end_date={PONIEDZIALEK}'):
            odpowiedz, kod = reports_api.reports_hourly_heatmap.__wrapped__()

        assert kod == 500
        tresc = odpowiedz.get_json()['error']
        assert 'SELECT' not in tresc
        assert 'Kowalski' not in tresc


# ============================================================================
# PODZAKŁADKA MIKS — NAZWY Z KATALOGU
# ============================================================================

def test_miks_bierze_nazwy_stanowisk_z_katalogu(app):
    """
    REGRESJA (zasada „nazwy stanowisk wyłącznie ze station_catalog"): szablon
    składał etykietę przez `status.replace('czeka_na_','').replace('_',' ')
    .title()` i produkował TRZECI w aplikacji zestaw nazw tych samych
    stanowisk — „Lakiernie" zamiast „Lakiernia", „Skladanie" zamiast
    „Składanie - lite", „Wykanczanie" zamiast „Wykańczanie". Pięć z dziesięciu
    wierszy pod inną nazwą niż reszta aplikacji i bez polskich znaków.
    """
    from modules.production.routers.api import reports_api
    from modules.production.services.station_catalog import (
        STATION_PENDING_STATUS, station_label,
    )

    with app.app_context():
        for kod, status in STATION_PENDING_STATUS.items():
            _produkt(status=status, volume=0.5, quantity=1)
        _produkt(status='spakowane', volume=0.5, quantity=1)
        _produkt(status='czeka_na_logistyke', volume=0.5, quantity=1)

        etykiety = {p['status']: p['label']
                    for p in reports_api._kontekst_miks()['status_breakdown']}

        for kod, status in STATION_PENDING_STATUS.items():
            assert etykiety[status] == station_label(kod), status

        # Statusy spoza pipeline'u dostają własne nazwy, nie kod z podłogami.
        assert etykiety['spakowane'] == 'Spakowane'
        assert etykiety['czeka_na_logistyke'] == 'Logistyka'
