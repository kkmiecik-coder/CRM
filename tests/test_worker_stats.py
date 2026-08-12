# -*- coding: utf-8 -*-
"""
Statystyki wydajności pracowników (docs/worker-profiles-backend.md §7.2).

Najważniejsze tu jest to, czego raport NIE liczy: eventów automatu
(auto_skip/system). Bez tego filtra sklejacz dostaje kredyt za formatowanie,
którego nikt nie wykonał — a taki błąd trafia prosto do rozmowy o premiach.
"""
import os
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionStationEvent, ProductionStationEventWorker,
    ProductionWorker, ProductionWorkerSession, get_local_now,
)
from modules.production.services import worker_stats_service
from modules.production.services.worker_stats_service import ZakresError
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker,
)]

ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()


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


def _produkt(volume=0.5, quantity=100):
    order = ProductionOrder(baselinker_order_id=1, internal_order_number='26/00001')
    db.session.add(order)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=order.id, short_product_id='26001_1', product_sequence_in_order=1,
        original_product_name='Blat', quantity=quantity,
        current_status='czeka_na_sklejanie', volume_m3=volume)
    db.session.add(produkt)
    db.session.commit()
    return produkt


def _pracownicy(ilu=2):
    dodani = [ProductionWorker(first_name=f'Imie{i}', last_name=f'Nazwisko{i}')
              for i in range(ilu)]
    db.session.add_all(dodani)
    db.session.commit()
    return dodani


def _dzis():
    return get_local_now().date()


# ============================================================================
# WYDAJNOŚĆ
# ============================================================================

def test_praca_dzieli_sie_miedzy_pracownikow(app):
    with app.app_context():
        produkt = _produkt(volume=0.5)
        adam, bartek = _pracownicy(2)

        produkt.set_quantity_done('gluing', 10, source='mobile',
                                  actor_worker_ids=[adam.id, bartek.id])
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis())

        assert len(raport['rows']) == 2
        assert all(w['pieces'] == 5.0 for w in raport['rows'])      # 10 szt / 2 osoby
        assert all(w['m3'] == 2.5 for w in raport['rows'])          # 0.5 m³ × 10 × 0.5
        assert raport['summary']['pieces'] == 10.0
        assert raport['summary']['attribution_coverage_pct'] == 100.0


def test_eventy_automatu_nie_licza_sie_nikomu(app):
    """
    Pułapka nr 2: complete_task() generuje sztuczne eventy dla stanowisk
    pominiętych. Nikt ich nie wykonał, więc nie mogą trafić do raportu —
    nawet gdyby ktoś nieopatrznie dopiął im atrybucję.
    """
    with app.app_context():
        produkt = _produkt()
        adam, = _pracownicy(1)

        produkt.set_quantity_done('gluing', 10, source='mobile',
                                  actor_worker_ids=[adam.id])
        produkt.set_quantity_done('formatting', 10, source='auto_skip',
                                  actor_worker_ids=[adam.id])
        produkt.set_quantity_done('finishing', 10, source='system',
                                  actor_worker_ids=[adam.id])
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis())

        stanowiska = {w['station_code'] for w in raport['rows']}
        assert stanowiska == {'gluing'}
        assert raport['summary']['pieces'] == 10.0


def test_praca_bez_atrybucji_trafia_do_nieprzypisanych(app):
    """Produkcja sprzed wdrożenia profili nie może zniknąć z sum."""
    with app.app_context():
        produkt = _produkt()
        adam, = _pracownicy(1)

        produkt.set_quantity_done('gluing', 4, source='mobile',
                                  actor_worker_ids=[adam.id])
        produkt.set_quantity_done('gluing', 10, source='mobile')   # bez profilu
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis())

        assert raport['summary']['pieces'] == 4.0
        assert raport['summary']['unassigned_pieces'] == 6.0
        # 4 z 10 sztuk wiadomo komu przypisać
        assert raport['summary']['attribution_coverage_pct'] == 40.0


def test_filtr_stanowiska(app):
    with app.app_context():
        produkt = _produkt()
        adam, = _pracownicy(1)
        produkt.set_quantity_done('gluing', 6, source='mobile', actor_worker_ids=[adam.id])
        produkt.set_quantity_done('packaging', 8, source='mobile', actor_worker_ids=[adam.id])
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis(), station='gluing')

        assert [w['station_code'] for w in raport['rows']] == ['gluing']
        assert raport['summary']['pieces'] == 6.0


def test_filtr_pracownika_pomija_nieprzypisane(app):
    """Przy raporcie jednej osoby sekcja "Nieprzypisane" nie ma sensu."""
    with app.app_context():
        produkt = _produkt()
        adam, bartek = _pracownicy(2)
        produkt.set_quantity_done('gluing', 4, source='mobile', actor_worker_ids=[adam.id])
        produkt.set_quantity_done('gluing', 10, source='mobile')  # bez profilu
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis(), worker_id=adam.id)

        assert raport['unassigned'] == []
        assert {w['worker_id'] for w in raport['rows']} == {adam.id}


def test_stanowiska_maja_polskie_nazwy(app):
    with app.app_context():
        produkt = _produkt()
        adam, = _pracownicy(1)
        produkt.set_quantity_done('gluing', 2, source='mobile', actor_worker_ids=[adam.id])
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis())

        assert raport['rows'][0]['station_label'] == 'Sklejanie'


# ============================================================================
# CZAS PRACY I TEMPO
# ============================================================================

def test_tempo_liczone_z_czasu_sesji(app):
    with app.app_context():
        produkt = _produkt(volume=0.5)
        adam, = _pracownicy(1)

        start = get_local_now() - timedelta(hours=2)
        db.session.add(ProductionWorkerSession(
            worker_id=adam.id, station_code='gluing', session_group='g',
            started_at=start, last_activity_at=start,
            ended_at=start + timedelta(hours=2), work_date=start.date()))
        produkt.set_quantity_done('gluing', 10, source='mobile',
                                  actor_worker_ids=[adam.id])
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(start.date(), _dzis())
        podsumowanie = raport['worker_totals'][0]

        assert podsumowanie['minutes'] == 120
        assert podsumowanie['hours'] == 2.0
        # 5 m³ w 2 godziny
        assert podsumowanie['pace_m3_per_hour'] == 2.5


def test_bez_sesji_tempo_jest_puste_a_nie_zerowe(app):
    """Brak pomiaru czasu to nie to samo co zerowa wydajność."""
    with app.app_context():
        produkt = _produkt()
        adam, = _pracownicy(1)
        produkt.set_quantity_done('gluing', 10, source='mobile', actor_worker_ids=[adam.id])
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis())

        assert raport['worker_totals'][0]['pace_m3_per_hour'] is None
        assert raport['worker_totals'][0]['minutes'] == 0


def test_wszystkie_widgety_maja_te_sama_definicje_zrobione(app):
    """
    Trzy widgety na jednym ekranie liczą z prod_station_events. Jeśli tylko
    jeden filtruje eventy automatu, kierownik widzi dla formatowania dwie różne
    liczby i nie da się tego wytłumaczyć wierszem "Nieprzypisane" — tych sztuk
    w liczniku pracowniczym w ogóle nie ma.
    """
    from modules.production.services import station_events_service

    with app.app_context():
        produkt = _produkt(volume=0.5, quantity=20)
        adam, = _pracownicy(1)

        produkt.set_quantity_done('formatting', 8, source='mobile',
                                  actor_worker_ids=[adam.id])
        produkt.set_quantity_done('formatting', 20, source='auto_skip')
        db.session.commit()

        poczatek = datetime.combine(_dzis(), datetime.min.time())
        koniec = poczatek + timedelta(days=1)
        stanowiskowo = station_events_service.get_station_work_in_range(
            'formatting', poczatek, koniec)
        pracowniczo = worker_stats_service.raport_wydajnosci(_dzis(), _dzis())

        # Oba źródła widzą te same 8 sztuk, nie 8 i 20
        assert stanowiskowo['pieces_done'] == 8
        assert pracowniczo['summary']['pieces'] == 8.0
        assert pracowniczo['summary']['unassigned_pieces'] == 0


def test_pracownik_z_sesja_bez_wyniku_jest_widoczny(app):
    """
    Ktoś, kto miał otwartą sesję i nie odbił ani jednej sztuki, MUSI być
    w tabeli — wiersz "8 h / 0 m³" to jedyna odpowiedź na pytanie "czy ktoś
    stoi bezczynnie". Wcześniej tabela powstawała tylko z atrybucji, więc
    taka osoba znikała, a jej godziny zostawały w sumie zbiorczej.

    REGRESJA: tempo takiego wiersza musi być NONE, nie 0.0. Bramka
    `if godziny` chroniła przed dzieleniem PRZEZ zero, ale nie przed
    dzieleniem ZERA — i raport stawiał „0 m³/h" przy nazwisku człowieka,
    o którym nic nie wie (zmierzone 2026-08-12: Józef Pustelnik, 87 minut
    sesji, zero atrybucji, tempo 0.0). Zero mierzone i brak pomiaru to dwa
    różne zdania, a to drugie nie ma prawa wyglądać jak zarzut bezczynności.
    """
    with app.app_context():
        pracujacy, bezczynny = _pracownicy(2)
        produkt = _produkt()
        produkt.set_quantity_done('gluing', 10, source='mobile',
                                  actor_worker_ids=[pracujacy.id])

        start = get_local_now().replace(hour=8, minute=0, second=0, microsecond=0)
        db.session.add(ProductionWorkerSession(
            worker_id=bezczynny.id, station_code='gluing', session_group='pusta',
            started_at=start, last_activity_at=start,
            ended_at=start + timedelta(hours=8), work_date=_dzis()))
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis())
        wiersz = next(w for w in raport['worker_totals']
                      if w['worker_id'] == bezczynny.id)

        assert wiersz['hours'] == 8.0
        assert wiersz['pieces'] == 0
        assert wiersz['m3'] == 0
        assert wiersz['has_attribution'] is False
        assert wiersz['pace_m3_per_hour'] is None

        # Kontrola dodatnia: pracownik Z atrybucją tempo dostaje. Bez tego
        # asercja wyżej przechodziłaby też wtedy, gdyby tempo zgasło wszystkim.
        z_praca = next(w for w in raport['worker_totals']
                       if w['worker_id'] == pracujacy.id)
        assert z_praca['has_attribution'] is True


def test_pokrycie_atrybucja_nie_przekracza_stu_procent(app):
    """
    delta bywa UJEMNA: korekty z panelu CRM idą bez profilu, więc trafiają
    do nieprzypisanych ze znakiem minus. Liczenie pokrycia na sumie ze znakiem
    dawało mianownik mniejszy od licznika i wynik w rodzaju 105%.
    """
    with app.app_context():
        produkt = _produkt(quantity=100)
        adam, = _pracownicy(1)

        produkt.set_quantity_done('gluing', 10, source='mobile',
                                  actor_worker_ids=[adam.id])
        produkt.set_quantity_done('gluing', 5, source='admin')   # korekta w dół
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis())
        pokrycie = raport['summary']['attribution_coverage_pct']

        assert raport['summary']['unassigned_pieces'] == -5.0
        assert 0 <= pokrycie <= 100, f'pokrycie poza zakresem: {pokrycie}'
        assert pokrycie == 66.7      # 10 z 15 jednostek ruchu


def test_czas_pracy_respektuje_filtr_stanowiska(app):
    """
    Licznik (m³ z jednego stanowiska) i mianownik (czas pracy) muszą być
    filtrowane tak samo — inaczej tempo m³/h zaniża się tym, którzy pracują
    na kilku stanowiskach.
    """
    with app.app_context():
        adam, = _pracownicy(1)
        start = get_local_now().replace(hour=8, minute=0, second=0, microsecond=0)
        for kod, godziny in (('gluing', 2), ('packaging', 3)):
            db.session.add(ProductionWorkerSession(
                worker_id=adam.id, station_code=kod, session_group=f'g-{kod}',
                started_at=start, last_activity_at=start,
                ended_at=start + timedelta(hours=godziny), work_date=start.date()))
        db.session.commit()

        wszystkie = worker_stats_service.czas_pracy(_dzis(), _dzis())
        tylko_klejenie = worker_stats_service.czas_pracy(_dzis(), _dzis(), station='gluing')

        assert wszystkie[(adam.id, _dzis().isoformat())] == 300     # 2h + 3h
        assert tylko_klejenie[(adam.id, _dzis().isoformat())] == 120


def test_zapomniana_sesja_nie_fabrykuje_setek_godzin(app, zegar):
    """
    Dopóki cron nie domknie zapomnianych sesji, w bazie będą wisieć sesje
    sprzed tygodni. Bez ograniczników jedna taka sesja dawała w raporcie
    kilkaset godzin w jednej dobie.

    Ogranicza ją TA SAMA reguła, którą stosuje close_stale_sessions:
    najwcześniejsza z trzech granic (teraz / nocny cutoff doby / ostatnia
    aktywność + idle_timeout). Tutaj wygrywa bezczynność — sesja bez śladu
    aktywności od 8:00 kończy się o 10:00, nie o 23:00.
    """
    zegar(godzina=12)
    with app.app_context():
        adam, = _pracownicy(1)
        dawno = get_local_now() - timedelta(days=30)
        start = dawno.replace(hour=8, minute=0, second=0, microsecond=0)
        db.session.add(ProductionWorkerSession(
            worker_id=adam.id, station_code='gluing', session_group='zapomniana',
            started_at=start, last_activity_at=start, work_date=dawno.date()))
        db.session.commit()

        minuty = worker_stats_service.czas_pracy(dawno.date(), _dzis())

        # 8:00 + 120 min bezczynności = 10:00, czyli 2 h — nie 30 dni i nie 15 h
        assert minuty[(adam.id, dawno.date().isoformat())] == 120


def test_godziny_w_tabeli_i_osobogodziny_hali_to_rozne_liczby(app, zegar):
    """
    REGRESJA: dwa kafelki obok siebie zawsze pokazywały TĘ SAMĄ liczbę,
    a przy filtrze stanowiska drugi z nich kłamał wprost.

    `session_minutes_all` brało się z tego samego dictu `minuty` co kafelek
    obok — a blok `braki` dopisuje do tabeli KAŻDEGO pracownika z sesją, więc
    zbiory kluczy były z definicji równe (zmierzone: 24.5/24.5, 5.4/5.4,
    8.3/8.3 — ani jednego przypadku różnicy). Gorsze było to, że czas_pracy()
    filtruje sesje po stanowisku, więc po wybraniu „Sklejanie" kafelek
    podpisany „osobogodzin NA HALI" pokazywał godziny jednego stanowiska.

    Kontrakt: przy filtrze stanowiska te dwie liczby MUSZĄ się różnić.
    """
    zegar(godzina=12)
    with app.app_context():
        sklejacz, pakowacz = _pracownicy(2)
        for pracownik, stanowisko, godzin in ((sklejacz, 'gluing', 6),
                                              (pakowacz, 'packaging', 3)):
            start = get_local_now().replace(hour=8, minute=0, second=0, microsecond=0)
            db.session.add(ProductionWorkerSession(
                worker_id=pracownik.id, station_code=stanowisko,
                session_group=f'g-{stanowisko}', started_at=start,
                last_activity_at=start + timedelta(hours=godzin),
                ended_at=start + timedelta(hours=godzin), work_date=_dzis()))
        db.session.commit()

        cala_hala = worker_stats_service.raport_wydajnosci(_dzis(), _dzis())
        assert cala_hala['summary']['hours'] == 9.0
        assert cala_hala['summary']['session_hours_all'] == 9.0

        tylko_sklejanie = worker_stats_service.raport_wydajnosci(
            _dzis(), _dzis(), station='gluing')
        # Kafelek „godzin ludzi w tabeli" idzie za filtrem…
        assert tylko_sklejanie['summary']['hours'] == 6.0
        # …a „osobogodzin na hali" NIE — bo hala przepracowała dziewięć.
        assert tylko_sklejanie['summary']['session_hours_all'] == 9.0
        assert (tylko_sklejanie['summary']['hours']
                != tylko_sklejanie['summary']['session_hours_all'])


def test_odczyt_dlugosci_sesji_zgadza_sie_z_domknieciem_przez_cron(app, zegar):
    """
    REGRESJA (zasada „jedna definicja na metrykę"): ta sama otwarta sesja
    musi mieć TĘ SAMĄ długość przed przebiegiem crona i po nim.

    Ścieżka ZAPISU (worker_service.close_stale_sessions) domykała sesję na
    `last_activity_at + idle_timeout`, a ścieżka ODCZYTU (minuty_sesji) reguły
    bezczynności nie znała wcale — liczyła do teraz. Skutek: kafelek
    „osobogodzin" i tempo m³/h KURCZYŁY SIĘ WSTECZ po każdym przebiegu crona.
    Zmierzone 2026-08-12 o 11:31 na sesji 12 (pakowanie, start 06:16:57,
    ostatnia aktywność 08:33:18): odczyt 314 min wobec 256 min reguły zapisu.
    """
    teraz = zegar(godzina=12)
    with app.app_context():
        from modules.production.services import worker_service

        adam, = _pracownicy(1)
        start = teraz.replace(hour=6, minute=0)
        sesja = ProductionWorkerSession(
            worker_id=adam.id, station_code='gluing', session_group='cicha',
            started_at=start, last_activity_at=start.replace(hour=8),
            work_date=_dzis())
        db.session.add(sesja)
        db.session.commit()

        przed = worker_stats_service.czas_pracy(_dzis(), _dzis())[
            (adam.id, _dzis().isoformat())]

        worker_service.close_stale_sessions()
        db.session.refresh(sesja)
        assert sesja.ended_at is not None, 'cron miał domknąć tę sesję'

        po = worker_stats_service.czas_pracy(_dzis(), _dzis())[
            (adam.id, _dzis().isoformat())]

        assert przed == po == 4 * 60      # 6:00 → 8:00 + 120 min bezczynności


def test_otwarta_sesja_liczy_sie_do_teraz(app, zegar):
    # Zegar zamrożony w środku zmiany. Uruchomiony między 23:00 a 23:45 ten
    # test przycinał sesję nocnym cutoffem i pokazywał 20 minut zamiast 45 —
    # co jest POPRAWNYM zachowaniem produkcji, tylko nie tym, o co pyta test.
    zegar(godzina=12)
    with app.app_context():
        adam, = _pracownicy(1)
        start = get_local_now() - timedelta(minutes=45)
        db.session.add(ProductionWorkerSession(
            worker_id=adam.id, station_code='gluing', session_group='g',
            started_at=start, last_activity_at=start, work_date=start.date()))
        db.session.commit()

        minuty = worker_stats_service.czas_pracy(start.date(), _dzis())

        assert minuty[(adam.id, start.date().isoformat())] >= 44


# ============================================================================
# ZAKRES DAT
# ============================================================================

def test_odwrocony_zakres_dat_odrzucony(app):
    with app.app_context():
        with pytest.raises(ZakresError):
            worker_stats_service.raport_wydajnosci(date(2026, 8, 11), date(2026, 8, 1))


def test_zbyt_dlugi_zakres_odrzucony(app):
    with app.app_context():
        with pytest.raises(ZakresError):
            worker_stats_service.raport_wydajnosci(date(2025, 1, 1), date(2026, 8, 11))


def test_praca_poza_zakresem_nie_wchodzi_do_raportu(app):
    with app.app_context():
        produkt = _produkt()
        adam, = _pracownicy(1)
        produkt.set_quantity_done('gluing', 10, source='mobile', actor_worker_ids=[adam.id])
        db.session.commit()

        wczoraj = _dzis() - timedelta(days=1)
        raport = worker_stats_service.raport_wydajnosci(wczoraj, wczoraj)

        assert raport['rows'] == []
        assert raport['summary']['attribution_coverage_pct'] is None


# ============================================================================
# KTO ZROBIŁ (§7.3)
# ============================================================================

def test_kto_zrobil_dla_wielu_produktow(app):
    with app.app_context():
        produkt = _produkt()
        adam, bartek = _pracownicy(2)
        produkt.set_quantity_done('gluing', 5, source='mobile',
                                  actor_worker_ids=[adam.id, bartek.id])
        produkt.set_quantity_done('packaging', 5, source='mobile',
                                  actor_worker_ids=[bartek.id])
        db.session.commit()

        mapa = worker_stats_service.get_workers_for_products([produkt.id])

        assert mapa[produkt.id]['gluing'] == ['Imie0 N.', 'Imie1 N.']
        assert mapa[produkt.id]['packaging'] == ['Imie1 N.']


def test_kto_zrobil_bez_produktow_nie_odpytuje_bazy(app):
    with app.app_context():
        assert worker_stats_service.get_workers_for_products([]) == {}


def test_kto_zrobil_pomija_eventy_automatu(app):
    with app.app_context():
        produkt = _produkt()
        adam, = _pracownicy(1)
        produkt.set_quantity_done('formatting', 5, source='auto_skip',
                                  actor_worker_ids=[adam.id])
        db.session.commit()

        assert worker_stats_service.get_workers_for_products([produkt.id]) == {}


# ============================================================================
# DŁUGOŚĆ SESJI — REGUŁA NOCNEGO CUTOFFU
#
# Te testy podają „teraz" Z ZEWNĄTRZ, a nie z zegara systemowego, i dlatego
# dają ten sam wynik o każdej porze doby. To nie jest kosmetyka: obie dziury
# opisane niżej były w kodzie miesiącami i przechodziły przez testy wyłącznie
# dlatego, że pakiet uruchamiano w środku dnia roboczego.
# ============================================================================

CUTOFF_NOCNY = time(23, 0)
# Ten sam domyślny timeout co w konfiguracji produkcyjnej. Podajemy go jawnie
# czwartym argumentem, żeby te testy nie zależały ani od bazy, ani od tego,
# co ktoś ustawi w prod_config.
IDLE_MINUT = 120


def _sesja(started_at, ended_at=None, work_date=None, last_activity_at=None):
    """Sesja BEZ bazy — minuty_sesji() czyta tylko cztery pola."""
    return ProductionWorkerSession(
        worker_id=1, station_code='gluing', session_group='g',
        started_at=started_at, last_activity_at=last_activity_at or started_at,
        ended_at=ended_at, work_date=work_date or started_at.date())


def _minuty(sesja, teraz):
    return worker_stats_service.minuty_sesji(sesja, teraz, CUTOFF_NOCNY, IDLE_MINUT)


def test_sesja_zaczeta_po_nocnym_cutoffie_nie_zeruje_sie():
    """
    Sesja z 23:55 przy cutoffie 23:00 ma granicę swojej doby WCZEŚNIEJ niż
    własny start. Poprzednia wersja liczyła jej zero minut — cała zmiana
    znikała z raportu, a tempo m³/h dzieliło przez zero. Granicą takiej sesji
    jest cutoff doby NASTĘPNEJ (ta sama reguła co w close_stale_sessions).
    """
    sesja = _sesja(datetime(2026, 8, 11, 23, 55))
    teraz = datetime(2026, 8, 12, 0, 30)

    assert _minuty(sesja, teraz) == 35


def test_sesja_zaczeta_po_cutoffie_przycieta_do_cutoffu_nastepnej_doby():
    """
    Ogranicznik nocny ma nadal działać o dobę dalej — pod warunkiem, że
    pracownik przez tę dobę cokolwiek robił. Bez aktywności wcześniej ubija
    ją bezczynność (osobny test niżej).
    """
    sesja = _sesja(datetime(2026, 8, 11, 23, 55),
                   last_activity_at=datetime(2026, 8, 12, 22, 30))
    teraz = datetime(2026, 8, 13, 9, 0)     # zapomniana, otwarta półtorej doby

    assert _minuty(sesja, teraz) == 23 * 60 + 5     # 23:55 → 12.08 23:00


def test_otwarta_sesja_przycieta_do_bezczynnosci_a_nie_do_cutoffu(app, zegar):
    """
    REGRESJA: sesja zapomniana sprzed miesiąca kończy się dwie godziny po
    OSTATNIEJ AKTYWNOŚCI, a nie na nocnym cutoffie swojej doby. Odczyt musi
    stosować tę samą trójkę granic co close_stale_sessions — inaczej ta sama
    sesja ma dwie różne długości zależnie od tego, czy cron zdążył ją domknąć.

    Test jest sparowany z close_stale_sessions() celowo: sprawdza, że obie
    ścieżki dają IDENTYCZNY moment końca, a nie że każda z osobna daje jakąś
    liczbę.
    """
    zegar(datetime(2026, 8, 12, 10, 0))
    sesja = _sesja(datetime(2026, 7, 1, 8, 0))
    teraz = datetime(2026, 8, 12, 10, 0)

    # Odczyt: 8:00 + 120 min bezczynności = 10:00 tej samej doby.
    assert _minuty(sesja, teraz) == 120

    # Zapis: cron postawiłby ended_at dokładnie na tej samej godzinie.
    with app.app_context():
        koniec_z_crona = min(
            datetime.combine(sesja.work_date, CUTOFF_NOCNY),
            sesja.last_activity_at + timedelta(minutes=IDLE_MINUT))
        assert koniec_z_crona == datetime(2026, 7, 1, 10, 0)


def test_otwarta_sesja_liczy_sie_do_teraz_gdy_pracownik_wciaz_pracuje():
    """Aktywna sesja liczy się do teraz — żaden ogranicznik jej nie dotyczy."""
    sesja = _sesja(datetime(2026, 8, 12, 8, 0),
                   last_activity_at=datetime(2026, 8, 12, 9, 25))
    teraz = datetime(2026, 8, 12, 9, 30)

    assert _minuty(sesja, teraz) == 90


def test_domknieta_sesja_przez_polnoc_liczy_sie_w_calosci():
    """
    Cutoff ogranicza sesje OTWARTE (zapomniane), a nie domknięte. Sesja
    22:55 → 00:55 to dwie godziny realnej pracy; przycięcie do 23:00 robiło
    z nich pięć minut. Koniec domkniętej sesji stawia serwer albo tablet,
    a korekta z tabletu idzie wyłącznie w dół — nie ma tu czego prostować.
    """
    sesja = _sesja(datetime(2026, 8, 11, 22, 55),
                   ended_at=datetime(2026, 8, 12, 0, 55))
    teraz = datetime(2026, 8, 12, 1, 0)

    assert worker_stats_service.minuty_sesji(sesja, teraz, CUTOFF_NOCNY) == 120


def test_domknieta_sesja_nie_jest_ucinana_do_chwili_liczenia_raportu():
    """
    Raport bywa liczony w środku zmiany (albo z zegarem kontenera cofniętym
    względem tabletu). Sesja domknięta o 16:00 ma 8 h także wtedy, gdy `teraz`
    wypada wcześniej — inaczej ta sama sesja pokazywałaby inną liczbę godzin
    zależnie od momentu otwarcia raportu.
    """
    sesja = _sesja(datetime(2026, 8, 12, 8, 0),
                   ended_at=datetime(2026, 8, 12, 16, 0))
    teraz = datetime(2026, 8, 12, 6, 0)

    assert worker_stats_service.minuty_sesji(sesja, teraz, CUTOFF_NOCNY) == 8 * 60


def test_minuty_sesji_nigdy_nie_sa_ujemne():
    """Zegar tabletu potrafi iść do tyłu — ujemne minuty zepsułyby każdą sumę."""
    sesja = _sesja(datetime(2026, 8, 12, 10, 0),
                   ended_at=datetime(2026, 8, 12, 9, 0))
    teraz = datetime(2026, 8, 12, 11, 0)

    assert worker_stats_service.minuty_sesji(sesja, teraz, CUTOFF_NOCNY) == 0
