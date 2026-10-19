# -*- coding: utf-8 -*-
"""GET /api/mobile/manager/sawmill/orders i /sawmill/orders/<id> — rejestr trakowni na tablecie kierownika (kontrakt
§8.3 i §8.4). Same odczyty. Kierownik widzi deklaracje, pomiary i różnice w m³ oraz procentach, ale NIE widzi pieniędzy
ani notatek rozliczenia (decyzja użytkownika: środek między tabletem trakowni, który nie widzi deklaracji, a panelem,
który widzi wszystko)."""
import itertools
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event

from extensions import db
from modules.production.kierownik.services import biala_lista, trakownia
from modules.production.models import ProductionConfig, ProductionWorker, get_local_now
from modules.production.sawmill.models import (
    STATUS_COMPLETED, STATUS_IN_PROGRESS, STATUS_NEW, STATUS_SETTLED,
    SawmillAudit, SawmillCounter, SawmillDelivery, SawmillLog, SawmillOrder, SawmillSpecies, SawmillSupplier,
)
from modules.production.sawmill.services.orders import add_log, compute_differences, order_totals
from modules.production.sawmill.services.serializers import serialize_order_for_panel
from tests.blokady_pomocnicze import Zapytania
from tests.kierownik_pomocnicze import API, ENDPOINTY_KIEROWNIKA, naglowki, tablet_kierownika
from tests.logistyka_fixtures import app, client  # noqa: F401

TABELE_TRAKOWNI = [m.__table__ for m in (
    SawmillSupplier, SawmillSpecies, SawmillCounter, SawmillDelivery, SawmillOrder, SawmillLog, SawmillAudit)]

# Wartości, które NIE mogą wyjść do kierownika; wpisane do bazy, żeby asercja mogła się wywrócić.
CENA_ZA_M3 = Decimal('1234.56')
NOTATKA_ROZLICZENIA = 'TAJNA-NOTATKA-ROZLICZENIA'
PROG = 3.0

_licznik = itertools.count(1)


@pytest.fixture()
def tablet(app):
    """Tablet kierownika + tabele trakowni i ustawienia z progiem odchyłki 3 %."""
    db.metadata.create_all(bind=db.engine, tables=TABELE_TRAKOWNI)
    db.session.add(ProductionConfig(config_key='sawmill_settings', config_type='json', config_value=json.dumps(
        {'min_diameter_cm': 15.0, 'max_diameter_cm': 250.0, 'min_length_cm': 30.0, 'max_length_cm': 20000.0,
         'decimal_places': 1, 'deviation_threshold_pct': PROG})))
    db.session.add(SawmillSpecies(name='Dąb', short_code='DB', sort_order=10))
    db.session.commit()
    return tablet_kierownika()


def _get(client, tablet, sciezka, **parametry):
    device, kierownik = tablet
    return client.get(API + sciezka, headers=naglowki(device, kierownik), query_string=parametry)


def _ok(client, tablet, sciezka, **parametry):
    r = _get(client, tablet, sciezka, **parametry)
    assert r.status_code == 200, r.get_data()[:500]
    return r.get_json()


def _pracownik(imie='Marek', nazwisko='Zieliński'):
    p = ProductionWorker(first_name=imie, last_name=nazwisko, is_active=True)
    db.session.add(p)
    db.session.commit()
    return p


def _zlecenie(deklaracja='12.500', status=STATUS_COMPLETED, dostawa=None, faktura='FV 112/10/2026',
              dostawca='Tartak Leśny s.c.', klody=(), z_cena=True, uzgodnione=None, notatki=None, deklarowane_klody=40):
    """
    Zlecenie z dostawą i kłodami `[(średnica, długość)]` albo `[(średnica, długość, pracownik)]`. Wartości, które
    kierownik widzieć nie może (cena za m³, wartość deklaracji, notatka rozliczenia), są zawsze wpisane do bazy.
    """
    n = next(_licznik)
    dostawca_wiersz = SawmillSupplier.query.filter_by(name=dostawca).first()
    if dostawca_wiersz is None:
        dostawca_wiersz = SawmillSupplier(name=dostawca)
        db.session.add(dostawca_wiersz)
        db.session.flush()
    dostawa_wiersz = SawmillDelivery(supplier_id=dostawca_wiersz.id, delivery_date=dostawa or date(2026, 10, 14),
                                     invoice_number=faktura)
    db.session.add(dostawa_wiersz)
    db.session.flush()
    deklaracja = Decimal(deklaracja)
    zlecenie = SawmillOrder(
        order_number='TRK/2026/%03d' % n, delivery_id=dostawa_wiersz.id, species_id=SawmillSpecies.query.first().id,
        declared_volume_m3=deklaracja, declared_logs_count=deklarowane_klody,
        price_per_m3=CENA_ZA_M3 if z_cena else None, declared_value=deklaracja * CENA_ZA_M3 if z_cena else None,
        agreed_volume_m3=Decimal(uzgodnione) if uzgodnione else None, notes=notatki,
        settlement_notes=NOTATKA_ROZLICZENIA)
    db.session.add(zlecenie)
    db.session.flush()
    t = datetime(2026, 10, 15, 7, 30, 0)
    for i, kloda in enumerate(klody):
        srednica, dlugosc = kloda[0], kloda[1]
        pracownik = kloda[2] if len(kloda) > 2 else None
        add_log(zlecenie, {'mid_diameter_cm': Decimal(str(srednica)), 'length_cm': Decimal(str(dlugosc))},
                t + timedelta(minutes=i), device_id='TRAK-1', worker_id=pracownik.id if pracownik else None)
    # Status ustawiamy dopiero po pomiarach (pierwszy pomiar sam przełącza new → in_progress).
    zlecenie.status = status
    if status != STATUS_NEW and klody:
        zlecenie.started_at = t
    if status in (STATUS_COMPLETED, STATUS_SETTLED):
        zlecenie.completed_at = datetime(2026, 10, 15, 14, 10, 0)
    db.session.commit()
    return zlecenie


def _numery(dane):
    return [z['numer'] for z in dane['zlecenia']]


def _sciezka_json(obiekt, sciezka=''):
    """Wszystkie klucze (na każdym poziomie) odpowiedzi — do sprawdzenia, że nie ma wśród nich zakazanych."""
    wynik = set()
    if isinstance(obiekt, dict):
        for k, v in obiekt.items():
            wynik.add(k)
            wynik |= _sciezka_json(v)
    elif isinstance(obiekt, list):
        for e in obiekt:
            wynik |= _sciezka_json(e)
    return wynik


def test_trakownia_jest_na_liscie_endpointow():
    assert ('GET', '/sawmill/orders') in ENDPOINTY_KIEROWNIKA
    assert ('GET', '/sawmill/orders/<int:order_id>') in ENDPOINTY_KIEROWNIKA


# --- lista (§8.3) -----------------------------------------------------------------------------------------------

def test_lista_ma_ksztalt_z_kontraktu(app, client, tablet):
    z = _zlecenie(klody=[(40.0, 260.0)] * 3, uzgodnione='12.000', notatki='Do sprawdzenia mierzenia')

    dane = _ok(client, tablet, '/sawmill/orders')

    assert set(dane) == {'zlecenia', 'podsumowanie', 'prog_odchylki_proc'}
    assert dane['prog_odchylki_proc'] == PROG
    assert len(dane['zlecenia']) == 1
    w = dane['zlecenia'][0]
    assert set(w) == {'id', 'numer', 'status', 'status_etykieta', 'gatunek', 'dostawca', 'faktura', 'data_dostawy',
                      'zadeklarowane_m3', 'zadeklarowane_klody', 'uzgodnione_m3', 'zmierzone_m3', 'klody',
                      'roznica_m3', 'roznica_proc', 'odchylka', 'roznica_w_toku', 'notatki', 'rozpoczeto',
                      'zakonczono'}
    assert (w['id'], w['numer'], w['status'], w['status_etykieta']) == (z.id, z.order_number, 'completed', 'Zakończone')
    assert (w['gatunek'], w['dostawca'], w['faktura'], w['data_dostawy']) == (
        'Dąb', 'Tartak Leśny s.c.', 'FV 112/10/2026', '2026-10-14')
    assert (w['zadeklarowane_m3'], w['zadeklarowane_klody'], w['uzgodnione_m3']) == (12.5, 40, 12.0)
    assert w['klody'] == 3
    assert w['zmierzone_m3'] == round(float(order_totals(z.id)[1]), 4)
    assert w['notatki'] == 'Do sprawdzenia mierzenia'
    assert (w['rozpoczeto'], w['zakonczono']) == ('2026-10-15T07:30:00', '2026-10-15T14:10:00')


def test_lista_bez_pieniedzy(app, client, tablet):
    """Cena, wartości i notatka rozliczenia siedzą w bazie (także jako wynik liczenia różnic), ale nie w odpowiedzi."""
    z = _zlecenie(klody=[(40.0, 260.0)] * 3)
    szczegoly = _ok(client, tablet, '/sawmill/orders/%d' % z.id)
    lista = _ok(client, tablet, '/sawmill/orders')

    # Straż testu: wartości naprawdę istnieją w bazie i panel by je wydał, więc brak w odpowiedzi coś znaczy.
    panel = serialize_order_for_panel(z, *order_totals(z.id), compute_differences(z, order_totals(z.id)[1], PROG))
    assert panel['price_per_m3'] == float(CENA_ZA_M3) and panel['settlement_notes'] == NOTATKA_ROZLICZENIA
    assert panel['difference_value'] is not None and panel['declared_value'] is not None

    for odpowiedz in (lista, szczegoly):
        assert biala_lista.zakazane_w(odpowiedz) == []
        klucze = _sciezka_json(odpowiedz)
        assert not klucze & {'price_per_m3', 'declared_value', 'difference_value', 'settlement_notes', 'can_delete'}
        tekst = json.dumps(odpowiedz, ensure_ascii=False)
        assert NOTATKA_ROZLICZENIA not in tekst
        assert '1234.56' not in tekst
        assert str(panel['declared_value']) not in tekst and str(panel['difference_value']) not in tekst


def test_roznice_jak_panel(app, client, tablet):
    """Różnica m³, procent i odchyłka dokładnie jak w panelu (ten sam compute_differences, ten sam próg)."""
    w_normie = _zlecenie(deklaracja='0.400', klody=[(40.0, 260.0)])             # ~0.3267 m³, daleko poniżej
    na_progu = _zlecenie(deklaracja='0.980', klody=[(40.0, 260.0)] * 3)         # ~0.98 m³, w normie
    rozliczone = _zlecenie(deklaracja='12.000', klody=[(40.0, 260.0)] * 3, status=STATUS_SETTLED)
    zlecenia = [w_normie, na_progu, rozliczone]

    dane = _ok(client, tablet, '/sawmill/orders')
    wedlug_numeru = {z['numer']: z for z in dane['zlecenia']}

    assert len(wedlug_numeru) == 3
    from modules.production.sawmill.routers.panel_api import _panel_payload
    odchylek = 0
    for zlecenie in zlecenia:
        panel = _panel_payload(zlecenie, PROG)
        moje = wedlug_numeru[zlecenie.order_number]
        assert moje['roznica_m3'] == panel['difference_m3'] and moje['roznica_m3'] is not None
        assert moje['roznica_proc'] == panel['difference_pct']
        assert moje['odchylka'] == panel['is_deviation']
        assert moje['roznica_w_toku'] == panel['differences_pending'] is False
        assert moje['zmierzone_m3'] == round(panel['measured_volume_m3'], 4)
        odchylek += panel['is_deviation']
    # Test ma sens tylko, gdy są obie strony progu.
    assert 0 < odchylek < 3


def test_otwarte_roznica_w_toku(app, client, tablet):
    nowe = _zlecenie(status=STATUS_NEW)
    w_trakcie = _zlecenie(status=STATUS_IN_PROGRESS, deklaracja='80.000', klody=[(40.0, 260.0)] * 2)

    dane = _ok(client, tablet, '/sawmill/orders')

    for z in (nowe, w_trakcie):
        w = next(x for x in dane['zlecenia'] if x['numer'] == z.order_number)
        assert w['roznica_m3'] is None and w['roznica_proc'] is None
        assert w['odchylka'] is False and w['roznica_w_toku'] is True
    assert next(x for x in dane['zlecenia'] if x['numer'] == nowe.order_number)['status_etykieta'] == 'Nowe'
    assert next(x for x in dane['zlecenia'] if x['numer'] == w_trakcie.order_number)['status_etykieta'] == 'W trakcie'
    # Pod filtrem odchyłek otwartych zleceń nie ma (nie ma o czym alarmować).
    assert _numery(_ok(client, tablet, '/sawmill/orders', only_deviation='1')) == []


def test_filtry_i_domyslne_90_dni(app, client, tablet):
    dzis = get_local_now().date()
    swieze = _zlecenie(dostawa=dzis - timedelta(days=10), faktura='FV SWIEZA', klody=[(40.0, 260.0)])
    granica = _zlecenie(dostawa=dzis - timedelta(days=90), faktura='FV GRANICA', klody=[(40.0, 260.0)])
    stare = _zlecenie(dostawa=dzis - timedelta(days=91), faktura='FV STARA', klody=[(40.0, 260.0)])
    stare_rozliczone = _zlecenie(dostawa=dzis - timedelta(days=200), faktura='FV ROZLICZONA', status=STATUS_SETTLED,
                                 klody=[(40.0, 260.0)])
    stare_otwarte = _zlecenie(dostawa=dzis - timedelta(days=200), faktura='FV OTWARTA', status=STATUS_IN_PROGRESS,
                              klody=[(40.0, 260.0)])
    stare_nowe = _zlecenie(dostawa=dzis - timedelta(days=300), faktura='FV NOWA', status=STATUS_NEW)

    # Bez filtrów: otwarte (bez względu na datę) + dostawy z ostatnich 90 dni; od najnowszego zlecenia.
    domyslnie = _numery(_ok(client, tablet, '/sawmill/orders'))
    assert set(domyslnie) == {z.order_number for z in (swieze, granica, stare_otwarte, stare_nowe)}
    assert domyslnie == sorted(domyslnie, reverse=True)

    # Status zdejmuje okno: wszystkie zlecenia o tym statusie.
    assert set(_numery(_ok(client, tablet, '/sawmill/orders', status='settled'))) == {stare_rozliczone.order_number}
    assert set(_numery(_ok(client, tablet, '/sawmill/orders', status='completed'))) == {
        swieze.order_number, granica.order_number, stare.order_number}

    # Zakres dat po dacie dostawy (granice włącznie) zdejmuje okno 90 dni.
    zakres = _ok(client, tablet, '/sawmill/orders', date_from=(dzis - timedelta(days=95)).isoformat(),
                 date_to=(dzis - timedelta(days=89)).isoformat())
    assert set(_numery(zakres)) == {granica.order_number, stare.order_number}
    tylko_od = _ok(client, tablet, '/sawmill/orders', date_from=(dzis - timedelta(days=100)).isoformat())
    assert set(_numery(tylko_od)) == {swieze.order_number, granica.order_number, stare.order_number}

    # Wyszukiwanie po numerze zlecenia albo faktury też nie jest ucinane oknem.
    assert _numery(_ok(client, tablet, '/sawmill/orders', q='FV ROZLICZONA')) == [stare_rozliczone.order_number]
    assert _numery(_ok(client, tablet, '/sawmill/orders', q=stare.order_number)) == [stare.order_number]
    assert _ok(client, tablet, '/sawmill/orders', q='nie-ma-takiego')['zlecenia'] == []


def test_filtr_tylko_odchylki(app, client, tablet):
    zgodne = _zlecenie(deklaracja='0.327', klody=[(40.0, 260.0)])
    odchylone = _zlecenie(deklaracja='5.000', klody=[(40.0, 260.0)])

    wszystkie = _ok(client, tablet, '/sawmill/orders')
    odchylki = _ok(client, tablet, '/sawmill/orders', only_deviation='1')

    assert set(_numery(wszystkie)) == {zgodne.order_number, odchylone.order_number}
    assert _numery(odchylki) == [odchylone.order_number]
    assert odchylki['zlecenia'][0]['odchylka'] is True
    # Filtr nie dotyka podsumowania trakowni (liczniki całej hali, nie wyniku wyszukiwania).
    assert odchylki['podsumowanie'] == wszystkie['podsumowanie']


def test_podsumowanie_jak_kafelek_dashboardu(app, client, tablet):
    from modules.production.sawmill.services.exports import sawmill_dashboard_stats
    dzis = get_local_now()
    z = _zlecenie(status=STATUS_IN_PROGRESS, klody=[(40.0, 260.0)] * 2)
    # Pomiary z dzisiejszą godziną (liczą się do „dziś” po measured_at), jeden skasowany.
    SawmillLog.query.filter_by(order_id=z.id).update({'measured_at': dzis})
    db.session.add(SawmillLog(order_id=z.id, sequence_no=9, mid_diameter_cm=40, length_cm=260, volume_m3=Decimal('1'),
                              measured_at=dzis, is_deleted=True))
    inne = _zlecenie(status=STATUS_COMPLETED, klody=[(40.0, 260.0)])
    SawmillLog.query.filter_by(order_id=inne.id).update({'measured_at': dzis - timedelta(days=1)})   # nie liczy się do „dziś”
    db.session.commit()

    stat = sawmill_dashboard_stats()
    podsumowanie = _ok(client, tablet, '/sawmill/orders')['podsumowanie']

    assert podsumowanie == {'otwarte': stat['open_orders'], 'klody_dzis': stat['logs_today'],
                            'm3_dzis': round(stat['volume_today_m3'], 4), 'do_rozliczenia': stat['to_settle'],
                            'postep_proc': stat['progress_pct']}
    assert (podsumowanie['otwarte'], podsumowanie['klody_dzis'], podsumowanie['do_rozliczenia']) == (1, 2, 1)
    assert podsumowanie['m3_dzis'] > 0


def test_lista_nie_zadaje_zapytania_na_zlecenie(app, client, tablet):
    """Liczba zapytań nie rośnie z liczbą zleceń (sumy kłód jednym agregatem, nie `order_totals` na wiersz)."""
    _zlecenie(klody=[(40.0, 260.0)])
    with Zapytania() as mala:
        _ok(client, tablet, '/sawmill/orders')
    for _ in range(6):
        _zlecenie(klody=[(40.0, 260.0)] * 2)
    with Zapytania() as duza:
        assert len(_ok(client, tablet, '/sawmill/orders')['zlecenia']) == 7
    assert len(duza.lista) == len(mala.lista)


def test_lista_ma_slaby_etag_i_304(app, client, tablet):
    _zlecenie(klody=[(40.0, 260.0)])

    r = _get(client, tablet, '/sawmill/orders')
    etag = r.headers['ETag']
    assert etag.startswith('W/"') and r.headers['Cache-Control'] == 'private, max-age=15'

    device, kierownik = tablet
    glowki = naglowki(device, kierownik)
    glowki['If-None-Match'] = etag
    nieruszone = client.get(API + '/sawmill/orders', headers=glowki)
    assert nieruszone.status_code == 304 and nieruszone.headers['ETag'] == etag

    _zlecenie(klody=[(40.0, 260.0)])      # zmiana danych zmienia ETag
    po_zmianie = client.get(API + '/sawmill/orders', headers=glowki)
    assert po_zmianie.status_code == 200 and po_zmianie.headers['ETag'] != etag


@pytest.mark.parametrize('parametry', [
    {'status': 'nieznany'},
    {'date_from': '2026-13-45'},
    {'date_to': 'wczoraj'},
    {'date_from': '2026-10-10', 'date_to': '2026-10-01'},
])
def test_zle_parametry_to_400(app, client, tablet, parametry):
    r = _get(client, tablet, '/sawmill/orders', **parametry)
    assert r.status_code == 400
    assert r.get_json()['error'] == 'dane_niepoprawne' and r.get_json()['message']


# --- karta (§8.4) -----------------------------------------------------------------------------------------------

def test_zlecenie_klody_bez_skasowanych_z_pracownikiem(app, client, tablet):
    marek, anna = _pracownik('Marek', 'Zieliński'), _pracownik('Anna', 'Nowak')
    z = _zlecenie(klody=[(41.0, 260.0, marek), (36.0, 240.0, anna), (40.0, 250.0), (38.0, 252.0, marek)])
    skasowana = SawmillLog.query.filter_by(order_id=z.id, sequence_no=2).one()
    skasowana.is_deleted = True
    skasowana.deleted_at = datetime(2026, 10, 15, 9, 0, 0)
    db.session.commit()

    dane = _ok(client, tablet, '/sawmill/orders/%d' % z.id)

    assert set(dane) == {'zlecenie', 'srednie', 'klody'}
    # Zlecenie to dokładnie ten sam DTO co na liście (po skasowaniu kłody: 3 sztuki).
    assert dane['zlecenie'] == next(x for x in _ok(client, tablet, '/sawmill/orders')['zlecenia'] if x['id'] == z.id)
    assert dane['zlecenie']['klody'] == 3

    assert [k['lp'] for k in dane['klody']] == [1, 3, 4]       # w kolejności lp, bez skasowanej (nr 2)
    pierwsza = dane['klody'][0]
    assert set(pierwsza) == {'id', 'lp', 'srednica_cm', 'dlugosc_cm', 'm3', 'zmierzono', 'pracownik'}
    assert (pierwsza['srednica_cm'], pierwsza['dlugosc_cm']) == (41.0, 260.0)
    assert pierwsza['m3'] == round(float(SawmillLog.query.filter_by(order_id=z.id, sequence_no=1).one().volume_m3), 4)
    assert pierwsza['zmierzono'] == '2026-10-15T07:30:00'
    assert pierwsza['pracownik'] == {'id': marek.id, 'nazwa': 'Marek Z.'}
    assert dane['klody'][1]['pracownik'] is None               # pomiar bez profilu (wpis z panelu, stare dane)
    assert dane['klody'][2]['pracownik'] == {'id': marek.id, 'nazwa': 'Marek Z.'}
    assert anna.id not in [(k['pracownik'] or {}).get('id') for k in dane['klody']]    # jej jedyny pomiar skasowany

    # Średnie ze zmierzonych (nieskasowanych) kłód, z tego samego źródła co protokół PDF.
    zywe = SawmillLog.query.filter_by(order_id=z.id, is_deleted=False).all()
    assert dane['srednie'] == {
        'm3': round(float(sum(k.volume_m3 for k in zywe) / 3), 4),
        'srednica_cm': round(float(sum(k.mid_diameter_cm for k in zywe) / 3), 1),
        'dlugosc_cm': round(float(sum(k.length_cm for k in zywe) / 3), 1)}


def test_zlecenie_bez_klod_ma_puste_srednie(app, client, tablet):
    z = _zlecenie(status=STATUS_NEW)

    dane = _ok(client, tablet, '/sawmill/orders/%d' % z.id)

    assert dane['klody'] == []
    assert dane['srednie'] == {'m3': None, 'srednica_cm': None, 'dlugosc_cm': None}


def test_nazwy_pracownikow_jednym_zapytaniem(app, client, tablet):
    pracownicy = [_pracownik('Pracownik%d' % i, 'Kowalski') for i in range(4)]
    z = _zlecenie(klody=[(40.0, 260.0, pracownicy[i % 4]) for i in range(12)])

    with Zapytania() as zapytania:
        dane = _ok(client, tablet, '/sawmill/orders/%d' % z.id)

    assert len(dane['klody']) == 12
    assert sum(1 for sql, _p in zapytania.lista if 'FROM prod_workers' in sql and 'prod_workers.id IN' in sql) == 1


def test_karta_trakowni_nie_ma_pieniedzy_ani_notatek_rozliczenia(app, client, tablet):
    z = _zlecenie(klody=[(40.0, 260.0, _pracownik())] * 2, uzgodnione='11.900', status=STATUS_SETTLED)

    dane = _ok(client, tablet, '/sawmill/orders/%d' % z.id)

    assert biala_lista.zakazane_w(dane) == []
    assert not _sciezka_json(dane) & {'price_per_m3', 'declared_value', 'difference_value', 'settlement_notes',
                                      'audit', 'device_id'}
    assert NOTATKA_ROZLICZENIA not in json.dumps(dane, ensure_ascii=False)
    assert dane['zlecenie']['uzgodnione_m3'] == 11.9


def test_karta_ma_no_store(app, client, tablet):
    z = _zlecenie(klody=[(40.0, 260.0)])

    r = _get(client, tablet, '/sawmill/orders/%d' % z.id)

    assert r.status_code == 200 and 'no-store' in r.headers['Cache-Control'] and 'ETag' not in r.headers


def test_zlecenie_nieznane_404(app, client, tablet):
    r = _get(client, tablet, '/sawmill/orders/99999')

    assert r.status_code == 404
    assert r.get_json()['error'] == 'zlecenie_nieznane' and r.get_json()['message']


def test_trakownia_wymaga_kierownika(app, client, tablet):
    """Bramka kierownika stoi także przed tymi odczytami (profil bez is_manager nie widzi rejestru)."""
    device, _ = tablet
    zwykly = _pracownik('Zwykły', 'Pracownik')

    for sciezka in ('/sawmill/orders', '/sawmill/orders/1'):
        r = client.get(API + sciezka, headers=naglowki(device, zwykly))
        assert r.status_code == 403 and r.get_json()['error'] == 'not_a_manager'
        assert client.get(API + sciezka).status_code == 401


def test_odczyty_trakowni_nic_nie_commituja(app, client, tablet):
    z = _zlecenie(klody=[(40.0, 260.0)])
    db.session.commit()
    zapisy = []

    def _zapis(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) and 'prod_devices' not in statement:
            zapisy.append(statement)

    event.listen(db.engine, 'before_cursor_execute', _zapis)
    try:
        _ok(client, tablet, '/sawmill/orders')
        _ok(client, tablet, '/sawmill/orders/%d' % z.id)
    finally:
        event.remove(db.engine, 'before_cursor_execute', _zapis)

    assert zapisy == []


def test_wczytaj_parametry_nie_wymaga_zadania():
    assert trakownia.wczytaj_parametry({}) == {
        'status': None, 'date_from': None, 'date_to': None, 'q': None, 'only_deviation': False}
