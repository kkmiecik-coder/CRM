# -*- coding: utf-8 -*-
"""GET /api/mobile/manager/reports/workers i /reports/daily — wydajność pracowników i przerób dzień po dniu
(kontrakt §8.6 i §8.7). Pierwszy owija `worker_stats_service.raport_wydajnosci`, drugi `get_station_work_per_day`.

Reguła tempa (decyzja kierownika projektu): `godziny` to obecność, czyli wszystkie sesje pracownika, ale `tempo_m3_h`
dzieli się przez minuty sesji na stanowiskach procesu (`STATION_ORDER`). Sesja kierownika (`manager`) albo trakowni
nie zaniża więc m³/h; ta sama reguła dotyczy panelu i XLSX raportu dziennego (jedna funkcja)."""
import itertools
from datetime import date, datetime, time, timedelta

import pytest

from extensions import db
from modules.production.kierownik.services import biala_lista, raporty
from modules.production.models import (
    ProductionStationEvent, ProductionStationEventWorker, ProductionWorker, ProductionWorkerSession, get_local_now,
)
from modules.production.sawmill.models import (
    SawmillAudit, SawmillCounter, SawmillDelivery, SawmillLog, SawmillOrder, SawmillSpecies, SawmillSupplier,
)
from modules.production.services import daily_report_service, reports_service, worker_stats_service
from modules.production.services.station_catalog import STATION_ORDER
from tests.kierownik_pomocnicze import API, ENDPOINTY_KIEROWNIKA, naglowki, tablet_kierownika
from tests.logistyka_fixtures import app, client, produkt, zamowienie  # noqa: F401

TABELE_DODATKOWE = [m.__table__ for m in (
    ProductionStationEventWorker, SawmillSupplier, SawmillSpecies, SawmillCounter, SawmillDelivery, SawmillOrder,
    SawmillLog, SawmillAudit)]

PON = date(2026, 8, 10)
_licznik = itertools.count(1)


@pytest.fixture()
def tablet(app):
    db.metadata.create_all(bind=db.engine, tables=TABELE_DODATKOWE)
    return tablet_kierownika()


def _get(client, tablet, sciezka, **parametry):
    device, kierownik = tablet
    return client.get(API + sciezka, headers=naglowki(device, kierownik), query_string=parametry)


def _ok(client, tablet, sciezka, **parametry):
    r = _get(client, tablet, sciezka, **parametry)
    assert r.status_code == 200, r.get_data()[:500]
    return r.get_json()


def _pracownik(imie='Adam', nazwisko=None):
    p = ProductionWorker(first_name=imie, last_name=nazwisko or 'Nowak %d' % next(_licznik), is_active=True)
    db.session.add(p)
    db.session.commit()
    return p


def _poz(order=None, quantity=10, volume=0.5):
    order = order or zamowienie(statusy=())
    p = produkt(order, status='spakowane', quantity=quantity)
    p.volume_m3 = volume
    p.total_value_net = 1000.0
    db.session.commit()
    return p


def _o(dzien, g=10, m=0, s=0):
    return datetime.combine(dzien, time(g, m, s))


def _zdarzenie(p, stanowisko, delta, kiedy, kto=(), source='mobile'):
    """Zdarzenie stanowiska; `kto` — pracownicy z równym udziałem (pusta lista = praca nieprzypisana)."""
    ev = ProductionStationEvent(production_item_id=p.id, station_code=stanowisko, delta=delta,
                                quantity_done_after=max(0, delta), created_at=kiedy, source=source)
    db.session.add(ev)
    db.session.flush()
    for pracownik in kto:
        db.session.add(ProductionStationEventWorker(event_id=ev.id, worker_id=pracownik.id,
                                                    share=1.0 / len(kto)))
    db.session.commit()
    return ev


def _sesja(pracownik, stanowisko, dzien=PON, godzin=2, od=time(8, 0), otwarta=False):
    start = datetime.combine(dzien, od)
    db.session.add(ProductionWorkerSession(
        worker_id=pracownik.id, station_code=stanowisko, session_group='g%d' % next(_licznik),
        started_at=start, last_activity_at=start, ended_at=None if otwarta else start + timedelta(hours=godzin),
        work_date=dzien))
    db.session.commit()


def _wiersz(dane, pracownik):
    return next(w for w in dane['pracownicy'] if w['id'] == pracownik.id)


# ── lista endpointów i bramka ────────────────────────────────────────────────────────────────────────────────

def test_trasy_sa_na_liscie_endpointow():
    assert ('GET', '/reports/workers') in ENDPOINTY_KIEROWNIKA
    assert ('GET', '/reports/daily') in ENDPOINTY_KIEROWNIKA


@pytest.mark.parametrize('sciezka', ['/reports/workers', '/reports/daily'])
def test_bramka_kierownika(app, client, sciezka):
    from modules.production.models import ProductionDevice
    device, kierownik = tablet_kierownika()
    obcy = ProductionDevice(device_id='TAB-OBCY-%d' % next(_licznik), device_name='Formatowanie',
                            station_code='formatting')
    db.session.add(obcy)
    db.session.commit()
    r = client.get(API + sciezka, headers=naglowki(obcy, kierownik))
    assert r.status_code == 403 and r.get_json()['error'] == 'station_not_allowed'
    r = client.get(API + sciezka, headers=naglowki(device))
    assert r.status_code == 400 and r.get_json()['error'] == 'worker_required'


@pytest.mark.parametrize('sciezka', ['/reports/workers', '/reports/daily'])
def test_odpowiedz_no_store(app, client, tablet, sciezka):
    r = _get(client, tablet, sciezka, start_date='2026-08-10', end_date='2026-08-10')
    assert r.status_code == 200 and 'no-store' in r.headers['Cache-Control']


@pytest.mark.parametrize('sciezka', ['/reports/workers', '/reports/daily'])
@pytest.mark.parametrize('parametry', [
    {'start_date': '2026-08-10'},
    {'start_date': '2026-08-12', 'end_date': '2026-08-10'},
    {'start_date': '2026-01-01', 'end_date': '2026-04-04'},
    {'start_date': '2026-13-01', 'end_date': '2026-13-02'},
])
def test_zakres_bledy(app, client, tablet, sciezka, parametry):
    r = _get(client, tablet, sciezka, **parametry)
    assert r.status_code == 400, r.get_data()[:300]
    assert r.get_json()['error'] == 'zakres_niepoprawny'


# ── pracownicy (§8.6) ────────────────────────────────────────────────────────────────────────────────────────

def _dane_pracownikow():
    """Dwóch pracowników na kilku stanowiskach, praca zespołowa, praca nieprzypisana i kłoda poza procesem."""
    adam, ewa, ola = _pracownik('Adam'), _pracownik('Ewa'), _pracownik('Ola')
    p1, p2 = _poz(volume=0.5), _poz(volume=0.25)
    _zdarzenie(p1, 'formatting', 4, _o(PON, 9), kto=[adam])                  # 2.0 m³
    _zdarzenie(p1, 'edges', 3, _o(PON, 11), kto=[adam, ewa])                 # po 1.5 szt., 0.75 m³
    _zdarzenie(p2, 'edges', 2, _o(PON + timedelta(days=1), 9), kto=[ewa])    # 0.5 m³
    _zdarzenie(p2, 'gluing', 5, _o(PON, 13))                                 # nieprzypisane: 5 szt., 1.25 m³
    _zdarzenie(p2, 'formatting', 9, _o(PON, 14), source='auto_skip')         # automat: nie liczy się nikomu
    _sesja(adam, 'formatting', PON, godzin=3)
    _sesja(adam, 'edges', PON, godzin=1, od=time(12, 0))
    _sesja(ewa, 'edges', PON, godzin=4)
    _sesja(ola, 'packaging', PON, godzin=2)                                  # sesja bez żadnej pracy
    return adam, ewa, ola


def test_pracownicy_jak_raport_wydajnosci(app, client, tablet):
    adam, ewa, ola = _dane_pracownikow()

    dane = _ok(client, tablet, '/reports/workers', start_date='2026-08-10', end_date='2026-08-11')
    raport = worker_stats_service.raport_wydajnosci(PON, PON + timedelta(days=1))

    assert dane['start_date'] == '2026-08-10' and dane['end_date'] == '2026-08-11' and dane['station'] is None
    assert len(dane['pracownicy']) == len(raport['worker_totals']) == 3
    for wzor in raport['worker_totals']:
        w = next(x for x in dane['pracownicy'] if x['id'] == wzor['worker_id'])
        assert w['nazwa'] == wzor['worker_name']
        assert w['sztuki'] == wzor['pieces']
        assert w['m3'] == wzor['m3']
        assert w['godziny'] == wzor['hours']
        assert w['tempo_m3_h'] == wzor['pace_m3_per_hour']
    # Liczby, a nie tylko zgodność z wzorem (inaczej zera pasowałyby do zer).
    assert _wiersz(dane, adam)['sztuki'] == 5.5 and _wiersz(dane, adam)['m3'] == 2.75
    assert _wiersz(dane, adam)['godziny'] == 4.0
    assert _wiersz(dane, adam)['tempo_m3_h'] == pytest.approx(2.75 / 4, abs=1e-3)
    assert _wiersz(dane, ewa)['sztuki'] == 3.5 and _wiersz(dane, ewa)['m3'] == pytest.approx(1.25)
    # Praca zespołowa to ułamki: dwie osoby przy jednym zdarzeniu (3 szt.) dostają po 1,5.
    assert dane['nieprzypisane'] == {'sztuki': 5.0, 'm3': 1.25}
    pod = dane['podsumowanie']
    assert pod['osoby'] == 3 and pod['godziny'] == raport['summary']['hours']
    assert pod['sztuki'] == raport['summary']['pieces'] and pod['m3'] == raport['summary']['m3']
    assert pod['pokrycie_atrybucji_proc'] == raport['summary']['attribution_coverage_pct']


def test_pracownicy_stanowiska_i_wg_stanowisk(app, client, tablet):
    adam, ewa, ola = _dane_pracownikow()

    dane = _ok(client, tablet, '/reports/workers', start_date='2026-08-10', end_date='2026-08-11')

    w = _wiersz(dane, adam)
    assert w['stanowiska'] == ['formatting', 'edges']              # kody, w kolejności procesu
    assert w['wg_stanowisk'] == [{'stanowisko': 'formatting', 'sztuki': 4.0, 'm3': 2.0},
                                 {'stanowisko': 'edges', 'sztuki': 1.5, 'm3': 0.75}]
    assert _wiersz(dane, ewa)['stanowiska'] == ['edges']
    # Ola miała tylko sesję: jest na liście (to odpowiedź na „kto stoi bezczynnie"), bez pracy i bez tempa.
    o = _wiersz(dane, ola)
    assert (o['sztuki'], o['m3'], o['godziny'], o['tempo_m3_h'], o['stanowiska'], o['wg_stanowisk']) == \
        (0, 0, 2.0, None, [], [])


def test_pracownicy_filtr_stanowiska(app, client, tablet):
    adam, ewa, ola = _dane_pracownikow()

    dane = _ok(client, tablet, '/reports/workers', start_date='2026-08-10', end_date='2026-08-11', station='edges')

    assert dane['station'] == 'edges'
    assert _wiersz(dane, adam)['wg_stanowisk'] == [{'stanowisko': 'edges', 'sztuki': 1.5, 'm3': 0.75}]
    assert _wiersz(dane, adam)['godziny'] == 1.0                    # tylko sesje na tym stanowisku
    assert _wiersz(dane, adam)['tempo_m3_h'] == 0.75
    assert dane['nieprzypisane'] == {'sztuki': 0.0, 'm3': 0.0}      # praca nieprzypisana była na sklejaniu


@pytest.mark.parametrize('stanowisko', ['nieznane', 'sawmill', 'manager', 'all'])
def test_pracownicy_zle_stanowisko_400(app, client, tablet, stanowisko):
    r = _get(client, tablet, '/reports/workers', station=stanowisko)
    assert r.status_code == 400
    assert r.get_json()['error'] == 'dane_niepoprawne'


def test_pracownicy_puste_stanowisko_to_brak_filtra(app, client, tablet):
    assert _ok(client, tablet, '/reports/workers', station='')['station'] is None


def test_sesja_kierownika_nie_obniza_tempa(app, client, tablet):
    """Obecność (`godziny`) liczy wszystkie sesje, mianownik tempa tylko sesje stanowisk procesu."""
    adam = _pracownik('Adam')
    _zdarzenie(_poz(volume=0.5), 'formatting', 2, _o(PON, 9), kto=[adam])      # 1,0 m³
    _sesja(adam, 'formatting', PON, godzin=2)
    _sesja(adam, 'manager', PON, godzin=2, od=time(12, 0))

    dane = _ok(client, tablet, '/reports/workers', start_date='2026-08-10', end_date='2026-08-10')
    w = _wiersz(dane, adam)

    assert w['m3'] == 1.0
    assert w['godziny'] == 4.0
    assert w['tempo_m3_h'] == 0.5                   # 1,0 m³ / 2 h na formatowaniu, a nie / 4 h
    # Parytet: ta sama liczba w panelu (raport_wydajnosci) i w XLSX raportu dziennego.
    raport = worker_stats_service.raport_wydajnosci(PON, PON)
    assert raport['worker_totals'][0]['pace_m3_per_hour'] == 0.5 and raport['worker_totals'][0]['hours'] == 4.0
    assert daily_report_service._ludzie(PON)['wiersze'][0]['tempo'] == 0.5
    assert daily_report_service._ludzie(PON)['wiersze'][0]['godziny'] == 4.0


def test_sesja_trakowni_nie_obniza_tempa(app, client, tablet):
    adam = _pracownik('Adam')
    _zdarzenie(_poz(volume=0.5), 'formatting', 2, _o(PON, 9), kto=[adam])
    _sesja(adam, 'formatting', PON, godzin=2)
    _sesja(adam, 'sawmill', PON, godzin=6, od=time(12, 0))

    w = _wiersz(_ok(client, tablet, '/reports/workers', start_date='2026-08-10', end_date='2026-08-10'), adam)

    assert w['godziny'] == 8.0 and w['tempo_m3_h'] == 0.5


def test_tempo_null_gdy_pracownik_ma_tylko_sesje_poza_procesem(app, client, tablet):
    """Praca przypisana, ale ani minuty na stanowisku procesu: nie ma czym dzielić, więc null (nie zero, nie błąd)."""
    adam = _pracownik('Adam')
    _zdarzenie(_poz(), 'formatting', 2, _o(PON, 9), kto=[adam])
    _sesja(adam, 'manager', PON, godzin=3)

    w = _wiersz(_ok(client, tablet, '/reports/workers', start_date='2026-08-10', end_date='2026-08-10'), adam)

    assert w['m3'] > 0 and w['godziny'] == 3.0 and w['tempo_m3_h'] is None


def test_tempo_null_bez_atrybucji(app, client, tablet):
    """Zero przy nazwisku człowieka, o którym raport nic nie wie, byłoby zarzutem bezczynności z braku danych."""
    adam = _pracownik('Adam')
    _sesja(adam, 'formatting', PON, godzin=8)

    w = _wiersz(_ok(client, tablet, '/reports/workers', start_date='2026-08-10', end_date='2026-08-10'), adam)

    assert w['godziny'] == 8.0 and w['sztuki'] == 0 and w['tempo_m3_h'] is None


def test_otwarta_sesja(app, client, tablet):
    dzis = get_local_now().date()
    otwarta, zamknieta = _pracownik('Otwarty'), _pracownik('Zamkniety')
    _sesja(otwarta, 'formatting', dzis, otwarta=True, od=time(0, 1))
    _sesja(zamknieta, 'formatting', dzis, godzin=1, od=time(0, 1))

    dane = _ok(client, tablet, '/reports/workers', start_date=dzis.isoformat(), end_date=dzis.isoformat())

    assert _wiersz(dane, otwarta)['otwarta_sesja'] is True
    assert _wiersz(dane, zamknieta)['otwarta_sesja'] is False


def test_pracownicy_bez_pracy_same_zera(app, client, tablet):
    dane = _ok(client, tablet, '/reports/workers', start_date='2026-08-10', end_date='2026-08-16')

    assert dane['pracownicy'] == []
    assert dane['nieprzypisane'] == {'sztuki': 0.0, 'm3': 0.0}
    assert dane['podsumowanie']['osoby'] == 0 and dane['podsumowanie']['godziny'] == 0
    assert dane['podsumowanie']['sztuki'] == 0 and dane['podsumowanie']['m3'] == 0


def test_obsada_vs_przerob_manager_poza_procesem(app, tablet):
    """
    Wykres „Obsada vs przerób" traktuje `manager` jak trakownię: wiersz jest (obecność), ale `in_pipeline` False,
    więc bez tempa m³/h. `in_pipeline` wynika z przynależności do STATION_ORDER, nie z listy na sztywno.
    """
    adam = _pracownik('Adam')
    _sesja(adam, 'manager', PON, godzin=3)
    _sesja(adam, 'sawmill', PON, godzin=2, od=time(12, 0))
    _sesja(adam, 'formatting', PON, godzin=1, od=time(15, 0))
    _zdarzenie(_poz(), 'formatting', 2, _o(PON, 15), kto=[adam])

    wynik = reports_service.obsada_vs_przerob(PON, PON)
    wiersze = {w['station_code']: w for w in wynik['rows']}

    assert wiersze['manager']['in_pipeline'] is False
    assert wiersze['manager']['person_hours'] == 3.0
    assert wiersze['manager']['m3_per_person_hour'] is None
    assert wiersze['sawmill']['in_pipeline'] is False         # wzorzec, z którym manager ma się zgadzać
    assert wiersze['formatting']['in_pipeline'] is True
    assert wiersze['formatting']['m3_per_person_hour'] is not None
    assert 'manager' not in STATION_ORDER


# ── dzień po dniu (§8.7) ─────────────────────────────────────────────────────────────────────────────────────

def test_dzien_po_dniu_kazdy_dzien_i_7_kluczy(app, client, tablet):
    p = _poz(volume=0.5)
    sr = PON + timedelta(days=1)
    _zdarzenie(p, 'cutting', 4, _o(sr, 8))                          # 2,0 m³
    _zdarzenie(p, 'formatting', 6, _o(sr, 9))                       # 3,0 m³
    _zdarzenie(p, 'formatting', -2, _o(sr, 15))                     # cofnięcie: netto 4 szt., 2,0 m³
    _zdarzenie(p, 'packaging', 2, _o(sr, 16))                       # 1,0 m³ zakończone
    _zdarzenie(p, 'edges', 9, _o(sr, 11), source='auto_skip')       # automat: nie liczy się

    dane = _ok(client, tablet, '/reports/daily', start_date='2026-08-10', end_date='2026-08-12')

    assert dane['start_date'] == '2026-08-10' and dane['end_date'] == '2026-08-12'
    assert [d['data'] for d in dane['dni']] == ['2026-08-10', '2026-08-11', '2026-08-12']
    for dzien in dane['dni']:
        assert set(dzien['stanowiska']) == set(STATION_ORDER)         # klucze wszystkich 7 stanowisk
    for brzeg in (dane['dni'][0], dane['dni'][2]):
        assert brzeg['sztuki'] == 0 and brzeg['m3'] == 0 and brzeg['zakonczone_m3'] == 0
        assert all(v == {'sztuki': 0, 'm3': 0} for v in brzeg['stanowiska'].values())
    srodek = dane['dni'][1]
    assert srodek['stanowiska']['cutting'] == {'sztuki': 4, 'm3': 2.0}
    assert srodek['stanowiska']['formatting'] == {'sztuki': 4, 'm3': 2.0}
    assert srodek['stanowiska']['edges'] == {'sztuki': 0, 'm3': 0}
    assert srodek['sztuki'] == 4 + 4 + 2 and srodek['m3'] == 5.0
    assert srodek['zakonczone_m3'] == 1.0


def test_dzien_po_dniu_jak_get_station_work_per_day(app, client, tablet):
    from modules.production.services.station_events_service import get_station_work_per_day

    p = _poz(volume=0.25)
    for i in range(4):
        _zdarzenie(p, STATION_ORDER[i], i + 1, _o(PON + timedelta(days=i), 9))

    dane = _ok(client, tablet, '/reports/daily', start_date='2026-08-10', end_date='2026-08-13')

    for kod in STATION_ORDER:
        wzor = get_station_work_per_day(kod, PON, PON + timedelta(days=3))
        for dzien in dane['dni']:
            oczekiwane = wzor.get(date.fromisoformat(dzien['data']), {'pieces': 0, 'm3': 0.0})
            assert dzien['stanowiska'][kod]['sztuki'] == oczekiwane['pieces']
            assert dzien['stanowiska'][kod]['m3'] == pytest.approx(oczekiwane['m3'], abs=1e-4)
    assert sum(d['sztuki'] for d in dane['dni']) == 1 + 2 + 3 + 4


def test_dzien_po_dniu_zakres_92_dni_i_domyslnie_dzis(app, client, tablet):
    pierwszy = date(2026, 6, 1)
    dane = _ok(client, tablet, '/reports/daily', start_date=pierwszy.isoformat(),
               end_date=(pierwszy + timedelta(days=91)).isoformat())
    assert len(dane['dni']) == 92 and dane['dni'][0]['data'] == '2026-06-01' and dane['dni'][-1]['data'] == '2026-08-31'
    assert all(d['sztuki'] == 0 and d['m3'] == 0 for d in dane['dni'])

    dzis = get_local_now().date().isoformat()
    dane = _ok(client, tablet, '/reports/daily')
    assert dane['start_date'] == dane['end_date'] == dzis and [d['data'] for d in dane['dni']] == [dzis]


def test_dzien_po_dniu_serwis_jednostkowo(app):
    assert [d['data'] for d in raporty.dzien_po_dniu(PON, PON)['dni']] == ['2026-08-10']


# ── bez pieniędzy ────────────────────────────────────────────────────────────────────────────────────────────

def test_raporty_bez_wartosci(app, client, tablet):
    _dane_pracownikow()
    for sciezka in ('/reports/workers', '/reports/daily'):
        r = _get(client, tablet, sciezka, start_date='2026-08-10', end_date='2026-08-11')
        assert r.status_code == 200
        assert biala_lista.zakazane_w(r.get_json()) == [], sciezka
        tekst = r.get_data(as_text=True)
        assert 'wartosc' not in tekst and 'value_net' not in tekst, sciezka
    # Wartość pozycji (1000 zł) siedzi w bazie, a serwis przerobu ją liczy — DTO nie ma jej wydać.
    assert worker_stats_service.raport_wydajnosci(PON, PON)['summary']['pieces'] > 0


# ── m2 Lakierni (§8.6) ───────────────────────────────────────────────────────────────────────────────────────

def _blat_lakierni(wykonczenie, dlugosc, szerokosc, ilosc=2, grubosc=4):
    p = _poz(quantity=ilosc)
    p.parsed_finish_type = wykonczenie
    p.parsed_length_cm, p.parsed_width_cm, p.parsed_thickness_cm = dlugosc, szerokosc, grubosc
    db.session.commit()
    return p


def test_m2_lakierni_tylko_dla_pracownika_z_praca_na_lakierni(app, client, tablet):
    lakiernik, formatowacz = _pracownik('Lakiernik'), _pracownik('Formatowacz')
    # 200x60x4 cm: 2,608 m2 na sztukę (x2 = 5,216); 100x100x4 cm: 2,16 m2 na sztukę.
    _zdarzenie(_blat_lakierni('olejowane', 200, 60), 'painting', 2, _o(PON, 9), kto=[lakiernik])
    _zdarzenie(_blat_lakierni('lakierowane', 100, 100), 'painting', 1, _o(PON, 10), kto=[lakiernik])
    _zdarzenie(_blat_lakierni('lakierowane', 100, 100), 'formatting', 1, _o(PON, 11), kto=[formatowacz])

    dane = _ok(client, tablet, '/reports/workers', start_date='2026-08-10', end_date='2026-08-10')

    assert _wiersz(dane, lakiernik)['m2'] == {'olejowane': 5.216, 'lakierowane': 2.16}
    assert 'm2' not in _wiersz(dane, formatowacz)
    raport = worker_stats_service.raport_wydajnosci(PON, PON)
    wzor = next(w for w in raport['worker_totals'] if w['worker_id'] == lakiernik.id)['painting_m2']
    assert wzor == {'oiled': 5.216, 'lacquered': 2.16}


def test_m2_brak_klucza_gdy_nikt_nie_pracowal_na_lakierni(app, client, tablet):
    adam = _pracownik('Adam')
    _zdarzenie(_poz(), 'formatting', 2, _o(PON, 9), kto=[adam])
    _sesja(_pracownik('Bez pracy'), 'painting', PON)       # sesja na Lakierni bez pracy: bez m2

    dane = _ok(client, tablet, '/reports/workers', start_date='2026-08-10', end_date='2026-08-10')

    assert all('m2' not in w for w in dane['pracownicy'])
