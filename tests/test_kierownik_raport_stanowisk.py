# -*- coding: utf-8 -*-
"""GET /api/mobile/manager/reports/stations — przerób stanowisk za dowolny zakres dat (kontrakt §8.5).

Raport dzienny (`daily_report_service.zbierz_dane`) i ten raport liczą z TYCH SAMYCH helperów, więc jeden dzień ma dać
dokładnie te same liczby. Tu pilnujemy też zasad zakresu (oba końce albo żaden, najwyżej 92 dni) oraz tego, że
odpowiedź nie niesie pieniędzy."""
import itertools
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from werkzeug.datastructures import MultiDict

from extensions import db
from modules.production.kierownik.services import biala_lista, raporty
from modules.production.models import (
    ProductionStationEvent, ProductionStationEventWorker, ProductionWorker, get_local_now,
)
from modules.production.sawmill.models import (
    SawmillAudit, SawmillCounter, SawmillDelivery, SawmillLog, SawmillOrder, SawmillSpecies, SawmillSupplier,
)
from modules.production.services import daily_report_service
from modules.production.services.station_catalog import STATION_ORDER
from tests.kierownik_pomocnicze import API, ENDPOINTY_KIEROWNIKA, naglowki, tablet_kierownika
from tests.logistyka_fixtures import app, client, produkt, zamowienie  # noqa: F401

TABELE_DODATKOWE = [m.__table__ for m in (
    ProductionStationEventWorker, SawmillSupplier, SawmillSpecies, SawmillCounter, SawmillDelivery, SawmillOrder,
    SawmillLog, SawmillAudit)]

# Stałe daty: raport kubełkuje po dobach, więc test liczony „od dziś" przechodziłby przez inne gałęzie w różne dni.
PON = date(2026, 8, 10)
_licznik = itertools.count(1)


@pytest.fixture()
def tablet(app):
    db.metadata.create_all(bind=db.engine, tables=TABELE_DODATKOWE)
    return tablet_kierownika()


def _get(client, tablet, **parametry):
    device, kierownik = tablet
    return client.get(API + '/reports/stations', headers=naglowki(device, kierownik), query_string=parametry)


def _ok(client, tablet, **parametry):
    r = _get(client, tablet, **parametry)
    assert r.status_code == 200, r.get_data()[:500]
    return r.get_json()


def _poz(order, status='spakowane', quantity=10, volume=0.5, wartosc=1000.0):
    """Pozycja z objętością sztuki i wartością (wartość MUSI być w bazie, żeby test wartości mógł się wywrócić)."""
    p = produkt(order, status=status, quantity=quantity)
    p.volume_m3 = volume
    p.total_value_net = wartosc
    db.session.commit()
    return p


def _zam_z_pozycja(**kolumny):
    o = zamowienie(statusy=(), **kolumny)
    return o, _poz(o)


def _zdarzenie(p, stanowisko, delta, kiedy, source='mobile'):
    db.session.add(ProductionStationEvent(
        production_item_id=p.id, station_code=stanowisko, delta=delta, quantity_done_after=max(0, delta),
        created_at=kiedy, source=source))
    db.session.commit()


def _o(dzien, g=10, m=0, s=0):
    return datetime.combine(dzien, time(g, m, s))


def _stanowisko(dane, kod):
    return next(s for s in dane['stanowiska'] if s['kod'] == kod)


def _kloda(zlecenie, volume, kiedy):
    db.session.add(SawmillLog(order_id=zlecenie.id, sequence_no=next(_licznik), mid_diameter_cm=40.0,
                              length_cm=250.0, volume_m3=volume, is_deleted=False, measured_at=kiedy))
    db.session.commit()


def _zlecenie_trakowni():
    dostawca, gatunek = SawmillSupplier(name='Tartak Testowy'), SawmillSpecies(name='Dąb')
    db.session.add_all([dostawca, gatunek])
    db.session.flush()
    dostawa = SawmillDelivery(supplier_id=dostawca.id, delivery_date=PON)
    db.session.add(dostawa)
    db.session.flush()
    zlecenie = SawmillOrder(order_number='TRK/2026/001', delivery_id=dostawa.id, species_id=gatunek.id,
                            declared_volume_m3=Decimal('80.000'))
    db.session.add(zlecenie)
    db.session.commit()
    return zlecenie


def _args(**kw):
    return MultiDict({k: v for k, v in kw.items() if v is not None})


# ── lista endpointów i bramka ────────────────────────────────────────────────────────────────────────────────

def test_trasa_jest_na_liscie_endpointow():
    assert ('GET', '/reports/stations') in ENDPOINTY_KIEROWNIKA


def test_bramka_kierownika(app, client):
    from modules.production.models import ProductionDevice
    device, kierownik = tablet_kierownika()
    obcy = ProductionDevice(device_id='TAB-OBCY-RAP', device_name='Formatowanie', station_code='formatting')
    db.session.add(obcy)
    db.session.commit()
    r = client.get(API + '/reports/stations', headers=naglowki(obcy, kierownik))
    assert r.status_code == 403 and r.get_json()['error'] == 'station_not_allowed'
    r = client.get(API + '/reports/stations', headers=naglowki(device))
    assert r.status_code == 400 and r.get_json()['error'] == 'worker_required'


def test_odpowiedz_no_store(app, client, tablet):
    r = _get(client, tablet, start_date='2026-08-10', end_date='2026-08-10')
    assert r.status_code == 200
    assert 'no-store' in r.headers['Cache-Control']


# ── jeden dzień == raport dzienny ────────────────────────────────────────────────────────────────────────────

def _dane_wielu_stanowisk():
    """Dwa zamówienia na kilku stanowiskach: cofnięcie, automat, granice doby, pakowanie i kłody trakowni."""
    o1, p1 = _zam_z_pozycja()
    o2 = zamowienie(statusy=())
    p2 = _poz(o2, status='czeka_na_formatowanie', quantity=4, volume=0.25, wartosc=400.0)
    p3 = _poz(o2, status='czeka_na_pakowanie', quantity=7, volume=0.1, wartosc=700.0)
    _zdarzenie(p1, 'cutting', 10, _o(PON, 7))
    _zdarzenie(p1, 'gluing', 6, _o(PON, 10))
    _zdarzenie(p1, 'gluing', -2, _o(PON, 14))
    _zdarzenie(p1, 'formatting', 10, _o(PON, 11), source='auto_skip')
    _zdarzenie(p2, 'formatting', 4, _o(PON, 12, 30))
    _zdarzenie(p2, 'edges', 4, _o(PON, 23, 59, 59))
    _zdarzenie(p2, 'edges', 3, _o(PON + timedelta(days=1), 0, 0, 0))
    _zdarzenie(p3, 'packaging', 7, _o(PON, 15))
    _zdarzenie(p1, 'packaging', 5, _o(PON, 9))
    _zdarzenie(p1, 'packaging', -1, _o(PON, 16))
    zlecenie = _zlecenie_trakowni()
    _kloda(zlecenie, 1.5, _o(PON, 8))
    _kloda(zlecenie, 2.0, _o(PON - timedelta(days=1), 16))


def test_jeden_dzien_rowny_raportowi_dziennemu(app, client, tablet):
    _dane_wielu_stanowisk()
    dzienne = daily_report_service.zbierz_dane(PON)

    dane = _ok(client, tablet, start_date='2026-08-10', end_date='2026-08-10')

    assert [s['kod'] for s in dane['stanowiska']] == list(STATION_ORDER)
    for wiersz in dane['stanowiska']:
        wzor = next(s for s in dzienne['stanowiska'] if s['kod'] == wiersz['kod'])
        assert wiersz['sztuki'] == wzor['sztuki'], wiersz['kod']
        assert wiersz['m3'] == pytest.approx(wzor['m3'], abs=1e-4), wiersz['kod']
        assert wiersz['zamowien'] == wzor['zamowienia'], wiersz['kod']
        assert wiersz['cofniecia'] == wzor['cofniecia'], wiersz['kod']
        assert wiersz['kolejka_szt'] == wzor['kolejka_szt'], wiersz['kod']
        assert wiersz['kolejka_m3'] == pytest.approx(wzor['kolejka_m3'], abs=1e-4), wiersz['kod']
    wykonanie = dzienne['wykonanie']
    assert dane['hala']['sztuki'] == wykonanie['sztuki']
    assert dane['hala']['m3'] == pytest.approx(wykonanie['m3'], abs=1e-4)
    assert dane['hala']['pozycji'] == wykonanie['pozycje']
    assert dane['hala']['zamowien'] == wykonanie['zamowienia']
    assert dane['hala']['cofniecia'] == wykonanie['cofniecia']
    assert dane['zakonczone'] == {'sztuki': dzienne['zakonczone']['sztuki'],
                                  'm3': pytest.approx(dzienne['zakonczone']['m3'], abs=1e-4)}
    assert dane['trakownia'] == {'klody': dzienne['trakownia']['klody'],
                                 'm3': pytest.approx(dzienne['trakownia']['m3'], abs=1e-4)}
    # Sprawdzamy też same liczby, żeby test nie przechodził na porównaniu zer z zerami.
    assert _stanowisko(dane, 'gluing')['sztuki'] == 4 and _stanowisko(dane, 'gluing')['cofniecia'] == 2
    assert _stanowisko(dane, 'formatting')['sztuki'] == 4          # automat (10) pominięty
    assert _stanowisko(dane, 'edges')['sztuki'] == 4               # 23:59:59 jeszcze w dobie
    assert dane['zakonczone']['sztuki'] == 11                      # 7 + 5 - 1
    assert dane['trakownia'] == {'klody': 1, 'm3': 1.5}


def test_pozycji_na_stanowisku_to_unikalne_pozycje(app, client, tablet):
    o, p = _zam_z_pozycja()
    p_b = _poz(o)
    _zdarzenie(p, 'gluing', 3, _o(PON, 8))
    _zdarzenie(p, 'gluing', 2, _o(PON, 9))        # ta sama pozycja drugi raz
    _zdarzenie(p_b, 'gluing', 1, _o(PON, 10))
    _zdarzenie(p, 'edges', 1, _o(PON, 11))

    dane = _ok(client, tablet, start_date='2026-08-10', end_date='2026-08-10')

    assert _stanowisko(dane, 'gluing')['pozycji'] == 2
    assert _stanowisko(dane, 'gluing')['zamowien'] == 1
    assert _stanowisko(dane, 'edges')['pozycji'] == 1
    assert dane['hala']['pozycji'] == 2 and dane['hala']['zamowien'] == 1


# ── zakres ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_zakres_tygodnia_sumuje_dni(app, client, tablet):
    o1, p1 = _zam_z_pozycja()
    o2, p2 = _zam_z_pozycja()
    for i, dzien in enumerate((PON, PON + timedelta(days=2), PON + timedelta(days=6))):
        _zdarzenie(p1, 'gluing', 2 + i, _o(dzien, 9))
    _zdarzenie(p2, 'gluing', 4, _o(PON + timedelta(days=1), 9))
    _zdarzenie(p2, 'gluing', -1, _o(PON + timedelta(days=1), 15))
    _zdarzenie(p1, 'packaging', 5, _o(PON + timedelta(days=3), 9))
    _zdarzenie(p1, 'gluing', 9, _o(PON + timedelta(days=7), 9))          # poza zakresem
    _zdarzenie(p1, 'gluing', 9, _o(PON - timedelta(days=1), 23, 59, 59))  # poza zakresem

    dane = _ok(client, tablet, start_date='2026-08-10', end_date='2026-08-16')

    assert dane['start_date'] == '2026-08-10' and dane['end_date'] == '2026-08-16'
    gluing = _stanowisko(dane, 'gluing')
    assert gluing['sztuki'] == 2 + 3 + 4 + 4 - 1
    assert gluing['m3'] == pytest.approx(12 * 0.5)
    assert gluing['cofniecia'] == 1
    # Zamówienia i pozycje to unikaty z całego zakresu: p1 dotknięto trzy razy, a liczy się raz.
    assert gluing['pozycji'] == 2 and gluing['zamowien'] == 2
    assert dane['hala']['zamowien'] == 2 and dane['hala']['pozycji'] == 2
    assert dane['zakonczone'] == {'sztuki': 5, 'm3': 2.5}


def test_zamowienia_hali_to_unikaty_a_nie_suma_stanowisk(app, client, tablet):
    o, p = _zam_z_pozycja()
    for kod in ('cutting', 'gluing', 'packaging'):
        _zdarzenie(p, kod, 1, _o(PON, 9))

    dane = _ok(client, tablet, start_date='2026-08-10', end_date='2026-08-10')

    assert sum(s['zamowien'] for s in dane['stanowiska']) == 3
    assert dane['hala']['zamowien'] == 1


def test_trakownia_poza_suma_hali(app, client, tablet):
    zlecenie = _zlecenie_trakowni()
    _kloda(zlecenie, 3.0, _o(PON, 8))
    _kloda(zlecenie, 1.0, _o(PON + timedelta(days=2), 8))

    dane = _ok(client, tablet, start_date='2026-08-10', end_date='2026-08-12')

    assert dane['trakownia'] == {'klody': 2, 'm3': 4.0}
    assert dane['hala']['m3'] == 0 and dane['hala']['sztuki'] == 0


def test_kolejka_i_dni_zapasu_to_stan_teraz(app, client, tablet):
    """Kolejka nie zależy od zakresu: raport sprzed miesiąca pokazuje dzisiejszą kolejkę (jak panel)."""
    o = zamowienie(statusy=())
    _poz(o, status='czeka_na_sklejanie', quantity=10, volume=0.5)
    _poz(o, status='czeka_na_sklejanie', quantity=4, volume=0.25)

    dane = _ok(client, tablet, start_date='2020-01-01', end_date='2020-01-02')

    gluing = _stanowisko(dane, 'gluing')
    assert gluing['kolejka_szt'] == 14
    assert gluing['kolejka_m3'] == pytest.approx(6.0)
    assert gluing['sztuki'] == 0
    # Kolejka stoi, a stanowisko nic nie zrobiło w oknie dni roboczych: brak danych to null, nie zero.
    assert gluing['dni_zapasu'] is None
    assert _stanowisko(dane, 'cutting')['dni_zapasu'] in (None, 0.0)


def test_wstrzymane_osobno_od_kolejek_i_niezalezne_od_zakresu(app, client, tablet):
    """Wstrzymane: stan teraz, poza `kolejka_*`; bez wstrzymanych same zera."""
    puste = _ok(client, tablet)
    assert puste['wstrzymane'] == {'pozycji': 0, 'sztuki': 0, 'm3': 0.0}

    o = zamowienie(statusy=())
    _poz(o, status='wstrzymane', quantity=24, volume=0.0330625)
    _poz(o, status='wstrzymane', quantity=2, volume=0.5)
    _poz(o, status='czeka_na_sklejanie', quantity=10, volume=0.5)
    _poz(o, status='spakowane', quantity=7, volume=1.0)

    dane = _ok(client, tablet, start_date='2020-01-01', end_date='2020-01-02')

    assert dane['wstrzymane'] == {'pozycji': 2, 'sztuki': 26, 'm3': pytest.approx(1.7935)}
    # Nie wchodzi do kolejek stanowisk: kolejka sklejania to tylko jej własna pozycja.
    assert _stanowisko(dane, 'gluing')['kolejka_m3'] == pytest.approx(5.0)
    assert sum(s['kolejka_m3'] for s in dane['stanowiska']) == pytest.approx(5.0)


def test_dni_zapasu_z_przerobu_14_dni_roboczych(app, client, tablet):
    """Przerób z okna dni roboczych dzieli kolejkę: te same dni zapasu co w panelu."""
    from modules.production.services import reports_service

    o, p = _zam_z_pozycja()
    teraz = get_local_now()
    _zdarzenie(p, 'gluing', 10, datetime.combine(teraz.date(), time(8, 0)))             # dziś, 5 m³
    _poz(o, status='czeka_na_sklejanie', quantity=20, volume=0.5)                       # kolejka 10 m³

    dane = _ok(client, tablet, start_date=teraz.date().isoformat(), end_date=teraz.date().isoformat())

    panel = next(s for s in reports_service.dni_zapasu_stanowisk()['stations'] if s['station_code'] == 'gluing')
    assert _stanowisko(dane, 'gluing')['dni_zapasu'] == panel['days_of_supply']
    assert panel['days_of_supply'] is not None


def test_nazwy_stanowisk_jak_w_przegladzie(app, client, tablet):
    dane = _ok(client, tablet)
    assert [(s['kod'], s['nazwa']) for s in dane['stanowiska']][3] == ('formatting', 'Formatowanie')


# ── błędy zakresu ────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('parametry', [
    {'start_date': '2026-08-10'},                                 # tylko początek
    {'end_date': '2026-08-10'},                                   # tylko koniec
    {'start_date': '2026-08-12', 'end_date': '2026-08-10'},       # start > end
    {'start_date': '2026-01-01', 'end_date': '2026-04-04'},       # 94 dni
    {'start_date': '2026-13-01', 'end_date': '2026-13-02'},       # zły miesiąc
    {'start_date': 'wczoraj', 'end_date': '2026-08-10'},          # nie data
    {'start_date': '2026-8-1', 'end_date': '2026-08-10'},         # nie RRRR-MM-DD
    {'start_date': '2026-08-10', 'end_date': ''},                 # jedna data pusta
])
def test_zakres_bledy(app, client, tablet, parametry):
    r = _get(client, tablet, **parametry)
    assert r.status_code == 400, r.get_data()[:300]
    cialo = r.get_json()
    assert cialo['error'] == 'zakres_niepoprawny' and cialo['message']


def test_zakres_granica_92_dni(app, client, tablet):
    pierwszy = date(2026, 6, 1)
    r = _get(client, tablet, start_date=pierwszy.isoformat(),
             end_date=(pierwszy + timedelta(days=91)).isoformat())          # dokładnie 92 dni
    assert r.status_code == 200
    r = _get(client, tablet, start_date=pierwszy.isoformat(),
             end_date=(pierwszy + timedelta(days=92)).isoformat())          # 93 dni
    assert r.status_code == 400 and r.get_json()['error'] == 'zakres_niepoprawny'


def test_zakres_domyslnie_dzisiaj(app, client, tablet):
    dzis = get_local_now().date().isoformat()
    dane = _ok(client, tablet)
    assert dane['start_date'] == dzis and dane['end_date'] == dzis


def test_zakres_serwis_jednostkowo():
    assert raporty.zakres(_args(start_date='2026-08-10', end_date='2026-08-10')) == (PON, PON)
    assert raporty.zakres(_args(start_date='2026-08-10', end_date='2026-08-12')) == (PON, date(2026, 8, 12))
    dzis = get_local_now().date()
    assert raporty.zakres(_args()) == (dzis, dzis)
    with pytest.raises(raporty.BladZakresu):
        raporty.zakres(_args(start_date='2026-08-10'))


def test_zakres_bez_pracy_same_zera(app, client, tablet):
    dane = _ok(client, tablet, start_date='2026-08-10', end_date='2026-08-16')

    assert len(dane['stanowiska']) == 7
    for s in dane['stanowiska']:
        assert (s['sztuki'], s['m3'], s['pozycji'], s['zamowien'], s['cofniecia']) == (0, 0, 0, 0, 0)
        assert (s['kolejka_szt'], s['kolejka_m3']) == (0, 0)
    assert dane['hala'] == {'sztuki': 0, 'm3': 0, 'pozycji': 0, 'zamowien': 0, 'cofniecia': 0}
    assert dane['zakonczone'] == {'sztuki': 0, 'm3': 0}
    assert dane['trakownia'] == {'klody': 0, 'm3': 0}


# ── bez pieniędzy ────────────────────────────────────────────────────────────────────────────────────────────

def test_bez_wartosci_netto(app, client, tablet):
    _dane_wielu_stanowisk()
    r = _get(client, tablet, start_date='2026-08-10', end_date='2026-08-11')
    assert r.status_code == 200
    dane = r.get_json()

    assert biala_lista.zakazane_w(dane) == []
    tekst = r.get_data(as_text=True)
    assert 'wartosc' not in tekst and 'value_net' not in tekst
    # Wartość pozycji była w bazie (1000 zł), więc serwis ją liczy dla XLSX, ale DTO jej nie wydaje.
    assert daily_report_service.zbierz_dane(PON)['wykonanie']['wartosc_netto'] > 0


def test_odczyt_nic_nie_zapisuje(app, client, tablet):
    """Czysty odczyt: poza znacznikiem kontaktu urządzenia żadnych zapisów (kontrakt §2)."""
    _dane_wielu_stanowisk()
    zdarzen_przed = ProductionStationEvent.query.count()
    _ok(client, tablet, start_date='2026-08-10', end_date='2026-08-10')
    assert ProductionStationEvent.query.count() == zdarzen_przed
    assert not db.session.new and not db.session.dirty


def test_granice_zakresu_jak_doba_i_obejmuja_ostatnia_sekunde():
    assert daily_report_service.granice_zakresu(PON, PON) == daily_report_service._granice_doby(PON)
    poczatek, koniec = daily_report_service.granice_zakresu(PON, PON + timedelta(days=2))
    assert poczatek == datetime(2026, 8, 10, 0, 0, 0)
    assert koniec == datetime(2026, 8, 12, 23, 59, 59, 999999)
