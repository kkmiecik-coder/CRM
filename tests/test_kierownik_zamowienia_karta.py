# -*- coding: utf-8 -*-
"""GET /api/mobile/manager/orders/<id> i /products/<id>/history — karta zamówienia i historia pozycji tabletu
kierownika (kontrakt §5.2 i §5.3)."""
from datetime import datetime

import pytest
from sqlalchemy import event

from extensions import db
from modules.production.kierownik.services import biala_lista, zamowienia
from modules.production.models import (
    ProductionConfiguration, ProductionDevice, ProductionProductEvent, ProductionStationEvent,
    ProductionStationEventWorker, ProductionWorker,
)
from modules.production.priorytety.models import StationDesk
from tests.kierownik_pomocnicze import API, ENDPOINTY_KIEROWNIKA, naglowki, tablet_kierownika
from tests.logistyka_fixtures import app, client, produkt, zamowienie  # noqa: F401

ZAMKNIETE = datetime(2026, 9, 20, 12, 0, 0)


def test_trasy_sa_na_liscie_endpointow():
    assert ('GET', '/orders/<int:order_id>') in ENDPOINTY_KIEROWNIKA
    assert ('GET', '/products/<int:product_id>/history') in ENDPOINTY_KIEROWNIKA


@pytest.fixture()
def tablet(app, monkeypatch):
    # Hak audytu (before_flush) zapamiętuje „tabela istnieje” w zmiennej modułu na stałe; ten test zakłada tabelę
    # zdarzeń tylko w swojej bazie, więc wyłączamy hak, żeby nie wyciekł do testów, w których tabeli nie ma.
    # Zdarzenia historii dodajemy w testach ręcznie.
    from modules.production.services import product_events
    monkeypatch.setattr(product_events, '_audit_table_available', lambda *a, **k: False)
    # Tabele zdarzeń nie wchodzą do wspólnej listy fikstur logistyki; historia pozycji ich potrzebuje.
    ProductionProductEvent.__table__.create(bind=db.engine, checkfirst=True)
    ProductionStationEventWorker.__table__.create(bind=db.engine, checkfirst=True)
    return tablet_kierownika()


def _karta_odp(client, tablet, order_id):
    device, kierownik = tablet
    return client.get('%s/orders/%s' % (API, order_id), headers=naglowki(device, kierownik))


def _karta(client, tablet, order_id):
    r = _karta_odp(client, tablet, order_id)
    assert r.status_code == 200, r.get_data()[:500]
    return r.get_json()['zamowienie']


def _historia_odp(client, tablet, product_id):
    device, kierownik = tablet
    return client.get('%s/products/%s/history' % (API, product_id), headers=naglowki(device, kierownik))


def _historia(client, tablet, product_id):
    r = _historia_odp(client, tablet, product_id)
    assert r.status_code == 200, r.get_data()[:500]
    return r.get_json()


def _konfiguracja(technologia='lity', gatunek=u'Dąb', klasa='A/B'):
    cfg = ProductionConfiguration(species=gatunek, technology=technologia, wood_class=klasa)
    db.session.add(cfg)
    db.session.flush()
    return cfg


# --- karta zamówienia -------------------------------------------------------------------------------------------

def test_karta_ma_pozycje_pelne_i_trase_stanowisk(tablet, client):
    z = zamowienie('transport_woodpower', statusy=(), numer_wewnetrzny='26/00501', bl_id=910501,
                   quote_number='W/2026/0912', order_notes='Klient prosi o telefon przed dostawą.',
                   priority_stars=2, priority_rank=14, delivery_fullname='Jan Kowalski')
    cfg = _konfiguracja('lity')
    p1 = produkt(z, status='czeka_na_formatowanie', sekwencja=1, quantity=2, configuration=cfg,
                 parsed_length_cm=240, parsed_width_cm=65, parsed_thickness_cm=4,
                 parsed_finish_type='surowe', parsed_edge_processing=True, parsed_edge_type=u'zaokrąglenie',
                 parsed_edge_radius=3, parsed_edge_letters=['A', 'B'], production_notes='Uwaga na sęk',
                 priority_rank=1401, shape='rectangular',
                 quantity_done_assembly=2, quantity_done_gluing=2, quantity_done_formatting=1)
    p1.volume_m3 = 0.0312   # fikstura `produkt` ustawia własną objętość; m³ pozycji = objętość sztuki × sztuki
    p2 = produkt(z, status='czeka_na_wyciecie', sekwencja=2, quantity=1, original_product_id=p1.id)
    db.session.commit()

    w = _karta(client, tablet, z.id)
    assert w['order_id'] == z.id and w['numer'] == '26/00501' and w['quote_number'] == 'W/2026/0912'
    assert w['notatki'] == 'Klient prosi o telefon przed dostawą.'
    # Pola listy (§5.1) są na karcie, ale bez skróconych `pozycje[]` w wersji z listy.
    assert w['sposob'] == 'transport_woodpower' and w['gwiazdki'] == 2 and w['ranga'] == 14
    assert w['klient']['nazwa'] == 'Jan Kowalski' and w['pozycji'] == 2

    pozycje = w['pozycje']
    assert [p['product_id'] for p in pozycje] == [p1.id, p2.id]
    a = pozycje[0]
    assert a['short_product_id'] == p1.short_product_id and a['kolejnosc'] == '1/2'
    assert a['specyfikacja'] == {
        'gatunek': u'Dąb', 'technologia': 'Lity', 'klasa': 'A/B', 'grubosc_cm': 4.0, 'wykonczenie': 'Surowe',
        'krawedzie': u'Zaokrąglenie R3 (A, B)', 'ksztalt': u'Prostokątny'}
    assert a['wymiary'] == {'dlugosc_cm': 240.0, 'szerokosc_cm': 65.0, 'grubosc_cm': 4.0}
    assert a['sztuk'] == 2 and a['m3'] == 0.0624
    assert a['status'] == 'czeka_na_formatowanie' and a['status_etykieta'] == 'Czeka na formatowanie'
    # Surowy z obróbką krawędzi: Składanie (lity), Sklejanie, Formatowanie, Krawędzie, Pakowanie.
    assert a['trasa_stanowisk'] == ['assembly', 'gluing', 'formatting', 'edges', 'packaging']
    # `zrobione` ma klucze tylko dla stanowisk z trasy.
    assert a['zrobione'] == {'assembly': 2, 'gluing': 2, 'formatting': 1, 'edges': 0, 'packaging': 0}
    assert a['ranga'] == 1401 and a['notatki_produkcji'] == 'Uwaga na sęk'
    assert a['dorobka'] is False and a['oryginal_id'] is None
    assert pozycje[1]['dorobka'] is True and pozycje[1]['oryginal_id'] == p1.id
    assert pozycje[1]['kolejnosc'] == '2/2'
    assert pozycje[1]['specyfikacja']['gatunek'] is None and pozycje[1]['specyfikacja']['krawedzie'] is None


def test_trasa_stanowisk_wejscie_wg_technologii(tablet, client):
    z = zamowienie(statusy=(), numer_wewnetrzny='26/00502', bl_id=910502)
    mikro = produkt(z, sekwencja=1, configuration=_konfiguracja('mikrowczep'))
    lity = produkt(z, sekwencja=2, configuration=_konfiguracja('lity', klasa='B'))
    bez = produkt(z, sekwencja=3)
    db.session.commit()
    pozycje = _karta(client, tablet, z.id)['pozycje']
    assert pozycje[0]['trasa_stanowisk'][0] == 'cutting' and 'assembly' not in pozycje[0]['trasa_stanowisk']
    assert pozycje[1]['trasa_stanowisk'][0] == 'assembly' and 'cutting' not in pozycje[1]['trasa_stanowisk']
    # Bez technologii (stare dane) pokazujemy oba wejścia, jak web.
    assert pozycje[2]['trasa_stanowisk'][:2] == ['cutting', 'assembly']


def test_trasa_stanowisk_olej_z_krawedziami_bez_krawedzi(tablet, client):
    """Reguła `_should_skip_edges` (jak oś czasu): olej/lakier idzie z formatowania prosto na Lakiernię."""
    z = zamowienie(statusy=(), numer_wewnetrzny='26/00503', bl_id=910503)
    cfg = _konfiguracja('lity')
    olej = produkt(z, sekwencja=1, configuration=cfg, parsed_finish_type='olejowane', parsed_edge_processing=True,
                   quantity_done_painting=1)
    surowe = produkt(z, sekwencja=2, configuration=cfg, parsed_finish_type='surowe', parsed_edge_processing=False)
    bez_dociecia = produkt(z, sekwencja=3, configuration=cfg, cut_to_size=False)
    db.session.commit()
    pozycje = _karta(client, tablet, z.id)['pozycje']
    assert pozycje[0]['trasa_stanowisk'] == ['assembly', 'gluing', 'formatting', 'painting', 'packaging']
    assert 'edges' not in pozycje[0]['zrobione'] and pozycje[0]['zrobione']['painting'] == 1
    assert pozycje[1]['trasa_stanowisk'] == ['assembly', 'gluing', 'formatting', 'packaging']
    # Bez docięcia na wymiar: ze Sklejania prosto do pakowania.
    assert pozycje[2]['trasa_stanowisk'] == ['assembly', 'gluing', 'packaging']
    assert set(pozycje[2]['zrobione']) == {'assembly', 'gluing', 'packaging'}


def test_karta_zalaczniki_lista(tablet, client):
    z = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00504', bl_id=910504,
                   attachment_file_name='projekt_blatu.pdf', attachment_file_url='https://cdn.example/p/projekt.pdf')
    bez = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00505', bl_id=910505)
    bez_nazwy = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00506', bl_id=910506,
                           attachment_file_url='https://cdn.example/p/rysunek.png')
    assert _karta(client, tablet, z.id)['zalaczniki'] == [
        {'nazwa': 'projekt_blatu.pdf', 'url': 'https://cdn.example/p/projekt.pdf'}]
    assert _karta(client, tablet, bez.id)['zalaczniki'] == []
    assert _karta(client, tablet, bez.id)['notatki'] is None
    assert _karta(client, tablet, bez_nazwy.id)['zalaczniki'] == [
        {'nazwa': 'rysunek.png', 'url': 'https://cdn.example/p/rysunek.png'}]


def test_karta_na_stanowiskach(tablet, client):
    z = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_krawedzie'), numer_wewnetrzny='26/00507',
                   bl_id=910507)
    inne = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00508', bl_id=910508)
    p1, p2 = sorted(z.products, key=lambda p: p.id)
    db.session.add_all([
        # Formatowanie pracuje zamówieniami: kafel `o:` na stole.
        StationDesk(station_code='formatting', order_id=z.id, unit_key='o:%d' % z.id),
        # Krawędzie pracują pozycjami: kafel `p:` odłożony.
        StationDesk(station_code='edges', order_id=z.id, product_id=p2.id, unit_key='p:%d' % p2.id,
                    postponed_at=datetime(2026, 10, 19, 9, 40), postpone_reason='brak_materialu'),
        # Kafel innego zamówienia i kafel w niewłaściwej jednostce nie wchodzą do karty.
        StationDesk(station_code='formatting', order_id=inne.id, unit_key='o:%d' % inne.id),
        StationDesk(station_code='gluing', order_id=z.id, unit_key='o:%d' % z.id),
    ])
    db.session.commit()
    assert _karta(client, tablet, z.id)['na_stanowiskach'] == [
        {'stanowisko': 'formatting', 'nazwa': 'Formatowanie', 'gdzie': 'stol', 'unit_key': 'o:%d' % z.id},
        {'stanowisko': 'edges', 'nazwa': u'Krawędzie', 'gdzie': 'odlozone', 'unit_key': 'p:%d' % p2.id,
         'powod_etykieta': u'Brak materiału'},
    ]
    assert _karta(client, tablet, inne.id)['na_stanowiskach'] == [
        {'stanowisko': 'formatting', 'nazwa': 'Formatowanie', 'gdzie': 'stol', 'unit_key': 'o:%d' % inne.id}]


def test_karta_bez_stolu_ma_pusta_liste(tablet, client):
    z = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00509', bl_id=910509)
    assert _karta(client, tablet, z.id)['na_stanowiskach'] == []


def test_karta_svg_jak_tablet(tablet, client):
    """`shape_svg` i `edge_svg` to te same pola, które dostaje tablet stanowiska (serialize_order)."""
    from modules.production.services.mobile_api_service import serialize_order
    z = zamowienie(statusy=(), numer_wewnetrzny='26/00510', bl_id=910510)
    p = produkt(z, sekwencja=1, shape_svg='<svg id="ksztalt"></svg>', edge_svg='<svg id="krawedzie"></svg>')
    bez = produkt(z, sekwencja=2)
    db.session.commit()
    dto = serialize_order(p, station_code='gluing')
    pozycje = _karta(client, tablet, z.id)['pozycje']
    assert pozycje[0]['shape_svg'] == dto['shape_svg'] == '<svg id="ksztalt"></svg>'
    assert pozycje[0]['edge_svg'] == dto['edge_svg'] == '<svg id="krawedzie"></svg>'
    assert pozycje[1]['shape_svg'] is None and pozycje[1]['edge_svg'] is None


def test_karta_zamowienia_archiwalnego_ma_zakonczono_bez_rangi(tablet, client):
    z = zamowienie(statusy=('spakowane',), numer_wewnetrzny='26/00511', bl_id=910511, priority_rank=7,
                   logistics_closed_at=ZAMKNIETE)
    otwarte = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00512', bl_id=910512, priority_rank=3)
    w = _karta(client, tablet, z.id)
    assert w['zakonczono'] == ZAMKNIETE.isoformat() and w['ranga'] is None
    assert w['etap_logistyki']['kod'] == 'spakowane'
    o = _karta(client, tablet, otwarte.id)
    assert o['zakonczono'] is None and o['ranga'] == 3


def test_karta_nieznana_404(tablet, client):
    r = _karta_odp(client, tablet, 99999)
    assert r.status_code == 404
    assert r.get_json()['error'] == 'zamowienie_nieznane' and r.get_json()['message']


def test_karta_wymaga_kierownika(app, client):
    z = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00513', bl_id=910513)
    device, _k = tablet_kierownika()
    r = client.get('%s/orders/%d' % (API, z.id), headers=naglowki(device))
    assert r.status_code == 400 and r.get_json()['error'] == 'worker_required'
    r = client.get('%s/products/%d/history' % (API, z.products[0].id), headers=naglowki(device))
    assert r.status_code == 400 and r.get_json()['error'] == 'worker_required'


# --- etap logistyki zamówienia bez aktywnych pozycji (poprawka z przeglądu zadania 4) ---------------------------

def test_etap_logistyki_zamowienia_bez_pozycji_to_anulowane(tablet, client):
    puste = zamowienie(statusy=(), numer_wewnetrzny='26/00521', bl_id=910521)
    assert zamowienia._etap_logistyki([]) == {'kod': 'anulowane', 'etykieta': 'Anulowane'}
    assert _karta(client, tablet, puste.id)['etap_logistyki'] == {'kod': 'anulowane', 'etykieta': 'Anulowane'}


def test_etap_logistyki_zamowienia_w_calosci_anulowanego_to_anulowane(tablet, client):
    z = zamowienie(statusy=('anulowane', 'anulowane'), numer_wewnetrzny='26/00522', bl_id=910522)
    assert zamowienia._etap_logistyki(list(z.products)) == {'kod': 'anulowane', 'etykieta': 'Anulowane'}
    assert _karta(client, tablet, z.id)['etap_logistyki'] == {'kod': 'anulowane', 'etykieta': 'Anulowane'}
    # Lista (view=archive) mówi to samo.
    device, kierownik = tablet
    odp = client.get(API + '/orders', query_string={'view': 'archive'}, headers=naglowki(device, kierownik))
    wiersz = [o for o in odp.get_json()['zamowienia'] if o['order_id'] == z.id][0]
    assert wiersz['etap_logistyki'] == {'kod': 'anulowane', 'etykieta': 'Anulowane'}


# --- historia pozycji -------------------------------------------------------------------------------------------

def _pracownik(imie, nazwisko):
    w = ProductionWorker(first_name=imie, last_name=nazwisko, is_active=True)
    db.session.add(w)
    db.session.flush()
    return w


def _praca(product, stanowisko, delta, po, kiedy, device_id=None, pracownik=None, source='mobile'):
    e = ProductionStationEvent(production_item_id=product.id, station_code=stanowisko, delta=delta,
                               quantity_done_after=po, created_at=kiedy, device_id=device_id, source=source)
    db.session.add(e)
    db.session.flush()
    if pracownik is not None:
        db.session.add(ProductionStationEventWorker(event_id=e.id, worker_id=pracownik.id, share=1))
    return e


def test_historia_status_i_praca_od_najnowszych(tablet, client):
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00531', bl_id=910531)
    p = z.products[0]
    adam, bartek = _pracownik('Adam', 'Kowalski'), _pracownik('Bartek', 'Nowak')
    db.session.add_all([
        ProductionDevice(device_id='TAB-W', device_name='Tablet Wycinanie', station_code='cutting'),
        ProductionDevice(device_id='TAB-S', device_name='Tablet Sklejanie', station_code='gluing'),
    ])
    _praca(p, 'cutting', 2, 2, datetime(2026, 10, 16, 10, 12, 44), 'TAB-W', adam)
    _praca(p, 'gluing', 1, 1, datetime(2026, 10, 17, 12, 40, 1), 'TAB-S', bartek)
    _praca(p, 'gluing', 1, 2, datetime(2026, 10, 17, 13, 2, 10), 'TAB-S', bartek)
    _praca(p, 'gluing', -1, 1, datetime(2026, 10, 17, 13, 30, 0), 'TAB-S')
    db.session.add(ProductionProductEvent(
        production_item_id=p.id, event_type='status_change', old_value='czeka_na_sklejanie',
        new_value='czeka_na_formatowanie', actor_type='worker', worker_id=bartek.id, device_id='TAB-S',
        source='mobile', created_at=datetime(2026, 10, 17, 13, 2, 11)))
    db.session.add(ProductionProductEvent(
        production_item_id=p.id, event_type='status_change', old_value='czeka_na_wyciecie',
        new_value='czeka_na_sklejanie', actor_type='system', source='system',
        created_at=datetime(2026, 10, 16, 10, 12, 45)))
    db.session.commit()

    odp = _historia(client, tablet, p.id)
    assert odp['product_id'] == p.id
    assert odp['przeplyw'] == {
        'cutting': {'zakonczono': '2026-10-16T10:12:44', 'kto': 'Tablet Wycinanie', 'pracownicy': ['Adam K.']},
        'gluing': {'zakonczono': '2026-10-17T13:02:10', 'kto': 'Tablet Sklejanie', 'pracownicy': ['Bartek N.']},
    }
    historia = odp['historia']
    assert [w['kiedy'] for w in historia] == sorted([w['kiedy'] for w in historia], reverse=True)
    assert [(w['rodzaj'], w['kiedy']) for w in historia] == [
        ('praca', '2026-10-17T13:30:00'),
        ('status', '2026-10-17T13:02:11'),
        ('praca', '2026-10-17T13:02:10'),
        ('praca', '2026-10-17T12:40:01'),
        ('status', '2026-10-16T10:12:45'),
        ('praca', '2026-10-16T10:12:44'),
    ]
    status = historia[1]
    assert status == {
        'kiedy': '2026-10-17T13:02:11', 'rodzaj': 'status', 'z': 'czeka_na_sklejanie',
        'z_etykieta': 'Czeka na sklejanie', 'na': 'czeka_na_formatowanie',
        'na_etykieta': 'Czeka na formatowanie', 'kto': 'Bartek N.', 'zrodlo': 'mobile'}
    # Cofnięcie sztuki to osobny wpis pracy z ujemną zmianą.
    assert historia[0]['stanowisko'] == 'gluing' and historia[0]['zmiana'] == -1
    assert historia[0]['zrodlo'] == 'mobile'
    assert historia[2] == {'kiedy': '2026-10-17T13:02:10', 'rodzaj': 'praca', 'stanowisko': 'gluing',
                           'zmiana': 1, 'kto': 'Bartek N.', 'zrodlo': 'mobile'}
    # Automat jest nazwany, a nie anonimowy.
    assert historia[4]['kto'] == 'System' and historia[4]['zrodlo'] == 'system'


def test_historia_praca_ma_pracownika_kazdego_odbicia(tablet, client):
    """`kto` na wierszu `praca` to pracownik TEGO odbicia, nie suma pracowników stanowiska (§5.3)."""
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00534', bl_id=910534)
    p = z.products[0]
    adam, bartek = _pracownik('Adam', 'Kowalski'), _pracownik('Bartek', 'Nowak')
    db.session.add(ProductionDevice(device_id='TAB-S2', device_name='Tablet Sklejanie', station_code='gluing'))
    _praca(p, 'gluing', 1, 1, datetime(2026, 10, 17, 12, 40, 1), 'TAB-S2', adam)
    _praca(p, 'gluing', 1, 2, datetime(2026, 10, 17, 13, 2, 10), 'TAB-S2', bartek)
    # Dwoje przy jednym odbiciu (praca zespołowa) i cofnięcie z własnym pracownikiem.
    e = _praca(p, 'gluing', 1, 3, datetime(2026, 10, 17, 13, 10, 0), 'TAB-S2', adam)
    db.session.add(ProductionStationEventWorker(event_id=e.id, worker_id=bartek.id, share=0.5))
    _praca(p, 'gluing', -1, 2, datetime(2026, 10, 17, 13, 20, 0), 'TAB-S2', bartek)
    # Odbicie bez atrybucji (praca bez wybranego profilu) wraca do nazwy urządzenia.
    _praca(p, 'gluing', 1, 3, datetime(2026, 10, 17, 13, 30, 0), 'TAB-S2')
    db.session.commit()

    odp = _historia(client, tablet, p.id)
    assert [(w['kiedy'], w['zmiana'], w['kto']) for w in odp['historia']] == [
        ('2026-10-17T13:30:00', 1, 'Tablet Sklejanie'),
        ('2026-10-17T13:20:00', -1, 'Bartek N.'),
        ('2026-10-17T13:10:00', 1, 'Adam K., Bartek N.'),
        ('2026-10-17T13:02:10', 1, 'Bartek N.'),
        ('2026-10-17T12:40:01', 1, 'Adam K.'),
    ]
    # Przepływ zostaje przy poziomie stanowiska: obaj pracownicy.
    assert odp['przeplyw']['gluing']['pracownicy'] == ['Adam K.', 'Bartek N.']


def test_historia_innych_rodzajow_zdarzen(tablet, client):
    z = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00532', bl_id=910532)
    p = z.products[0]
    db.session.add_all([
        ProductionProductEvent(production_item_id=p.id, event_type='priority_change', old_value='5',
                               new_value='1', actor_type='system', source='system',
                               created_at=datetime(2026, 10, 17, 9, 0, 0)),
        ProductionProductEvent(production_item_id=p.id, event_type='rework', actor_type='system',
                               source='system', note='doróbka z pozycji 1',
                               created_at=datetime(2026, 10, 17, 10, 0, 0)),
        ProductionProductEvent(production_item_id=p.id, event_type='logistics', actor_type='system',
                               source='system', created_at=datetime(2026, 10, 17, 11, 0, 0)),
    ])
    db.session.commit()
    historia = _historia(client, tablet, p.id)['historia']
    assert [(w['rodzaj'], w['kiedy']) for w in historia] == [
        ('logistyka', '2026-10-17T11:00:00'), ('dorobka', '2026-10-17T10:00:00'),
        ('priorytet', '2026-10-17T09:00:00')]
    assert historia[1]['opis'] == u'doróbka z pozycji 1' and 'opis' not in historia[0]
    assert historia[2]['z'] == '5' and historia[2]['na'] == '1'


def test_historia_pustej_pozycji(tablet, client):
    z = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00533', bl_id=910533)
    assert _historia(client, tablet, z.products[0].id) == {
        'product_id': z.products[0].id, 'przeplyw': {}, 'historia': []}


def test_historia_nieznana_404(tablet, client):
    r = _historia_odp(client, tablet, 99999)
    assert r.status_code == 404
    assert r.get_json()['error'] == 'pozycja_nieznana' and r.get_json()['message']


# --- dane wrażliwe, pamięć podręczna, zapytania ------------------------------------------------------------------

def test_karta_i_historia_bez_zakazanych_kluczy(tablet, client):
    z = zamowienie('transport_woodpower', statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00541',
                   bl_id=910541, client_email='tajny@klient.pl', client_phone='600700800', shipping_price=45.5,
                   delivery_company='Firma', attachment_file_name='a.pdf', attachment_file_url='https://x/a.pdf')
    p = z.products[0]
    p.total_value_net = 1234.56
    p.unit_price_net = 617.28
    db.session.add(ProductionProductEvent(production_item_id=p.id, event_type='status_change',
                                          old_value='czeka_na_wyciecie', new_value='wstrzymane',
                                          actor_type='system', source='system',
                                          created_at=datetime(2026, 10, 17, 9, 0, 0)))
    db.session.commit()
    for r in (_karta_odp(client, tablet, z.id), _historia_odp(client, tablet, p.id)):
        assert r.status_code == 200
        assert biala_lista.zakazane_w(r.get_json()) == []
        tekst = r.get_data(as_text=True)
        for sekret in ('tajny@klient.pl', '600700800', '1234.56', '617.28', 'ul. Testowa'):
            assert sekret not in tekst


def test_karta_i_historia_no_store(tablet, client):
    z = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00542', bl_id=910542)
    for r in (_karta_odp(client, tablet, z.id), _historia_odp(client, tablet, z.products[0].id)):
        assert r.status_code == 200
        assert 'no-store' in r.headers['Cache-Control']
        assert 'ETag' not in r.headers


def test_odczyty_nie_zmieniaja_stanu(tablet, client):
    z = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00543', bl_id=910543)
    db.session.add(StationDesk(station_code='formatting', order_id=z.id, unit_key='o:%d' % z.id))
    db.session.commit()
    p = z.products[0]
    przed = (p.updated_at, p.current_status, p.priority_rank, z.updated_at)
    _karta(client, tablet, z.id)
    _historia(client, tablet, p.id)
    db.session.expire_all()
    assert (p.updated_at, p.current_status, p.priority_rank, z.updated_at) == przed
    assert StationDesk.query.count() == 1


def _zapytania(client, tablet, url):
    device, kierownik = tablet
    naglowek = naglowki(device, kierownik)
    zapytania = []

    def zapisz(conn, cursor, statement, parameters, context, executemany):
        zapytania.append(statement)

    event.listen(db.engine, 'before_cursor_execute', zapisz)
    try:
        r = client.get(url, headers=naglowek)
    finally:
        event.remove(db.engine, 'before_cursor_execute', zapisz)
    assert r.status_code == 200, r.get_data()[:300]
    return len(zapytania)


def test_karta_bez_n_plus_1(tablet, client):
    cfg = _konfiguracja('lity')
    male = zamowienie(statusy=(), numer_wewnetrzny='26/00551', bl_id=910551)
    duze = zamowienie(statusy=(), numer_wewnetrzny='26/00552', bl_id=910552)
    for i in range(1, 3):
        produkt(male, sekwencja=i, configuration=cfg)
    for i in range(1, 16):
        produkt(duze, sekwencja=i, configuration=_konfiguracja('lity', klasa='K%d' % i))
    db.session.commit()
    malo = _zapytania(client, tablet, '%s/orders/%d' % (API, male.id))
    duzo = _zapytania(client, tablet, '%s/orders/%d' % (API, duze.id))
    assert duzo == malo, 'liczba zapytań rośnie z liczbą pozycji (%d -> %d)' % (malo, duzo)


def test_historia_bez_n_plus_1(tablet, client):
    z = zamowienie(statusy=('czeka_na_wyciecie', 'czeka_na_wyciecie'), numer_wewnetrzny='26/00553', bl_id=910553)
    a, b = sorted(z.products, key=lambda p: p.id)
    adam = _pracownik('Adam', 'Kowalski')
    _praca(a, 'cutting', 1, 1, datetime(2026, 10, 16, 10, 0, 0), None, adam)
    db.session.add(ProductionProductEvent(production_item_id=a.id, event_type='status_change',
                                          old_value='czeka_na_wyciecie', new_value='czeka_na_sklejanie',
                                          actor_type='worker', worker_id=adam.id, source='mobile',
                                          created_at=datetime(2026, 10, 16, 10, 1, 0)))
    db.session.commit()
    malo =_zapytania(client, tablet, '%s/products/%d/history' % (API, a.id))
    for i in range(20):
        _praca(a, 'gluing', 1, i + 1, datetime(2026, 10, 17, 10, i, 0), None, adam)
        db.session.add(ProductionProductEvent(production_item_id=a.id, event_type='status_change',
                                              old_value='czeka_na_wyciecie', new_value='czeka_na_sklejanie',
                                              actor_type='worker', worker_id=adam.id, source='mobile',
                                              created_at=datetime(2026, 10, 17, 11, i, 0)))
    db.session.commit()
    duzo = _zapytania(client, tablet, '%s/products/%d/history' % (API, a.id))
    assert duzo == malo, 'liczba zapytań rośnie z liczbą zdarzeń (%d -> %d)' % (malo, duzo)
