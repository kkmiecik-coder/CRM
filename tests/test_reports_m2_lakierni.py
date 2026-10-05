# tests/test_reports_m2_lakierni.py
"""
m2 (olejowane / lakierowane) na stanowisku Lakiernia w Raportach produkcji.

Lakiernia mierzy robotę także w powierzchni, nie tylko w m3. Powierzchnia
jednej sztuki to PEŁNA powierzchnia: góra + dół + 4 boki, czyli
2·(dł·szer + dł·gr + szer·gr) z wymiarów produktu. Inne stanowiska m2 nie
dostają — to zakładka o lakierni, nie o całej hali.

Wymiary testowe (grubość 4 cm): 200×60 = 2.608 m2 na sztukę,
100×50 = 1.12 m2, 100×100 = 2.16 m2.
"""

import os
import sys
from datetime import datetime, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from modules.production.models import (
    ProductionOrder, ProductionProduct, ProductionStationEvent,
    ProductionStationEventWorker, ProductionWorker,
)
from modules.production.services import reports_service, worker_stats_service

# Fixture'y (app, client, zalogowany) i stałe — te same co w teście aliasu
# krawędzi: ta sama aplikacja testowa z zarejestrowanym blueprintem API.
from tests.test_reports_alias_krawedzi import (  # noqa: F401
    BASE, PONIEDZIALEK, ZAKRES, app, client, zalogowany,
)

_licznik = [0]


def _blat(wykonczenie, dlugosc, szerokosc, ilosc=2, grubosc=4):
    """Pozycja o znanej powierzchni; objętość dowolna (nie wchodzi do m2)."""
    _licznik[0] += 1
    numer = _licznik[0]
    order = ProductionOrder(baselinker_order_id=numer,
                            internal_order_number=f'26/{numer:05d}',
                            client_name='Klient Testowy')
    db.session.add(order)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=order.id, short_product_id=f'26{numer:03d}_1',
        product_sequence_in_order=1, original_product_name='Blat',
        quantity=ilosc, volume_m3=0.1, current_status='czeka_na_lakiernie',
        parsed_length_cm=dlugosc, parsed_width_cm=szerokosc,
        parsed_thickness_cm=grubosc,
        parsed_finish_type=wykonczenie,
        created_at=datetime.combine(PONIEDZIALEK, time(9, 0)))
    db.session.add(produkt)
    db.session.commit()
    return produkt


def _event(produkt, stanowisko, delta, pracownik=None, ilosc_po=None):
    ev = ProductionStationEvent(
        production_item_id=produkt.id, station_code=stanowisko, delta=delta,
        quantity_done_after=delta if ilosc_po is None else ilosc_po,
        source='mobile', created_at=datetime.combine(PONIEDZIALEK, time(10, 0)))
    db.session.add(ev)
    db.session.flush()
    if pracownik is not None:
        db.session.add(ProductionStationEventWorker(
            event_id=ev.id, worker_id=pracownik.id, share=1.0))
    db.session.commit()
    return ev


def _pracownik():
    w = ProductionWorker(first_name='Adam', last_name='Nowak')
    db.session.add(w)
    db.session.commit()
    return w


def test_powierzchnia_sztuki_to_gora_dol_i_cztery_boki():
    """Sześcian 10 cm ma 6 ścian po 100 cm2 = 0.06 m2; płyta 100×100×2 to 2.08 m2."""
    from modules.production.services.worker_stats_service import (
        powierzchnia_sztuki_m2)

    assert powierzchnia_sztuki_m2(10, 10, 10) == 0.06
    assert powierzchnia_sztuki_m2(100, 100, 2) == 2.08
    # Brak grubości nie wywala liczenia (zostaje góra + dół).
    assert powierzchnia_sztuki_m2(100, 50, None) == 1.0


def test_m2_liczy_pelna_powierzchnie_sztuki(app):
    """200×60×4 cm = 2.608 m2 na sztukę (2 szt. olejowane = 5.216); 100×50×4 = 1.12."""
    with app.app_context():
        olej = _blat('olejowane', 200, 60)
        lakier = _blat('lakierowane', 100, 50, ilosc=1)
        _event(olej, 'painting', 2)
        _event(lakier, 'painting', 1)

        wynik = reports_service.dni_zapasu_stanowisk(end_date=PONIEDZIALEK)
        lakiernia = next(s for s in wynik['stations']
                         if s['station_code'] == 'painting')

        # kolejka = całe pozycje czekające (quantity), okno = netto zdarzeń
        assert lakiernia['pending_m2'] == {'oiled': 5.216, 'lacquered': 1.12}
        assert lakiernia['window_m2'] == {'oiled': 5.216, 'lacquered': 1.12}


def test_dni_zapasu_tylko_lakiernia_ma_m2(app):
    with app.app_context():
        _event(_blat('olejowane', 100, 100), 'gluing', 1)

        wynik = reports_service.dni_zapasu_stanowisk(end_date=PONIEDZIALEK)

        for s in wynik['stations']:
            assert ('pending_m2' in s) == (s['station_code'] == 'painting')


def test_wklad_lakierni_ma_m2_osob_i_stanowiska_a_bez_podpisu_to_roznica(app):
    with app.app_context():
        adam = _pracownik()
        _event(_blat('olejowane', 200, 60), 'painting', 2, pracownik=adam)
        _event(_blat('lakierowane', 100, 100), 'painting', 1)  # bez podpisu

        wynik = reports_service.wklad_pracownikow_na_stanowisku(
            'painting', PONIEDZIALEK, PONIEDZIALEK)

        assert wynik['summary']['station_m2'] == {'oiled': 5.216, 'lacquered': 2.16}
        assert wynik['workers'][0]['m2'] == {'oiled': 5.216, 'lacquered': 0.0}
        assert wynik['unassigned']['m2'] == {'oiled': 0.0, 'lacquered': 2.16}


def test_wklad_innego_stanowiska_nie_ma_m2(app):
    with app.app_context():
        adam = _pracownik()
        _event(_blat('olejowane', 200, 60), 'gluing', 2, pracownik=adam)

        wynik = reports_service.wklad_pracownikow_na_stanowisku(
            'gluing', PONIEDZIALEK, PONIEDZIALEK)

        assert 'station_m2' not in wynik['summary']
        assert 'm2' not in wynik['workers'][0]
        assert 'm2' not in wynik['unassigned']


def test_obsada_vs_przerob_m2_tylko_w_wierszu_lakierni(app):
    with app.app_context():
        _event(_blat('olejowane', 200, 60), 'painting', 2)
        _event(_blat('lakierowane', 100, 100), 'gluing', 1)

        wynik = reports_service.obsada_vs_przerob(PONIEDZIALEK, PONIEDZIALEK)
        wiersze = {w['station_code']: w for w in wynik['rows']}

        assert wiersze['painting']['m2'] == {'oiled': 5.216, 'lacquered': 0.0}
        assert 'm2' not in wiersze['gluing']


def test_raport_pracownikow_liczy_m2_lakierni_na_osobe_i_w_sumie(app):
    with app.app_context():
        adam = _pracownik()
        _event(_blat('olejowane', 200, 60), 'painting', 2, pracownik=adam)
        _event(_blat('lakierowane', 100, 100), 'gluing', 1, pracownik=adam)
        _event(_blat('lakierowane', 100, 100), 'painting', 1)  # bez podpisu

        raport = worker_stats_service.raport_wydajnosci(
            PONIEDZIALEK, PONIEDZIALEK)

        # sklejanie nie wlicza się do m2 lakierni
        assert raport['worker_totals'][0]['painting_m2'] == {
            'oiled': 5.216, 'lacquered': 0.0}
        assert raport['summary']['painting_m2'] == {
            'oiled': 5.216, 'lacquered': 0.0}
        assert raport['summary']['unassigned_painting_m2'] == {
            'oiled': 0.0, 'lacquered': 2.16}
        assert raport['daily_totals'][0]['painting_m2'] == {
            'oiled': 5.216, 'lacquered': 2.16}
        wiersze_lakierni = [w for w in raport['rows'] if 'm2' in w]
        assert [w['station_code'] for w in wiersze_lakierni] == ['painting']


def test_wykonanie_stanowiska_lakiernia_ma_stan_m2_i_m2_w_wierszach(
        app, client, zalogowany):
    with app.app_context():
        olej = _blat('olejowane', 200, 60, ilosc=5)
        # 3 z 5 sztuk gotowe po ostatnim evencie: stan EOD = 3 × 2.608 m2
        _event(olej, 'painting', 3, ilosc_po=3)
        lakier = _blat('lakierowane', 100, 50, ilosc=1)
        _event(lakier, 'painting', 1, ilosc_po=1)

    odp = client.get(f'{BASE}/reports/station-output?station=painting&{ZAKRES}')

    assert odp.status_code == 200, odp.get_json()
    dane = odp.get_json()
    assert dane['summary']['painting_done_eod_m2'] == {
        'oiled': 7.824, 'lacquered': 1.12}
    po_typie = {p['finish_type']: p['area_done_eod_m2'] for p in dane['items']}
    assert po_typie == {'olejowane': 7.824, 'lakierowane': 1.12}


def test_wykonanie_innego_stanowiska_nie_ma_stanu_m2(app, client, zalogowany):
    with app.app_context():
        _event(_blat('olejowane', 200, 60), 'gluing', 2)

    for stanowisko in ('gluing', 'all'):
        odp = client.get(
            f'{BASE}/reports/station-output?station={stanowisko}&{ZAKRES}')
        assert odp.status_code == 200, odp.get_json()
        assert odp.get_json()['summary']['painting_done_eod_m2'] is None
