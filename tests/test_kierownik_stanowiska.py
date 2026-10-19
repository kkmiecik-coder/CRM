# -*- coding: utf-8 -*-
"""GET /api/mobile/manager/stations, /stations/<kod> i /workers/now — przegląd stanowisk, pełne stanowisko i
„Kto teraz pracuje” tabletu kierownika (kontrakt §7.1, §7.2 i §7.5).

Aplikacja testowa to apka panelu produkcji (`krawedzie_fixtures`: zakładka Stanowiska w webie), do której dokładamy
blueprint kierownika — dzięki temu parytet liczb z `stations-tab-content` sprawdzamy na prawdziwym endpoincie.
Ten plik nie zakłada tabeli prod_product_events (konwencja pakietu)."""
import itertools
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from extensions import db
from modules.production.kierownik.services import biala_lista, stanowiska
from modules.production.models import (
    ProductionConfiguration, ProductionDevice, ProductionOrder, ProductionWorker, ProductionWorkerSession,
    get_local_now,
)
from modules.production.priorytety.models import StationDesk
from modules.production.priorytety.services import stol, widok
from tests.blokady_pomocnicze import Zapytania
from tests.kierownik_pomocnicze import API, ENDPOINTY_KIEROWNIKA, naglowki, tablet_kierownika
from tests.krawedzie_fixtures import BASE, app as _app_krawedzi  # noqa: F401
from tests.logistyka_fixtures import produkt
from tests.priorytety_fixtures import (  # noqa: F401
    czyste_ustawienia, drabina_domyslna, ustaw, zamrozony_dzien,
)

KOLEJNOSC = ['cutting', 'assembly', 'gluing', 'formatting', 'edges', 'painting', 'packaging']
KOLEJNOSC_OBSADY = KOLEJNOSC + ['sawmill', 'verification', 'delivery', 'manager']
_licznik = itertools.count(1)


@pytest.fixture()
def app(_app_krawedzi, zamrozony_dzien, czyste_ustawienia):
    """Apka panelu produkcji z domyślną drabiną, z dołożonym blueprintem kierownika i konfiguracją API mobilnego."""
    from modules.production.kierownik import kierownik_mobile_bp
    _app_krawedzi.config['API_MOBILE'] = {
        'jwt_secret': 'x' * 64, 'token_ttl_days': 365, 'ip_whitelist': [], 'min_supported_app_version': '0.0.0'}
    _app_krawedzi.register_blueprint(kierownik_mobile_bp, url_prefix='/api/mobile/manager')
    drabina_domyslna()
    return _app_krawedzi


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def tablet(app):
    return tablet_kierownika()


# ── pomocniki danych ─────────────────────────────────────────────────────────────────────────────────────────

def zam(statusy=('czeka_na_sklejanie',), gwiazdki=0, **kolumny):
    """Zamówienie z jedną pozycją na każdy status (z konfiguracją materiału). Commituje."""
    n = next(_licznik)
    order = ProductionOrder(baselinker_order_id=810000 + n, internal_order_number='27/%05d' % n,
                            client_name='Klient %d' % n, priority_stars=gwiazdki,
                            client_phone='500100200', delivery_address='ul. Tajna 1', **kolumny)
    db.session.add(order)
    cfg = ProductionConfiguration.find_or_create(u'Dąb', 'lity', 'A/B')
    db.session.flush()
    for i, status in enumerate(statusy, start=1):
        produkt(order, status=status, sekwencja=i, configuration=cfg, quantity=3)   # 0,024 m³ × 3 szt. = 0,072 m³
    db.session.commit()
    return order


def kafel_stolu(stanowisko, obiekt, odlozony=None, zrodlo='kolejka', **kolumny):
    """Wiersz stołu dla pozycji albo zamówienia; `odlozony` — czas odłożenia (None = leży na stole). Commituje."""
    if isinstance(obiekt, ProductionOrder):
        dane = dict(order_id=obiekt.id, product_id=None, unit_key='o:%d' % obiekt.id)
    else:
        dane = dict(order_id=obiekt.order_id, product_id=obiekt.id, unit_key='p:%d' % obiekt.id)
    if odlozony is not None:
        dane.update(postponed_at=odlozony, postpone_reason='brak_materialu', postpone_note=u'czekamy na dąb')
    dane.update(kolumny)
    db.session.add(StationDesk(station_code=stanowisko, pulled_at=datetime(2026, 10, 5, 8, 0), zrodlo=zrodlo,
                               **dane))
    db.session.commit()


def sesja(pracownik, stanowisko, start=None, aktywnosc=None):
    """Otwarta sesja pracownika na stanowisku, z dzisiejszą datą pracy. Commituje."""
    teraz = get_local_now()
    start = start or teraz - timedelta(hours=3)
    db.session.add(ProductionWorkerSession(
        worker_id=pracownik.id, station_code=stanowisko, session_group='g%d' % next(_licznik),
        started_at=start, last_activity_at=aktywnosc or start, work_date=teraz.date()))
    db.session.commit()


def pracownik(imie='Adam', nazwisko='Kowalczyk', kolor='#2E7D32'):
    kto = ProductionWorker(first_name=imie, last_name=nazwisko, is_active=True, color_hex=kolor)
    db.session.add(kto)
    db.session.commit()
    return kto


def pobierz(client, tablet, sciezka, **parametry):
    device, kierownik = tablet
    return client.get(API + sciezka, headers=naglowki(device, kierownik), query_string=parametry)


def ok(client, tablet, sciezka, **parametry):
    r = pobierz(client, tablet, sciezka, **parametry)
    assert r.status_code == 200, r.get_data()[:500]
    return r.get_json()


def stanowisko_w(dane, kod):
    return next(s for s in dane['stanowiska'] if s['kod'] == kod)


# ── lista endpointów i bramka ────────────────────────────────────────────────────────────────────────────────

def test_trasy_sa_na_liscie_endpointow():
    for trasa in (('GET', '/stations'), ('GET', '/stations/<kod>'), ('GET', '/workers/now')):
        assert trasa in ENDPOINTY_KIEROWNIKA


@pytest.mark.parametrize('sciezka', ['/stations', '/stations/formatting', '/workers/now'])
def test_bramka_kierownika_na_trasach_stanowisk(app, client, sciezka):
    device, kierownik = tablet_kierownika()
    obcy = ProductionDevice(device_id='TAB-OBCY-ST', device_name='Formatowanie', station_code='formatting')
    db.session.add(obcy)
    db.session.commit()
    r = client.get(API + sciezka, headers=naglowki(obcy, kierownik))
    assert r.status_code == 403 and r.get_json()['error'] == 'station_not_allowed'
    r = client.get(API + sciezka, headers=naglowki(device))
    assert r.status_code == 400 and r.get_json()['error'] == 'worker_required'


# ── przegląd (§7.1) ──────────────────────────────────────────────────────────────────────────────────────────

def test_przeglad_statystyki_jak_zakladka(app, client, tablet):
    """Liczby przeglądu == `data[kod].stats` zakładki Stanowiska (jedna definicja w `statystyki_stanowisk`)."""
    from datetime import date
    if date.today() != get_local_now().date():
        pytest.skip('Zakładka w webie liczy „dziś” po dacie systemowej, kierownik po czasie lokalnym Polski.')
    teraz = get_local_now()
    ustaw('priorytety_tryb_formatting', 'stol')
    kto = pracownik()
    z1 = zam(('czeka_na_formatowanie', 'czeka_na_formatowanie'))
    z2 = zam(('czeka_na_formatowanie', 'czeka_na_sklejanie'))
    zam(('czeka_na_formatowanie',) * 3)
    zam(('czeka_na_sklejanie',) * 2)
    zam(('czeka_na_krawedzie',))
    zam(('czeka_na_lakiernie',) * 2)
    dawne = zam(('czeka_na_pakowanie',))
    dawne.products[0].formatting_completed_at = teraz
    gotowe = zam(('czeka_na_krawedzie',))
    gotowe.products[0].formatting_completed_at = teraz
    gotowe.products[0].gluing_completed_at = teraz
    kafel_stolu('formatting', z1)
    kafel_stolu('formatting', z2, odlozony=datetime(2026, 10, 5, 9, 0), postponed_by_worker_id=kto.id)
    db.session.commit()

    web = client.get(BASE + '/stations-tab-content').get_json()['data']
    db.session.rollback()
    przeglad = ok(client, tablet, '/stations')

    assert [s['kod'] for s in przeglad['stanowiska']] == KOLEJNOSC
    for kod in KOLEJNOSC:
        liczby, web_stats = stanowisko_w(przeglad, kod)['statystyki'], web[kod]['stats']
        assert liczby['oczekuje'] == web_stats['total_pending'], kod
        assert liczby['ukonczono_dzis'] == web_stats['today_completed'], kod
        assert liczby['m3_dzis'] == pytest.approx(web_stats['today_volume'], abs=1e-4), kod
        if kod != 'painting':
            for pole in ('na_stole', 'miejsca', 'odlozone', 'limit_odlozen', 'kolejka_dalej'):
                assert liczby[pole] == web_stats[pole], (kod, pole)
    assert stanowisko_w(przeglad, 'formatting')['statystyki']['ukonczono_dzis'] == 2
    assert stanowisko_w(przeglad, 'formatting')['statystyki']['m3_dzis'] == pytest.approx(0.144, abs=1e-4)


def test_przeglad_naglowki_i_licznik_widm_i_niekompletnych(app, client, tablet):
    ustaw('priorytety_tryb_formatting', 'stol')
    z = zam(('czeka_na_formatowanie', 'czeka_na_sklejanie'))       # niekompletne: jedna pozycja nadal na Sklejaniu
    inny = zam(('czeka_na_pakowanie',))
    kafel_stolu('formatting', inny)                                 # widmo: zamówienie bez pozycji na stanowisku
    przeglad = ok(client, tablet, '/stations')

    formatowanie = stanowisko_w(przeglad, 'formatting')
    assert (formatowanie['nazwa'], formatowanie['tryb'], formatowanie['jednostka'], formatowanie['ma_stol']) == \
        ('Formatowanie', 'stol', 'zamowienie', True)
    assert formatowanie['statystyki']['niekompletnych'] == 1
    assert formatowanie['statystyki']['widm'] == 1
    assert formatowanie['statystyki']['miejsca'] == 2 and formatowanie['statystyki']['limit_odlozen'] == 10
    assert set(formatowanie['statystyki']) == {
        'oczekuje', 'ukonczono_dzis', 'm3_dzis', 'na_stole', 'miejsca', 'odlozone', 'limit_odlozen',
        'kolejka_dalej', 'widm', 'niekompletnych'}
    sklejanie = stanowisko_w(przeglad, 'gluing')
    assert (sklejanie['tryb'], sklejanie['jednostka'], sklejanie['ma_stol']) == ('stary', 'pozycja', True)
    lakiernia = stanowisko_w(przeglad, 'painting')
    assert (lakiernia['tryb'], lakiernia['ma_stol'], lakiernia['statystyki']['miejsca']) == ('stary', False, 0)
    assert z.id and lakiernia['statystyki']['kolejka_dalej'] == lakiernia['statystyki']['oczekuje']


def test_przeglad_suma_i_obsada(app, client, tablet):
    kto = pracownik('Adam', 'Kowalczyk', '#2E7D32')
    teraz = get_local_now()
    sesja(kto, 'formatting', start=teraz - timedelta(hours=3), aktywnosc=teraz - timedelta(minutes=7))
    zam(('czeka_na_formatowanie',) * 2)
    zam(('czeka_na_sklejanie',))
    zam(('czeka_na_pakowanie',))
    gotowe = zam(('czeka_na_krawedzie',))
    gotowe.products[0].gluing_completed_at = teraz
    db.session.commit()

    przeglad = ok(client, tablet, '/stations')

    (osoba,) = stanowisko_w(przeglad, 'formatting')['obsada']
    assert set(osoba) == {'id', 'imie', 'nazwisko', 'inicjaly', 'kolor', 'od', 'ostatnia_aktywnosc',
                          'bezczynnosc_min'}
    assert (osoba['id'], osoba['imie'], osoba['nazwisko'], osoba['inicjaly'], osoba['kolor']) == \
        (kto.id, 'Adam', 'Kowalczyk', 'AK', '#2E7D32')
    assert osoba['od'] == (teraz - timedelta(hours=3)).replace(microsecond=0).isoformat()
    assert osoba['bezczynnosc_min'] in (7, 8)
    assert stanowisko_w(przeglad, 'gluing')['obsada'] == []
    suma = przeglad['suma']
    assert suma['oczekuje'] == sum(s['statystyki']['oczekuje'] for s in przeglad['stanowiska']) == 5
    assert suma['ukonczono_dzis'] == 1 and suma['m3_dzis'] == pytest.approx(0.072, abs=1e-4)
    assert suma['odlozone'] == 0
    assert przeglad['wyliczono'] <= get_local_now().isoformat(timespec='seconds')


def test_przeglad_etag_i_304_oraz_naglowki_pamieci(app, client, tablet):
    zam(('czeka_na_sklejanie',))
    device, kierownik = tablet
    pierwszy = client.get(API + '/stations', headers=naglowki(device, kierownik))
    assert pierwszy.status_code == 200
    assert pierwszy.headers['Cache-Control'] == 'private, max-age=15'
    etag = pierwszy.headers['ETag']
    assert etag.startswith('W/"')
    drugi = client.get(API + '/stations', headers=dict(naglowki(device, kierownik), **{'If-None-Match': etag}))
    assert drugi.status_code == 304
    zam(('czeka_na_sklejanie',))
    trzeci = client.get(API + '/stations', headers=dict(naglowki(device, kierownik), **{'If-None-Match': etag}))
    assert trzeci.status_code == 200 and trzeci.headers['ETag'] != etag


# ── pełne stanowisko (§7.2) ──────────────────────────────────────────────────────────────────────────────────

def _scenariusz_formatowania():
    """Stół (K=2), odłożone, niekompletne, kolejka i dwa rodzaje widm na Formatowaniu (jednostka: zamówienie)."""
    ustaw('priorytety_tryb_formatting', 'stol')
    kto = pracownik('Marek', 'Zielony', '#1565C0')
    na_stole = zam(('czeka_na_formatowanie', 'czeka_na_formatowanie'), gwiazdki=2)
    odlozone = zam(('czeka_na_formatowanie',))
    zam(('czeka_na_formatowanie',) * 3, gwiazdki=1)
    zam(('czeka_na_formatowanie',))
    niekompletne = zam(('czeka_na_formatowanie', 'czeka_na_sklejanie'))
    bez_pozycji = zam(('czeka_na_pakowanie',))
    kafel_stolu('formatting', na_stole, zrodlo='biuro')
    kafel_stolu('formatting', odlozone, odlozony=datetime(2026, 10, 5, 9, 40), postponed_by_worker_id=kto.id)
    kafel_stolu('formatting', bez_pozycji)                                       # widmo: zamówienie bez pozycji
    pozycja = na_stole.products[0]
    kafel_stolu('formatting', pozycja)                                           # widmo: kafel innej jednostki
    return na_stole, odlozone, niekompletne, bez_pozycji, pozycja


def test_pelne_stanowisko_jak_widok(app, client, tablet):
    na_stole, odlozone, niekompletne, _bez, _pozycja = _scenariusz_formatowania()

    dane = ok(client, tablet, '/stations/formatting', limit=2)
    db.session.rollback()
    panel = widok.stoly_panelu(['formatting'])[0]
    kolejka = widok.kolejka_stanowiska('formatting', limit=2)

    assert (dane['kod'], dane['nazwa'], dane['tryb'], dane['jednostka'], dane['ma_stol']) == \
        ('formatting', 'Formatowanie', 'stol', 'zamowienie', True)
    assert dane['stol'] == panel['stol'] and len(dane['stol']) == 1
    assert dane['odlozone'] == panel['odlozone'] and len(dane['odlozone']) == 1
    assert dane['widma'] == panel['widma']
    assert dane['niekompletne'] == widok.kolejka_stanowiska('formatting', limit=500)['niekompletne']
    assert dane['kolejka']['kafle'] == kolejka['kafle'] and len(dane['kolejka']['kafle']) == 2
    assert dane['kolejka']['lacznie'] == kolejka['lacznie'] == panel['kolejka_dalej']
    assert dane['stol'][0]['order_id'] == na_stole.id and dane['stol'][0]['zrodlo'] == 'biuro'
    assert dane['odlozone'][0]['order_id'] == odlozone.id
    assert dane['odlozone'][0]['pracownik_krotko'] == 'Marek Z.' and dane['odlozone'][0]['powod_etykieta']
    assert [n['order_id'] for n in dane['niekompletne']] == [niekompletne.id]
    liczby = dane['statystyki']
    assert (liczby['na_stole'], liczby['odlozone'], liczby['widm'], liczby['niekompletnych']) == (1, 1, 2, 1)
    assert liczby['kolejka_dalej'] == dane['kolejka']['lacznie']
    # kształt kafla zamówienia i kafla odłożonego wg kontraktu
    assert set(dane['stol'][0]) == {'unit_key', 'order_id', 'numer', 'gwiazdki', 'szczebel', 'termin', 'pozycji',
                                    'sposob_dostawy_ustawiony', 'pobrano', 'zrodlo', 'wyslal',
                                    'wroci_przy_dopelnieniu'}
    assert set(dane['odlozone'][0]) == set(dane['stol'][0]) | {
        'powod', 'powod_etykieta', 'notatka', 'odlozono', 'pracownik', 'pracownik_krotko'}
    assert set(dane['kolejka']['kafle'][0]) == {'order_id', 'numer', 'gwiazdki', 'szczebel', 'termin', 'pozycji',
                                                'sposob_dostawy_ustawiony'}


def test_widma_wszystkie_rodzaje_jak_w_panelu(app, client, tablet):
    """`widma` niesie wszystkie trzy rodzaje wierszy stołu bez kafla (jak panel), nie tylko jeden."""
    _scenariusz_formatowania()
    ustaw('priorytety_tryb_gluing', 'stol')
    sklejanie = zam(('czeka_na_sklejanie', 'czeka_na_pakowanie'))
    kafel_stolu('gluing', sklejanie.products[1])                                 # widmo: pozycja już nie czeka

    formatowanie = ok(client, tablet, '/stations/formatting')['widma']
    sklejanie_widma = ok(client, tablet, '/stations/gluing')['widma']

    opisy = {w['opis'] for w in formatowanie} | {w['opis'] for w in sklejanie_widma}
    assert opisy == {widok.OPIS_WIDMA_POZYCJI, widok.OPIS_WIDMA_ZAMOWIENIA, widok.OPIS_WIDMA_JEDNOSTKI}
    for widmo in formatowanie + sklejanie_widma:
        assert set(widmo) == {'unit_key', 'order_id', 'numer', 'product_id', 'short_id', 'zrodlo', 'pobrano',
                              'odlozony', 'opis'}
    db.session.rollback()
    assert formatowanie == widok.stoly_panelu(['formatting'])[0]['widma']
    assert sklejanie_widma == widok.stoly_panelu(['gluing'])[0]['widma']


def test_kafel_pozycji_ma_pola_pozycji(app, client, tablet):
    ustaw('priorytety_tryb_gluing', 'stol')
    z = zam(('czeka_na_sklejanie',) * 3, gwiazdki=1)
    kafel_stolu('gluing', z.products[0])

    dane = ok(client, tablet, '/stations/gluing')

    assert dane['jednostka'] == 'pozycja'
    assert set(dane['stol'][0]) == {'unit_key', 'order_id', 'numer', 'gwiazdki', 'szczebel', 'termin',
                                    'product_id', 'short_id', 'rozpoczete', 'dorobka', 'material', 'wymiary',
                                    'pobrano', 'zrodlo', 'wyslal', 'wroci_przy_dopelnieniu'}
    assert dane['stol'][0]['unit_key'] == 'p:%d' % z.products[0].id
    assert dane['stol'][0]['material']['gatunek'] == u'Dąb'
    assert set(dane['kolejka']['kafle'][0]) == {'order_id', 'numer', 'gwiazdki', 'szczebel', 'termin', 'product_id',
                                                'short_id', 'rozpoczete', 'dorobka', 'material', 'wymiary'}
    db.session.rollback()
    assert dane['kolejka']['kafle'] == widok.kolejka_stanowiska('gluing', limit=50)['kafle']


def test_tryb_stary_i_lakiernia(app, client, tablet):
    zam(('czeka_na_sklejanie',) * 3)
    lakier = zam(('czeka_na_lakiernie',) * 2, gwiazdki=3)

    sklejanie = ok(client, tablet, '/stations/gluing')
    assert sklejanie['tryb'] == 'stary' and sklejanie['stol'] == [] and sklejanie['odlozone'] == []
    assert sklejanie['kolejka']['lacznie'] == 3 and len(sklejanie['kolejka']['kafle']) == 3
    assert sklejanie['statystyki']['kolejka_dalej'] == 3 and sklejanie['statystyki']['na_stole'] == 0

    lakiernia = ok(client, tablet, '/stations/painting')
    assert (lakiernia['ma_stol'], lakiernia['tryb'], lakiernia['jednostka']) == (False, 'stary', 'pozycja')
    assert lakiernia['stol'] == [] and lakiernia['odlozone'] == [] and lakiernia['widma'] == []
    assert lakiernia['niekompletne'] == []
    assert lakiernia['kolejka']['lacznie'] == 2 and len(lakiernia['kolejka']['kafle']) == 2
    for kafel in lakiernia['kolejka']['kafle']:
        assert set(kafel) == {'product_id', 'short_id', 'order_id', 'numer', 'gwiazdki', 'dorobka', 'termin',
                              'dni_do_terminu', 'grupa', 'material'}
        assert kafel['order_id'] == lakier.id and kafel['gwiazdki'] == 3 and kafel['grupa']
    assert lakiernia['statystyki']['miejsca'] == 0 and lakiernia['statystyki']['kolejka_dalej'] == 2
    assert ok(client, tablet, '/stations/painting', limit=1)['kolejka']['lacznie'] == 2
    assert len(ok(client, tablet, '/stations/painting', limit=1)['kolejka']['kafle']) == 1


def test_pelne_stanowisko_niesie_obsade(app, client, tablet):
    kto = pracownik()
    sesja(kto, 'edges')
    dane = ok(client, tablet, '/stations/edges')
    assert [o['id'] for o in dane['obsada']] == [kto.id]
    assert ok(client, tablet, '/stations/cutting')['obsada'] == []


def test_limit_kolejki(app, client, tablet):
    for _ in range(55):
        zam(('czeka_na_sklejanie',))

    domyslny = ok(client, tablet, '/stations/gluing')
    assert len(domyslny['kolejka']['kafle']) == 50 and domyslny['kolejka']['lacznie'] == 55
    assert len(ok(client, tablet, '/stations/gluing', limit=500)['kolejka']['kafle']) == 55
    assert len(ok(client, tablet, '/stations/gluing', limit=1)['kolejka']['kafle']) == 1
    for zly in ('0', '501', '-1', 'abc', '1.5'):
        r = pobierz(client, tablet, '/stations/gluing', limit=zly)
        assert r.status_code == 400 and r.get_json()['error'] == 'dane_niepoprawne', zly
        assert r.get_json()['message']


def test_nieznane_stanowisko_404(app, client, tablet):
    for kod in ('finishing', 'sawmill', 'manager', 'xyz'):
        r = pobierz(client, tablet, '/stations/%s' % kod)
        assert r.status_code == 404 and r.get_json()['error'] == 'stanowisko_nieznane', kod
        assert r.get_json()['message']
    # nieznane stanowisko ma pierwszeństwo przed błędem limitu
    assert pobierz(client, tablet, '/stations/xyz', limit='0').get_json()['error'] == 'stanowisko_nieznane'


def test_pelne_stanowisko_bez_pamieci_podrecznej(app, client, tablet):
    device, kierownik = tablet
    r = client.get(API + '/stations/gluing', headers=naglowki(device, kierownik))
    assert r.status_code == 200 and 'no-store' in r.headers['Cache-Control']
    r = client.get(API + '/workers/now', headers=naglowki(device, kierownik))
    assert r.status_code == 200 and 'no-store' in r.headers['Cache-Control']


# ── odczyty niczego nie piszą, nie blokują i nie dopełniają stołu ───────────────────────────────────────────

def test_odczyt_nie_dopelnia_stolu(app, client, tablet, monkeypatch):
    """Tryb `stol`, stoły puste, a w kolejce praca: odczyty kierownika nie dokładają ani jednego wiersza stołu
    i nie wołają żadnego pisarza stołu (to robi wyłącznie `GET desk` tabletów)."""
    for kod in ('gluing', 'formatting'):
        ustaw('priorytety_tryb_' + kod, 'stol')
    zam(('czeka_na_sklejanie',) * 3)
    zam(('czeka_na_formatowanie',) * 2)
    zam(('czeka_na_formatowanie',))
    assert StationDesk.query.count() == 0

    def _zakazane(*args, **kwargs):
        raise AssertionError('odczyt kierownika wywołał pisarza stołu')
    for nazwa in ('dopelnij', 'wyslij', 'zdejmij_przez_biuro', 'przygotuj_start', 'zablokuj_stanowisko'):
        monkeypatch.setattr(stol, nazwa, _zakazane)

    for sciezka in ('/stations', '/stations/gluing', '/stations/formatting', '/stations/painting', '/workers/now'):
        ok(client, tablet, sciezka)

    assert StationDesk.query.count() == 0
    assert ok(client, tablet, '/stations/gluing')['statystyki']['kolejka_dalej'] == 3   # praca czekała w kolejce


def test_odczyt_bez_blokad_zapisow_i_commitow(app, client, tablet):
    """Poza jednym commitem `require_device_token` (znacznik kontaktu urządzenia) odczyt nie commituje, nie zapisuje
    i nie bierze żadnej blokady (SELECT … FOR UPDATE / LOCK IN SHARE MODE)."""
    ustaw('priorytety_tryb_formatting', 'stol')
    kto = pracownik()
    sesja(kto, 'formatting')
    z = zam(('czeka_na_formatowanie',) * 2)
    kafel_stolu('formatting', z)
    zam(('czeka_na_formatowanie',))

    for sciezka in ('/stations', '/stations/formatting', '/stations/painting', '/workers/now'):
        with Zapytania() as zapytania:
            def _commit(conn):
                zapytania.lista.append(('COMMIT', None))
            event.listen(db.engine, 'commit', _commit)
            try:
                ok(client, tablet, sciezka)
            finally:
                event.remove(db.engine, 'commit', _commit)
        sql = [s for s, _p in zapytania.lista]
        assert not [s for s in sql if s.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))], sciezka
        assert sql.count('COMMIT') == 1, (sciezka, sql.count('COMMIT'))
        po_commicie = sql[sql.index('COMMIT') + 1:]
        assert po_commicie, sciezka        # po commicie urządzenia odczyt rzeczywiście ruszył
        assert not [s for s in po_commicie if s.startswith(('INSERT', 'UPDATE', 'DELETE'))], (sciezka, po_commicie)


def test_odczyty_stanowisk_bez_zakazanych(app, client, tablet):
    _scenariusz_formatowania()
    kto = pracownik()
    sesja(kto, 'formatting')
    zam(('czeka_na_lakiernie',))
    for sciezka in ('/stations', '/stations/formatting', '/stations/gluing', '/stations/painting', '/workers/now'):
        dane = ok(client, tablet, sciezka)
        assert biala_lista.zakazane_w(dane) == [], sciezka


# ── „Kto teraz pracuje” (§7.5) ───────────────────────────────────────────────────────────────────────────────

def test_kto_teraz_wszystkie_stanowiska(app, client, tablet):
    device, kierownik = tablet
    teraz = get_local_now()
    robotnik = pracownik('Adam', 'Kowalczyk')
    sesja(robotnik, 'formatting', start=teraz - timedelta(hours=4), aktywnosc=teraz - timedelta(minutes=12))
    sesja(kierownik, 'manager', start=teraz - timedelta(minutes=30), aktywnosc=teraz - timedelta(minutes=1))
    trakarz = pracownik('Ewa', 'Lis')
    sesja(trakarz, 'sawmill')
    # pierwsze logowanie doby bywa na innym stanowisku niż bieżąca sesja
    db.session.add(ProductionWorkerSession(
        worker_id=robotnik.id, station_code='cutting', session_group='wczesna', started_at=teraz - timedelta(hours=7),
        last_activity_at=teraz - timedelta(hours=6), ended_at=teraz - timedelta(hours=6), work_date=teraz.date()))
    db.session.commit()

    dane = ok(client, tablet, '/workers/now')

    assert [s['kod'] for s in dane['stanowiska']] == KOLEJNOSC_OBSADY
    assert stanowisko_w(dane, 'manager')['nazwa'] == 'Kierownik hali'
    assert stanowisko_w(dane, 'sawmill')['nazwa'] == 'Trakownia'
    for kod in ('cutting', 'assembly', 'gluing', 'edges', 'painting', 'packaging', 'verification', 'delivery'):
        assert stanowisko_w(dane, kod)['osoby'] == [], kod
    (formatowanie,) = stanowisko_w(dane, 'formatting')['osoby']
    assert set(formatowanie) == {'id', 'imie', 'nazwisko', 'inicjaly', 'kolor', 'od', 'pierwsze_dzis',
                                 'ostatnia_aktywnosc', 'bezczynnosc_min'}
    assert formatowanie['id'] == robotnik.id and formatowanie['bezczynnosc_min'] in (12, 13)
    assert formatowanie['od'] == (teraz - timedelta(hours=4)).replace(microsecond=0).isoformat()
    assert formatowanie['pierwsze_dzis'] == (teraz - timedelta(hours=7)).replace(microsecond=0).isoformat()
    (na_manager,) = stanowisko_w(dane, 'manager')['osoby']
    assert na_manager['id'] == kierownik.id and na_manager['bezczynnosc_min'] in (1, 2)
    assert dane['lacznie_osob'] == 3
    assert dane['wyliczono'] <= get_local_now().isoformat(timespec='seconds')


def test_kto_teraz_bez_nikogo(app, client, tablet):
    dane = ok(client, tablet, '/workers/now')
    assert [s['kod'] for s in dane['stanowiska']] == KOLEJNOSC_OBSADY
    assert all(s['osoby'] == [] for s in dane['stanowiska'])
    assert dane['lacznie_osob'] == 0


def test_limit_wczytaj_limit():
    assert stanowiska.wczytaj_limit(None) == 50
    assert stanowiska.wczytaj_limit('') == 50
    assert stanowiska.wczytaj_limit(' 7 ') == 7
    with pytest.raises(stanowiska.BladLimitu):
        stanowiska.wczytaj_limit('0')


def test_obsada_dashboardu_bez_pelnych_czasow(app):
    """`obsada_stanowisk()` bez `szczegoly` zachowuje dotychczasowy kształt wiersza (dashboard produkcji)."""
    from modules.production.services.worker_stats_service import obsada_stanowisk
    sesja(pracownik(), 'gluing')
    (osoba,) = obsada_stanowisk()['gluing']
    assert not {'od', 'pierwsze_dzis', 'ostatnia_aktywnosc'} & set(osoba)
    (pelna,) = obsada_stanowisk(szczegoly=True)['gluing']
    assert {'od', 'pierwsze_dzis', 'ostatnia_aktywnosc'} <= set(pelna)
