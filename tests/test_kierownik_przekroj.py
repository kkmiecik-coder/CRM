# -*- coding: utf-8 -*-
"""Testy przekrojowe tabletu kierownika hali (/api/mobile/manager/*): każda trasa blueprintu przechodzi przez te same
trzy kontrole, więc parametryzujemy je listą `ENDPOINTY_KIEROWNIKA`. Nowa trasa dopisana do listy (a bez tego
`test_lista_endpointow_jest_pelna` się wywróci) dostaje bramkę i kontrolę zakazanych kluczy bez ani jednej linii
w tym pliku.

Szczegóły poszczególnych tras mają własne pliki `test_kierownik_*.py`; tu tylko to, co dotyczy WSZYSTKICH."""
import json
from datetime import datetime, time, timedelta

import pytest

from extensions import db
from modules.production.kierownik.services import biala_lista
from modules.production.logistics.models import OrderGeo
from modules.production.models import (
    ProcessedMobileOperation, ProductionConfig, ProductionDevice, ProductionProductEvent, ProductionStationEvent,
    ProductionStationEventWorker, ProductionWorker, ProductionWorkerSession, get_local_now,
)
from modules.production.priorytety.models import PriorityLog, StationDesk
from modules.production.sawmill.models import (
    STATUS_COMPLETED, SawmillAudit, SawmillCounter, SawmillDelivery, SawmillLog, SawmillOrder, SawmillSpecies,
    SawmillSupplier,
)
from modules.production.sawmill.services.orders import add_log
from tests.dostawa_pomocnicze import T0, trasa, zamowienie_z_paczkami
from tests.kierownik_pomocnicze import API, ENDPOINTY_KIEROWNIKA, naglowki, tablet_kierownika
from tests.logistyka_fixtures import app, client, zamowienie  # noqa: F401
from tests.priorytety_fixtures import czyste_ustawienia, drabina_domyslna, zamrozony_dzien  # noqa: F401

pytestmark = pytest.mark.usefixtures('czyste_ustawienia', 'zamrozony_dzien')

TABELE_DODATKOWE = [m.__table__ for m in (
    ProductionProductEvent, ProductionStationEventWorker, SawmillSupplier, SawmillSpecies, SawmillCounter,
    SawmillDelivery, SawmillOrder, SawmillLog, SawmillAudit)]

GET_Y = [e for e in ENDPOINTY_KIEROWNIKA if e[0] == 'GET']
IDS_TRAS = ['%s %s' % e for e in ENDPOINTY_KIEROWNIKA]
IDS_GET = ['%s %s' % e for e in GET_Y]


@pytest.fixture(autouse=True)
def _zamrozony_zegar(zegar):
    """Zegar aplikacji zatrzymany na dziś, 12:00. Wszystkie daty zasiewu liczymy od niego (dziś, wczoraj), więc żadne
    okno odczytu (sesje „dziś”, 90 dni trakowni, 30 dni tras) nie wypchnie danych, a doba nie zmieni się w trakcie
    testu."""
    zegar()


class Dane(object):
    """Identyfikatory zasianych obiektów, do podstawienia w ścieżkach."""


def _zasiej_baze(z_zakazanymi=True):
    """
    Baza, na której każda trasa ma co zwrócić. Przy `z_zakazanymi` wszystkie pola, których kierownik widzieć nie
    może (kontakt, adres, ceny, wartości, notatka rozliczenia), są wypełnione — gdyby jakiś serializator je
    przepuścił, `zakazane_w` albo szukanie wartości w tekście odpowiedzi to wychwyci.
    """
    db.metadata.create_all(bind=db.engine, tables=TABELE_DODATKOWE)
    db.session.add(ProductionConfig(config_key='sawmill_settings', config_type='json', config_value=json.dumps(
        {'min_diameter_cm': 15.0, 'max_diameter_cm': 250.0, 'min_length_cm': 30.0, 'max_length_cm': 20000.0,
         'decimal_places': 1, 'deviation_threshold_pct': 3.0})))
    db.session.commit()
    drabina_domyslna()
    d = Dane()
    d.dzis = get_local_now().date()
    d.wczoraj = d.dzis - timedelta(days=1)

    # Zamówienie na stanowiskach (z danymi klienta i pieniędzmi), kafel na stole, historia pozycji.
    kolumny = dict(client_email='tajny@klient.pl', client_phone='600700800', shipping_price=45.5,
                   delivery_company='Firma') if z_zakazanymi else {}
    d.zamowienie = zamowienie('transport_woodpower', statusy=('czeka_na_formatowanie', 'czeka_na_lakiernie'),
                              numer_wewnetrzny='26/00777', bl_id=977777, **kolumny)
    d.pozycja = d.zamowienie.products[0]
    if z_zakazanymi:
        for p in d.zamowienie.products:
            p.total_value_net = 1234.56
            p.unit_price_net = 617.28
    # Formatowanie pracuje zamówieniami, więc kafel to `o:<zamówienie>`.
    db.session.add(StationDesk(station_code='formatting', order_id=d.zamowienie.id, product_id=None,
                               unit_key='o:%d' % d.zamowienie.id, pulled_at=datetime.combine(d.dzis, time(7, 0)),
                               zrodlo='kolejka'))
    db.session.add(ProductionProductEvent(
        production_item_id=d.pozycja.id, event_type='status_change', old_value='czeka_na_wyciecie',
        new_value='czeka_na_formatowanie', actor_type='system', source='system',
        created_at=datetime.combine(d.dzis, time(9, 0, 0))))

    # Pracownik na stanowisku (sesja otwarta) i jego przerób w zakresie raportów.
    pracownik = ProductionWorker(first_name='Adam', last_name='Kowalczyk', is_active=True)
    db.session.add(pracownik)
    db.session.flush()
    d.pracownik = pracownik
    start = datetime.combine(d.dzis, time(8, 0))
    db.session.add(ProductionWorkerSession(
        worker_id=pracownik.id, station_code='formatting', session_group='przekroj', started_at=start,
        last_activity_at=start, work_date=d.dzis))
    zdarzenie = ProductionStationEvent(production_item_id=d.pozycja.id, station_code='formatting', delta=2,
                                       quantity_done_after=2, created_at=datetime.combine(d.dzis, time(10, 0)),
                                       source='mobile')
    db.session.add(zdarzenie)
    db.session.flush()
    db.session.add(ProductionStationEventWorker(event_id=zdarzenie.id, worker_id=pracownik.id, share=1.0))
    db.session.commit()

    # Trasa z przystankiem (adres, telefon i e-mail w zamówieniu) i punktem na mapie.
    dostarczane, _paczki = zamowienie_z_paczkami(**kolumny)
    db.session.add(OrderGeo(order_id=dostarczane.id, lat=50.06, lng=19.94, source='gugik', quality='dokladna',
                            address_hash='x' * 40))
    db.session.commit()
    d.trasa = trasa([dostarczane], status='zatwierdzona', approved_at=T0)

    # Zlecenie trakowni z ceną, wartością deklaracji i notatką rozliczenia.
    dostawca = SawmillSupplier(name='Tartak Leśny s.c.')
    gatunek = SawmillSpecies(name='Dąb', short_code='DB', sort_order=10)
    db.session.add_all([dostawca, gatunek])
    db.session.flush()
    dostawa = SawmillDelivery(supplier_id=dostawca.id, delivery_date=d.wczoraj, invoice_number='FV 1/08/2026')
    db.session.add(dostawa)
    db.session.flush()
    zlecenie = SawmillOrder(
        order_number='TRK/2026/777', delivery_id=dostawa.id, species_id=gatunek.id, declared_volume_m3=12.5,
        declared_logs_count=3, price_per_m3=1234.56 if z_zakazanymi else None,
        declared_value=15432.0 if z_zakazanymi else None,
        settlement_notes='TAJNA-NOTATKA-ROZLICZENIA' if z_zakazanymi else None)
    db.session.add(zlecenie)
    db.session.flush()
    for i in range(3):
        add_log(zlecenie, {'mid_diameter_cm': 40, 'length_cm': 260}, datetime.combine(d.dzis, time(7, 30 + i, 0)),
                device_id='TRAK-1', worker_id=pracownik.id)
    zlecenie.status = STATUS_COMPLETED
    db.session.commit()
    d.zlecenie = zlecenie
    return d


def _sciezka(wzor, d):
    """Wzór reguły Flaska z ENDPOINTY_KIEROWNIKA → ścieżka na zasianych obiektach."""
    id_zamowienia = d.zlecenie.id if wzor.startswith('/sawmill/') else d.zamowienie.id
    return (wzor.replace('<int:order_id>', str(id_zamowienia)).replace('<int:product_id>', str(d.pozycja.id))
            .replace('<int:route_id>', str(d.trasa.id)).replace('<kod>', 'formatting'))


def _dobre_cialo(metoda, wzor, d):
    """Poprawne ciało zapisu: odmowa z bramki jest wtedy jedyną możliwą przyczyną (wzór: test_dostawa_api)."""
    if metoda == 'GET':
        return None
    if wzor == '/products/status':
        return {'product_ids': [d.pozycja.id], 'status': 'czeka_na_lakiernie'}
    if wzor == '/stations/<kod>/desk':
        return {'order_id': d.zamowienie.id}
    if wzor == '/stations/<kod>/desk/remove':
        return {'unit_key': 'o:%d' % d.zamowienie.id}
    raise AssertionError('Dopisz poprawne ciało zapisu dla %s %s w _dobre_cialo' % (metoda, wzor))


def _zapytanie(metoda, wzor, d):
    parametry = {'start_date': d.wczoraj.isoformat(), 'end_date': d.dzis.isoformat()} if wzor.startswith('/reports/') else {}
    return dict(method=metoda, path=API + _sciezka(wzor, d), json=_dobre_cialo(metoda, wzor, d),
                query_string=parametry)


def _wyslij(client, naglowek, zapytanie):
    return client.open(zapytanie['path'], method=zapytanie['method'], headers=naglowek, json=zapytanie['json'],
                       query_string=zapytanie['query_string'])


# --- lista tras ---------------------------------------------------------------------------------------------------

def test_lista_endpointow_jest_pelna(app):
    """Szesnaście tras blueprintu == `ENDPOINTY_KIEROWNIKA`; dopisanie trasy bez wpisu na listę (albo odwrotnie)
    wywraca ten test, więc parametryzowane testy niżej nie mogą jej pominąć."""
    reguly = {(metoda, r.rule[len(API):]) for r in app.url_map.iter_rules() if r.rule.startswith(API + '/')
              for metoda in r.methods - {'HEAD', 'OPTIONS'}}
    assert reguly == set(ENDPOINTY_KIEROWNIKA)
    assert len(ENDPOINTY_KIEROWNIKA) == len(set(ENDPOINTY_KIEROWNIKA)) == 16
    assert sum(1 for e in ENDPOINTY_KIEROWNIKA if e[0] == 'POST') == 3


# --- bramka każdego endpointu -------------------------------------------------------------------------------------

@pytest.mark.parametrize('metoda, wzor', ENDPOINTY_KIEROWNIKA, ids=IDS_TRAS)
def test_bramka_kazdego_endpointu(app, client, metoda, wzor):
    """Urządzenie innego stanowiska → 403 `station_not_allowed`; pracownik bez znacznika kierownika → 403
    `not_a_manager`; brak tokenu → 401. Ciało zapisu jest poprawne, więc odmowa pochodzi z bramki. Żaden zapis nie
    rusza bazy, a odmowa nie jest zapamiętana pod `X-Operation-Id`."""
    d = _zasiej_baze(z_zakazanymi=False)
    device, kierownik = tablet_kierownika()
    obcy = ProductionDevice(device_id='TAB-OBCY-PRZEKROJ', device_name='Weryfikacja', station_code='verification')
    zwykly = ProductionWorker(first_name='Piotr', last_name='Zwykły', is_active=True, is_manager=False)
    db.session.add_all([obcy, zwykly])
    db.session.commit()
    zapytanie = _zapytanie(metoda, wzor, d)
    status_pozycji = d.pozycja.current_status
    stol_przed = StationDesk.query.count()

    for naglowek, kod in ((naglowki(obcy, kierownik, op_id='op-przekroj-stanowisko'), 'station_not_allowed'),
                          (naglowki(device, zwykly, op_id='op-przekroj-zwykly'), 'not_a_manager')):
        r = _wyslij(client, naglowek, zapytanie)
        assert r.status_code == 403 and r.get_json()['error'] == kod, (metoda, wzor, kod, r.get_data()[:300])
        assert r.get_json()['message']
        assert ProcessedMobileOperation.query.get(naglowek['X-Operation-Id']) is None, (metoda, wzor, kod)

    r = _wyslij(client, {}, zapytanie)
    assert r.status_code == 401 and r.get_json()['error'] == 'missing_token', (metoda, wzor)

    db.session.expire_all()
    assert d.pozycja.current_status == status_pozycji
    assert StationDesk.query.count() == stol_przed and PriorityLog.query.count() == 0


# --- niepustość: odpowiedź musi zawierać zasiane dane --------------------------------------------------------------
# Test kluczy bez tego mógłby przechodzić na pustej odpowiedzi (okno dat, filtr, zły zasiew). Każdy GET ma tu
# sprawdzenie, czy w odpowiedzi jest to, co zasiał `_zasiej_baze`. Odczyt zwracający agregat sprawdza liczbę
# niezerową, którą wytworzył zasiew.

def _jest(lista, klucz, wartosc):
    return any(isinstance(e, dict) and e.get(klucz) == wartosc for e in lista)


def _wiersz(j, kod):
    return next((s for s in j['stanowiska'] if s['kod'] == kod), {})


OBECNOSC_ZASIEWU = {
    '/orders': lambda j, d: _jest(j['zamowienia'], 'order_id', d.zamowienie.id) and j['statystyki']['zamowien'] >= 1,
    '/orders/<int:order_id>': lambda j, d: (j['zamowienie']['order_id'] == d.zamowienie.id
                                             and len(j['zamowienie']['pozycje']) == 2
                                             and _jest(j['zamowienie']['na_stanowiskach'], 'unit_key',
                                                       'o:%d' % d.zamowienie.id)),
    '/products/<int:product_id>/history': lambda j, d: j['product_id'] == d.pozycja.id and len(j['historia']) >= 2,
    '/stations': lambda j, d: (_wiersz(j, 'formatting').get('statystyki', {}).get('oczekuje', 0) >= 1
                               and _wiersz(j, 'formatting').get('statystyki', {}).get('na_stole', 0) >= 1
                               and _jest(_wiersz(j, 'formatting').get('obsada', []), 'id', d.pracownik.id)),
    '/stations/<kod>': lambda j, d: (j['kod'] == 'formatting' and _jest(j['stol'], 'order_id', d.zamowienie.id)),
    '/workers/now': lambda j, d: (j['lacznie_osob'] >= 1
                                  and _jest(_wiersz(j, 'formatting').get('osoby', []), 'id', d.pracownik.id)),
    '/routes': lambda j, d: _jest(j['trasy'], 'id', d.trasa.id),
    '/routes/<int:route_id>': lambda j, d: j['trasa']['id'] == d.trasa.id and len(j['trasa']['przystanki']) == 1,
    '/sawmill/orders': lambda j, d: _jest(j['zlecenia'], 'id', d.zlecenie.id),
    '/sawmill/orders/<int:order_id>': lambda j, d: j['zlecenie']['id'] == d.zlecenie.id and len(j['klody']) == 3,
    '/reports/stations': lambda j, d: (_wiersz(j, 'formatting').get('sztuki', 0) >= 2 and j['hala']['sztuki'] >= 2),
    '/reports/workers': lambda j, d: any(w['id'] == d.pracownik.id and w['sztuki'] > 0 for w in j['pracownicy']),
    '/reports/daily': lambda j, d: any(x['sztuki'] > 0 for x in j['dni']),
}


def test_kazdy_get_ma_sprawdzenie_niepustosci():
    """Nowy odczyt dopisany do listy musi dostać tu sprawdzenie, inaczej jego kontrola kluczy byłaby bezwartościowa."""
    assert sorted(OBECNOSC_ZASIEWU) == sorted(wzor for _metoda, wzor in GET_Y)


@pytest.mark.parametrize('metoda, wzor', GET_Y, ids=IDS_GET)
def test_odpowiedz_zawiera_zasiane_dane(app, client, metoda, wzor):
    d = _zasiej_baze()
    device, kierownik = tablet_kierownika()
    r = _wyslij(client, naglowki(device, kierownik), _zapytanie(metoda, wzor, d))
    assert r.status_code == 200, (wzor, r.get_data()[:500])
    assert OBECNOSC_ZASIEWU[wzor](r.get_json(), d), (
        'Odpowiedź %s nie zawiera zasianych danych, więc test kluczy nic by nie sprawdzał: %s'
        % (wzor, r.get_data(as_text=True)[:800]))


# --- żadna odpowiedź nie niesie zakazanych kluczy -----------------------------------------------------------------

@pytest.mark.parametrize('metoda, wzor', GET_Y, ids=IDS_GET)
def test_zadna_odpowiedz_bez_zakazanych_kluczy(app, client, metoda, wzor):
    """Baza ma wypełnione wszystkie pola zakazane (kontakt, adres, ceny, wartości, notatka rozliczenia), a odpowiedź
    każdego odczytu: 200, bez kluczy z `ZAKAZANE_KLUCZE` na żadnym poziomie i bez ich wartości w tekście."""
    d = _zasiej_baze()
    device, kierownik = tablet_kierownika()
    # Straż testu: dane naprawdę siedzą w bazie, więc brak w odpowiedzi coś znaczy.
    assert d.zamowienie.client_email and d.zamowienie.client_phone and d.zamowienie.delivery_address
    assert d.zlecenie.price_per_m3 and d.zlecenie.settlement_notes and d.pozycja.total_value_net

    r = _wyslij(client, naglowki(device, kierownik), _zapytanie(metoda, wzor, d))

    assert r.status_code == 200, (wzor, r.get_data()[:500])
    assert OBECNOSC_ZASIEWU[wzor](r.get_json(), d), 'Pusta odpowiedź %s: kontrola kluczy byłaby pozorna' % wzor
    assert biala_lista.zakazane_w(r.get_json()) == [], wzor
    tekst = r.get_data(as_text=True)
    for sekret in ('tajny@klient.pl', '600700800', '1234.56', '617.28', '15432', 'TAJNA-NOTATKA-ROZLICZENIA',
                   'ul. Testowa'):
        assert sekret not in tekst, (wzor, sekret)

