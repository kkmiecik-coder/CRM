# -*- coding: utf-8 -*-
"""
Poprawki zakładki Logistyka po oględzinach właściciela (25.09.2026):
powrót do „Nie ustawiono”, nazwy stanowisk w kolumnie etapu, poprawka adresu
z wysyłką do Base. i lekki stan geokodera dla przycisku „Zlokalizuj teraz”.
"""
import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog
from modules.production.logistics.services import bl_sync, delivery, geocoding, lista
from modules.production.models import ProductionOrder
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401
from tests.test_logistyka_bl_sync import FakeBase


@pytest.fixture(autouse=True)
def bez_watkow(monkeypatch):
    uruchomione = []
    monkeypatch.setattr(geocoding, 'uruchom_w_tle', lambda app_: uruchomione.append('geo') or True)
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: uruchomione.append('base') or True)
    return uruchomione


@pytest.fixture()
def base(monkeypatch):
    fake = FakeBase()
    import modules.production.services.sync_service as ss
    monkeypatch.setattr(ss, 'get_sync_service', lambda: fake)
    return fake


# ── Powrót do „Nie ustawiono” ────────────────────────────────────────────

def test_cofniecie_sposobu_przez_api(client, app):
    with app.app_context():
        oid = zamowienie(sposob=s.KURIER, delivery_method='Kurier DPD',
                         bl_delivery_method_pending=True).id
    r = client.post(BASE + '/orders/delivery-method', json={'order_ids': [oid], 'sposob': 'brak'})
    dane = r.get_json()
    assert r.status_code == 200 and dane['zmienione'] == [oid]
    assert dane['orders'][0]['sposob'] is None
    with app.app_context():
        order = ProductionOrder.query.get(oid)
        # Niewysłana metoda nie poleci już do Base. — decyzja cofnięta.
        assert order.override_delivery_method is None
        assert order.bl_delivery_method_pending is False
        log = LogisticsLog.query.filter_by(order_id=oid).order_by(LogisticsLog.id.desc()).first()
        assert (log.action, log.old_value, log.new_value) == ('sposob_dostawy', s.KURIER, None)


def test_cofniecie_otwiera_zamkniete_i_kasuje_status_po_spakowaniu(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',),
                           bl_status_pending_id=s.STATUS_SPAKOWANE)
        delivery.przelicz_zamkniecie(order)
        db.session.commit()
        assert order.logistics_closed_at is not None
        wynik = delivery.ustaw_sposob_dostawy(order, s.BRAK)
        db.session.commit()
        assert wynik == {'zmieniono': True, 'przepakowanie': False}
        assert order.logistics_closed_at is None
        assert order.bl_status_pending_id is None


def test_cofniecie_konczy_przepakowanie(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',), repack_required=True)
        delivery.ustaw_sposob_dostawy(order, s.BRAK)
        assert order.repack_required is False


def test_cofniecie_wydanego_to_blad(app):
    from datetime import datetime
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, handed_over_at=datetime(2026, 9, 1))
        with pytest.raises(delivery.LogistykaBlad):
            delivery.ustaw_sposob_dostawy(order, s.BRAK)


def test_brak_sposobu_w_zadaniu_to_dalej_422(client, app):
    """Zgubione pole formularza nie może po cichu wyczyścić decyzji logistyka."""
    with app.app_context():
        oid = zamowienie(sposob=s.KURIER).id
    for cialo in ({'order_ids': [oid]}, {'order_ids': [oid], 'sposob': None},
                  {'order_ids': [oid], 'sposob': ''}):
        assert client.post(BASE + '/orders/delivery-method', json=cialo).status_code == 422
    with app.app_context():
        assert ProductionOrder.query.get(oid).override_delivery_method == s.KURIER


def test_cofniecie_juz_nieustawionego_nic_nie_zmienia(app):
    with app.app_context():
        order = zamowienie()
        assert delivery.ustaw_sposob_dostawy(order, s.BRAK)['zmieniono'] is False


# ── Etap = stanowisko ────────────────────────────────────────────────────

@pytest.mark.parametrize('status, nazwa', [
    ('czeka_na_wyciecie', 'Wycinanie - mikro'),
    ('czeka_na_lakiernie', 'Lakiernia'),
    ('czeka_na_pakowanie', 'Pakowanie'),
    ('spakowane', 'Spakowane'),
    ('wstrzymane', 'Wstrzymane'),
])
def test_etap_to_nazwa_stanowiska(app, status, nazwa):
    with app.app_context():
        wiersz = lista.serializuj(zamowienie(statusy=(status,)))
        assert wiersz['etap'] == {'status': status, 'nazwa': nazwa}


# ── Poprawka adresu ──────────────────────────────────────────────────────

def test_zmiana_adresu_przez_api(client, app, bez_watkow):
    with app.app_context():
        oid = zamowienie(miasto='Kraków').id
    r = client.put(BASE + '/orders/%d/address' % oid,
                   json={'adres': ' ul.  Floriańska 10/5 ', 'kod': '31-021', 'miasto': 'Kraków'})
    dane = r.get_json()
    assert r.status_code == 200 and dane['zmieniono'] is True
    assert (dane['order']['adres'], dane['order']['kod']) == ('ul. Floriańska 10/5', '31-021')
    assert dane['order']['base_czeka'] is True
    assert sorted(bez_watkow) == ['base', 'geo']  # wysyłka do Base. i geokoder — w tle
    with app.app_context():
        order = ProductionOrder.query.get(oid)
        assert order.bl_address_pending is True
        log = LogisticsLog.query.filter_by(order_id=oid, action='adres').one()
        assert log.new_value == '31-021 Kraków' and log.note.startswith('Było: ul. Testowa')


def test_ten_sam_adres_nie_uruchamia_niczego(client, app, bez_watkow):
    with app.app_context():
        order = zamowienie(miasto='Kraków')
        oid, adres = order.id, order.delivery_address
    r = client.put(BASE + '/orders/%d/address' % oid,
                   json={'adres': adres, 'kod': '30-001', 'miasto': 'Kraków'})
    assert r.status_code == 200 and r.get_json()['zmieniono'] is False and bez_watkow == []


@pytest.mark.parametrize('cialo', [
    {'adres': '', 'kod': '31-021', 'miasto': 'Kraków'},
    {'adres': 'Nowa 1', 'kod': '31-021', 'miasto': '  '},
    {'adres': 'Nowa 1', 'kod': 31021, 'miasto': 'Kraków'},
    {'adres': 'x' * 157, 'kod': '', 'miasto': 'Kraków'},
    {'adres': 'Nowa 1', 'kod': '1' * 21, 'miasto': 'Kraków'},
    [1, 2],
])
def test_zly_adres_to_422(client, app, cialo):
    with app.app_context():
        oid = zamowienie().id
    assert client.put(BASE + '/orders/%d/address' % oid, json=cialo).status_code == 422
    with app.app_context():
        assert ProductionOrder.query.get(oid).bl_address_pending is False


def test_adres_nieznanego_zamowienia_to_404(client):
    r = client.put(BASE + '/orders/999999/address', json={'adres': 'A 1', 'kod': '', 'miasto': 'B'})
    assert r.status_code == 404


def test_pusty_kod_zapisuje_null(app):
    with app.app_context():
        order = zamowienie()
        delivery.zmien_adres(order, 'Bachórz 14N', '', 'Bachórz')
        assert order.delivery_postcode is None


def test_dopychacz_wysyla_adres_i_gasi_znacznik(app, base):
    with app.app_context():
        order = zamowienie(bl_address_pending=True)
        assert bl_sync.wyslij_zamowienie(order) == 1
        assert base.wywolania == [('setOrderFields', {
            'order_id': order.baselinker_order_id, 'delivery_address': order.delivery_address,
            'delivery_postcode': '30-001', 'delivery_city': 'Kraków'})]
        assert order.bl_address_pending is False


def test_adres_poprawiony_w_trakcie_wysylki_zostaje_do_wyslania(app, base):
    """Logistyk poprawił adres jeszcze raz w trakcie zapytania — poleci nowy."""
    with app.app_context():
        order = zamowienie(bl_address_pending=True)
        oid = order.id
        stary = base._make_api_request

        def w_trakcie(dane):
            db.session.execute(db.text("UPDATE prod_orders SET delivery_city = 'Rzeszów' WHERE id = :id"),
                               {'id': oid})
            return stary(dane)
        base._make_api_request = w_trakcie
        bl_sync.wyslij_zamowienie(order)
        db.session.commit()
        assert ProductionOrder.query.get(oid).bl_address_pending is True


def test_dopychacz_wybiera_zamowienie_z_samym_adresem(app, base):
    with app.app_context():
        zamowienie(bl_address_pending=True)
        wynik = bl_sync.dopychaj(spij=lambda _: None)
        assert wynik['zamowienia'] == 1 and base.wywolania[0][0] == 'setOrderFields'


def test_synchronizacja_nie_cofa_niewyslanego_adresu(app):
    """Nowa pozycja z Base. do zamówienia z poprawionym (niewysłanym) adresem."""
    from modules.production.services.sync_service import BaselinkerSyncService
    with app.app_context():
        order = zamowienie(bl_address_pending=True)
        order.delivery_address, order.delivery_city = 'Poprawiona 5', 'Rzeszów'
        db.session.commit()
        dane = {'baselinker_order_id': order.baselinker_order_id,
                'delivery_address': 'Stara 1', 'delivery_city': 'Kraków', 'delivery_postcode': '30-001',
                'client_name': 'Nowa nazwa', 'short_product_id': '%d_9' % order.id,
                'product_sequence_in_order': 9, 'original_product_name': 'Blat', 'quantity': 1,
                'current_status': 'czeka_na_wyciecie'}
        produkt = BaselinkerSyncService._create_production_product_from_data(None, dane)
        db.session.add(produkt)
        db.session.commit()
        order = ProductionOrder.query.get(order.id)
        assert (order.delivery_address, order.delivery_city) == ('Poprawiona 5', 'Rzeszów')
        assert order.client_name == 'Nowa nazwa'  # reszta pól zamówienia jak dotąd


def test_synchronizacja_nadpisuje_adres_gdy_nic_nie_czeka(app):
    from modules.production.services.sync_service import BaselinkerSyncService
    with app.app_context():
        order = zamowienie()
        dane = {'baselinker_order_id': order.baselinker_order_id,
                'delivery_address': 'Z Base 7', 'delivery_city': 'Tarnów',
                'short_product_id': '%d_9' % order.id, 'product_sequence_in_order': 9,
                'original_product_name': 'Blat', 'quantity': 1, 'current_status': 'czeka_na_wyciecie'}
        db.session.add(BaselinkerSyncService._create_production_product_from_data(None, dane))
        db.session.commit()
        order = ProductionOrder.query.get(order.id)
        assert (order.delivery_address, order.delivery_city) == ('Z Base 7', 'Tarnów')


# ── Stan geokodera dla przycisku ─────────────────────────────────────────

def test_lekki_stan_geokodera(client, app):
    with app.app_context():
        zamowienie()
    dane = client.get(BASE + '/geocode').get_json()
    assert dane == {'success': True, 'geokoder_dziala': False, 'geokoder_postep': None,
                    'bez_lokalizacji': 1}


# ── Interfejs (statycznie) ───────────────────────────────────────────────

import os  # noqa: E402

_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'modules', 'production', 'logistics')


def _plik(*sciezka):
    return open(os.path.join(_LOG, *sciezka), encoding='utf-8').read()


def test_select_zawsze_ma_nie_ustawiono():
    js = _plik('static', 'js', 'logistics.js')
    # Opcja „Nie ustawiono” zawsze na liście i wysyłana jako 'brak' — nie wyłączona.
    assert '<option value="brak"' in js
    assert 'selected disabled>' not in js


def test_okno_adresu_i_filtr_lokalizacji_w_szablonie():
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert 'data-lg="adres-dialog"' in html and '<dialog' in html
    assert 'data-lg="geo"' in html
    js = _plik('static', 'js', 'logistics.js')
    for fraza in ("'/address'", 'dblclick', "'/geocode'", 'STAN_GEO_MS', 'dopasujWysokosc'):
        assert fraza in js, fraza


def test_ramka_tabeli_trzyma_ukryte_teksty():
    """Teksty .visually-hidden w wierszach wydłużały dokument — ramka musi być pozycjonowana."""
    css = _plik('static', 'css', 'logistics.css')
    blok = css[css.index('.logistics-tab .lg-tabela-ramka {'):]
    blok = blok[:blok.index('}')]
    assert 'position: relative' in blok and 'overflow: auto' in blok


def test_naglowki_tabeli_sortuja():
    """Klik w nagłówek sortuje, drugi klik odwraca; aria-sort dla czytnika ekranu."""
    html = _plik('templates', 'logistics', 'tab_content.html')
    for kolumna in ('numer', 'klient', 'adres', 'metoda', 'sposob', 'etap', 'termin', 'm3'):
        assert 'data-lg-sort="%s"' % kolumna in html, kolumna
        assert 'data-lg-sort-kolumna="%s" aria-sort="none"' % kolumna in html, kolumna
    js = _plik('static', 'js', 'logistics.js')
    assert "kierunek: -stan.sort.kierunek" in js           # drugi klik odwraca
    assert "'logistyka.lista.sortowanie'" in js              # zapamiętane w przeglądarce
    assert 'return posortuj(' in js                          # lista, zaznaczanie zakresu i mapa — jedna kolejność


# ── Rozwijane pozycje zamówienia ─────────────────────────────────────────

def test_lista_niesie_pozycje_zamowienia(app):
    from modules.production.models import ProductionConfiguration
    from tests.logistyka_fixtures import produkt
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_lakiernie', 'anulowane'))
        konf = ProductionConfiguration(species='Dąb', technology='Lity', wood_class='A/B')
        db.session.add(konf)
        db.session.flush()
        order.products[0].configuration_id = konf.id
        order.products[0].parsed_thickness_cm = 4
        order.products[1].cut_to_size = False
        db.session.commit()
        pozycje = lista.pobierz()[0]['pozycje']
        assert [p['id'] for p in pozycje] == ['%d_1' % order.id, '%d_2' % order.id]
        pierwsza, druga = pozycje
        assert (pierwsza['gatunek'], pierwsza['technologia'], pierwsza['klasa'], pierwsza['grubosc_cm']) == \
            ('Dąb', 'Lity', 'A/B', '4')
        assert pierwsza['etap'] == {'status': 'czeka_na_lakiernie', 'nazwa': 'Lakiernia'}
        assert (pierwsza['ilosc'], pierwsza['m3']) == (2, 0.048)
        assert druga['anulowana'] is True and druga['bez_dociecia'] is True
        assert pierwsza['anulowana'] is False and pierwsza['dorobka'] is False


def test_pozycje_bez_zapytania_na_kazda_pozycje(app):
    """Konfiguracje pozycji jednym zapytaniem na listę, nie osobno dla każdej pozycji."""
    from sqlalchemy import event
    from modules.production.models import ProductionConfiguration
    with app.app_context():
        konf = ProductionConfiguration(species='Dąb', technology='Lity', wood_class='A/B')
        db.session.add(konf)
        db.session.flush()
        for _ in range(6):
            order = zamowienie(statusy=('czeka_na_wyciecie', 'czeka_na_pakowanie'))
            for p in order.products:
                p.configuration_id = konf.id
        db.session.commit()
        db.session.expire_all()
        zapytania = []
        sluchacz = lambda *a, **k: zapytania.append(1)  # noqa: E731
        event.listen(db.engine, 'before_cursor_execute', sluchacz)
        try:
            wiersze = lista.pobierz()
        finally:
            event.remove(db.engine, 'before_cursor_execute', sluchacz)
        assert len(wiersze) == 6 and all(w['pozycje'][0]['gatunek'] == 'Dąb' for w in wiersze)
        # Stała liczba, niezależna od liczby pozycji: zamówienia, pozycje, konfiguracje, punkty mapy.
        assert len(zapytania) <= 4


def test_wiersz_rozwija_sie_po_kliknieciu_w_tlo():
    js = _plik('static', 'js', 'logistics.js')
    assert 'data-lg-akcja="rozwin"' in js and '▶' in js
    klik = js[js.index('function klikWiersza'):]
    klik = klik[:klik.index('\n    }\n')]
    assert '[data-lg-adres]' in klik and 'przelaczRozwiniecie(' in klik
    assert 'pozycjeHtml(w)' in js
    css = _plik('static', 'css', 'logistics.css')
    blok = css[css.index('.logistics-tab .lg-pozycje {'):]
    assert 'width: 0' in blok[:blok.index('}')]   # pozycje nie rozpychają tabeli
