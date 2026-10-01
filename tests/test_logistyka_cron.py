# -*- coding: utf-8 -*-
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import bl_sync, geocoding
from modules.production.models import ProductionConfig, ProductionOrder
from tests.logistyka_fixtures import BASE, SEKRET_CRONA, app, client, produkt, zamowienie  # noqa: F401

NAGLOWEK = {'X-Cron-Secret': SEKRET_CRONA}


@pytest.fixture()
def watki(monkeypatch):
    """Etap 2: cron uruchamia też geokoder w tle — bez mocka odpalałby PRAWDZIWY
    wątek na tym samym połączeniu SQLite (StaticPool) co żądanie testowe i gubił
    się z nim o transakcję (wyścig, nie coś do naprawienia w kodzie produkcyjnym)."""
    uruchomione = []
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: uruchomione.append(1) or True)
    monkeypatch.setattr(geocoding, 'uruchom_w_tle', lambda app_: uruchomione.append(1) or True)
    return uruchomione


def test_cron_bez_sekretu_to_403(client, watki):
    assert client.post(BASE + '/cron').status_code == 403
    assert watki == []


def test_cron_uruchamia_dopychacz_i_odpowiada_od_razu(client, watki):
    r = client.post(BASE + '/cron', headers=NAGLOWEK)
    assert r.status_code == 200
    dane = r.get_json()
    assert dane['dopychacz_uruchomiony'] is True
    assert dane['geokoder_uruchomiony'] is True
    assert watki == [1, 1]  # dopychacz Base. i geokoder — oba uruchomione


def test_cron_zwraca_pauze(client, app, watki):
    """Review Focus 2 — pauza jest widoczna w odpowiedzi crona (log crontaba)."""
    with app.app_context():
        bl_sync.wstrzymaj_do(datetime(2099, 1, 1))
    assert client.post(BASE + '/cron', headers=NAGLOWEK).get_json()['base_wstrzymane_do'] \
        == '2099-01-01T00:00:00'


def test_cron_otwiera_zamowienie_z_nowa_aktywna_pozycja(client, app, watki):
    """Review Focus 5: Base. dołożył pozycję do zamkniętego zamówienia kurierskiego."""
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',),
                           logistics_closed_at=datetime(2026, 9, 20))
        produkt(order, status='czeka_na_wyciecie')
        db.session.commit()
        order_id = order.id
    r = client.post(BASE + '/cron', headers=NAGLOWEK)
    assert r.get_json()['przeliczone'] == 1
    with app.app_context():
        assert ProductionOrder.query.get(order_id).logistics_closed_at is None


def test_cron_otwiera_zamkniete_na_aktywnej_trasie(client, app, watki):
    """M10 (fala poprawek): zamówienie z transportem własnym, w całości spakowane, zamknięte,
    a z przystankiem na trasie AKTYWNEJ — jeszcze nie pojechało, więc cron je otwiera. Zamówienie dostarczone
    (pozycje „dostarczone”, krok 4.4) na trasie WYKONANEJ zostaje zamknięte."""
    from modules.production.logistics.models import Route, RouteStop
    with app.app_context():
        otwierane = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',),
                               logistics_closed_at=datetime(2026, 9, 20))
        dostarczone = zamowienie(sposob=s.TRANSPORT, statusy=('dostarczone',),
                                 logistics_closed_at=datetime(2026, 9, 20))
        for order, status in ((otwierane, 'zatwierdzona'), (dostarczone, 'wykonana')):
            trasa = Route(name='T ' + status, date_from=datetime(2026, 10, 1).date(),
                          date_to=datetime(2026, 10, 1).date(), status=status)
            db.session.add(trasa)
            db.session.flush()
            db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
        db.session.commit()
        otwierane_id, dostarczone_id = otwierane.id, dostarczone.id
    r = client.post(BASE + '/cron', headers=NAGLOWEK)
    assert r.get_json()['przeliczone'] == 1
    with app.app_context():
        assert ProductionOrder.query.get(otwierane_id).logistics_closed_at is None
        assert ProductionOrder.query.get(dostarczone_id).logistics_closed_at is not None


def test_cron_blad_zwraca_500_bez_uruchamiania_dopychacza(client, monkeypatch, watki):
    """Błąd w przeliczaniu nie uruchamia dopychacza i zwraca 500 ze strukturą JSON."""
    from modules.production.logistics.services import delivery
    monkeypatch.setattr(delivery, 'przelicz_otwarte', lambda: (_ for _ in ()).throw(RuntimeError('boom')))

    r = client.post(BASE + '/cron', headers=NAGLOWEK)
    assert r.status_code == 500
    j = r.get_json()
    assert j['success'] is False
    assert 'boom' in j['error']
    # dopychacz nie powinien być uruchomiony
    assert watki == []


# ── I2 (przegląd gałęzi): produkty zapisane przez stary kod w oknie wdrożenia ──────
# deploy.sh robi migrate → przeliczenie klientów (do 300 s) → restart; przez ten czas
# stary kod wciąż zapisuje `czeka_na_logistyke`. Po restarcie taki produkt nie ma
# kolejki na tablecie ani filtra na liście — cron przenosi go do pakowania.

class LoggerSzpieg(object):
    def __init__(self):
        self.ostrzezenia = []

    def debug(self, message, **kwargs):
        pass

    info = error = debug

    def warning(self, message, **kwargs):
        self.ostrzezenia.append((message, kwargs))


def test_cron_przenosi_osierocone_z_logistyki_do_pakowania(client, app, watki, monkeypatch):
    from modules.production.logistics.routers import cron_api
    szpieg = LoggerSzpieg()
    monkeypatch.setattr(cron_api, 'logger', szpieg)
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'czeka_na_logistyke'))
        for p in order.products:
            p.updated_at = datetime(2026, 1, 1)
        db.session.commit()
        order_id = order.id
        osierocony_id = order.products[1].id
        assert order.products[1].current_status == 'czeka_na_logistyke'
        assert order.logistics_completed_at is None
    r = client.post(BASE + '/cron', headers=NAGLOWEK)
    assert r.status_code == 200
    assert r.get_json()['przeniesione_z_logistyki'] == 1
    assert len(szpieg.ostrzezenia) == 1
    with app.app_context():
        order = ProductionOrder.query.get(order_id)
        assert [p.current_status for p in order.products] == ['czeka_na_pakowanie'] * 2
        assert order.logistics_completed_at is not None  # ostatni produkt wszedł do pakowania
        # przeniesiona pozycja ma świeży updated_at — ETag kolejki pakowania na tablecie
        podbite = {p.id for p in order.products if p.updated_at > datetime(2026, 1, 1)}
        assert podbite == {osierocony_id}
    # idempotentnie: drugi przebieg nic nie przenosi i nie ostrzega
    assert client.post(BASE + '/cron', headers=NAGLOWEK).get_json()['przeniesione_z_logistyki'] == 0
    assert len(szpieg.ostrzezenia) == 1


def test_przeniesienie_nie_ustawia_zeszlo_z_produkcji_przedwczesnie(app):
    from modules.production.logistics.services import delivery
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_logistyke', 'czeka_na_lakiernie'))
        assert delivery.przenies_osierocone_z_logistyki() == 1
        db.session.commit()
        assert order.products[0].current_status == 'czeka_na_pakowanie'
        assert order.logistics_completed_at is None


def test_przeniesienie_przelicza_zamkniecie(app):
    """Zamówienie zamknięte (np. kurier) z produktem w `czeka_na_logistyke` otwiera się."""
    from modules.production.logistics.services import delivery
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_logistyke'),
                           logistics_closed_at=datetime(2026, 9, 20))
        assert delivery.przenies_osierocone_z_logistyki() == 1
        db.session.commit()
        assert order.logistics_closed_at is None


# ── Krok 4.3: pozycje już wydanych zamówień → 'dostarczone' (po restarcie, nie w migracji) ──────
# Migracja działa przed restartem, a stary kod nie zna 'dostarczone' w ENUM — przepisanie robi cron.

def test_dostarcz_wydane_przestawia_tylko_spakowane_wydanych(app):
    from modules.production.logistics.services import delivery
    with app.app_context():
        wydane = zamowienie(sposob=s.ODBIOR, statusy=('spakowane', 'spakowane', 'anulowane'),
                            handed_over_at=datetime(2026, 9, 20))
        niewydane = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',))
        w_produkcji = zamowienie(sposob=s.ODBIOR, statusy=('czeka_na_pakowanie',),
                                 handed_over_at=datetime(2026, 9, 20))
        for order in (wydane, niewydane, w_produkcji):
            for p in order.products:
                p.updated_at = datetime(2026, 1, 1)
        db.session.commit()
        teraz = datetime(2026, 10, 1, 8, 0)

        assert delivery.dostarcz_wydane(teraz) == 2
        db.session.commit()

        assert [p.current_status for p in wydane.products] == ['dostarczone', 'dostarczone', 'anulowane']
        assert [p.updated_at for p in wydane.products] == [teraz, teraz, datetime(2026, 1, 1)]  # ETag tabletów
        assert [p.current_status for p in niewydane.products] == ['spakowane']
        assert [p.current_status for p in w_produkcji.products] == ['czeka_na_pakowanie']
        # idempotentnie: drugi przebieg nie ma czego przestawiać
        assert delivery.dostarcz_wydane(teraz) == 0
        znacznik = ProductionConfig.query.filter_by(config_key=delivery.KLUCZ_WYDANE_DOSTARCZONE).one()
        assert znacznik.config_value == '2026-10-01 08:00:00'   # chwila pierwszego przebiegu


def test_cron_przestawia_wydane_na_dostarczone(client, app, watki):
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane', 'spakowane'),
                           handed_over_at=datetime(2026, 9, 20),
                           logistics_closed_at=datetime(2026, 9, 20))
        order_id = order.id
    r = client.post(BASE + '/cron', headers=NAGLOWEK)
    assert r.status_code == 200
    assert r.get_json()['wydane_dostarczone'] == 2
    with app.app_context():
        order = ProductionOrder.query.get(order_id)
        assert [p.current_status for p in order.products] == ['dostarczone', 'dostarczone']
        assert order.logistics_closed_at is not None   # zamkniecie wydanego odbioru zostaje
    # idempotentnie: kolejny przebieg nic nie przestawia
    assert client.post(BASE + '/cron', headers=NAGLOWEK).get_json()['wydane_dostarczone'] == 0


# ── Jednorazowość przestawienia wydanych (fala końcowa 4.3, F1/I1) ──────────────────────────────
# Znacznik `logistyka_wydane_dostarczone` w prod_config: pierwszy udany przebieg przestawia pozycje
# wydanych zamówień i go zapisuje, kolejne zwracają 0 bez pytania o pozycje. Bez niego cron co godzinę
# „dostarczałby” pozycje wydanego zamówienia, które wróciły z doróbki i są znów spakowane.

def _znacznik():
    return ProductionConfig.query.filter_by(config_key='logistyka_wydane_dostarczone').all()


def test_pierwszy_przebieg_przestawia_wydane_i_zapisuje_znacznik(client, app, watki):
    """(a) Pierwszy przebieg: wydane 'spakowane' → 'dostarczone' i znacznik z chwilą przebiegu."""
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane', 'spakowane'),
                           handed_over_at=datetime(2026, 9, 20), logistics_closed_at=datetime(2026, 9, 20))
        order_id = order.id
        assert _znacznik() == []
    assert client.post(BASE + '/cron', headers=NAGLOWEK).get_json()['wydane_dostarczone'] == 2
    with app.app_context():
        assert [p.current_status for p in ProductionOrder.query.get(order_id).products] ==             ['dostarczone', 'dostarczone']
        znacznik = _znacznik()
        assert len(znacznik) == 1
        datetime.strptime(znacznik[0].config_value, '%Y-%m-%d %H:%M:%S')   # format jak weryfikacja.data_wdrozenia()


def test_po_znaczniku_pozycja_wydanego_po_dorobce_zostaje_spakowana(client, app, watki):
    """(b) Po znaczniku: pozycja wydanego zamówienia wróciła do produkcji (doróbka) i znów jest
    'spakowane' — kolejny przebieg jej nie rusza, bo klient jej nie odebrał. Tak samo nowa pozycja
    wydanego zamówienia, spakowana już po przebiegu."""
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane', 'spakowane'),
                           handed_over_at=datetime(2026, 9, 20), logistics_closed_at=datetime(2026, 9, 20))
        order_id = order.id
    assert client.post(BASE + '/cron', headers=NAGLOWEK).get_json()['wydane_dostarczone'] == 2
    with app.app_context():
        order = ProductionOrder.query.get(order_id)
        dorobka = order.products[0]
        dorobka.current_status = 'czeka_na_pakowanie'     # doróbka: pozycja wraca do produkcji
        db.session.commit()
        dorobka.current_status = 'spakowane'              # i znów jest spakowana (complete_task)
        produkt(order, status='spakowane')                # Base. dołożył pozycję, też spakowana
        db.session.commit()
    assert client.post(BASE + '/cron', headers=NAGLOWEK).get_json()['wydane_dostarczone'] == 0
    with app.app_context():
        assert [p.current_status for p in ProductionOrder.query.get(order_id).products] ==             ['spakowane', 'dostarczone', 'spakowane']
        assert len(_znacznik()) == 1


def test_przebieg_na_pustej_bazie_ustawia_znacznik_i_zwraca_zero(client, app, watki):
    """(c) Nic do przestawienia: znacznik i tak powstaje (inaczej każdy przebieg pytałby o pozycje)."""
    from modules.production.logistics.services import delivery
    with app.app_context():
        assert ProductionOrder.query.count() == 0 and _znacznik() == []
        assert delivery.dostarcz_wydane(datetime(2026, 10, 1, 8, 0)) == 0
        db.session.commit()
        assert [z.config_value for z in _znacznik()] == ['2026-10-01 08:00:00']
    r = client.post(BASE + '/cron', headers=NAGLOWEK)
    assert r.status_code == 200 and r.get_json()['wydane_dostarczone'] == 0
    with app.app_context():
        assert len(_znacznik()) == 1                      # kolejny przebieg nie dubluje znacznika


def test_przebieg_ze_znacznikiem_nie_pyta_o_pozycje(app):
    from sqlalchemy import event
    from modules.production.logistics.services import delivery
    with app.app_context():
        zamowienie(sposob=s.ODBIOR, statusy=('spakowane',), handed_over_at=datetime(2026, 9, 20))
        assert delivery.dostarcz_wydane() == 1
        db.session.commit()

        zapytania = []
        event.listen(db.engine, 'before_cursor_execute',
                     lambda conn, cursor, statement, *a, **k: zapytania.append(statement))
        assert delivery.dostarcz_wydane() == 0
        assert zapytania and not any('prod_products' in z for z in zapytania)   # tylko odczyt znacznika


def test_rownolegly_przebieg_z_duplikatem_znacznika_konczy_sie_zerem_bez_bledu(app, monkeypatch):
    """Dwa przebiegi naraz: drugi nie widzi jeszcze znacznika pierwszego (odczyt sprzed jego commitu),
    wstawia własny i dostaje duplikat klucza. Ma zwrócić 0 bez wyjątku, nie ruszyć pozycji, a sesja
    zostaje sprawna (wołający commituje dalej)."""
    from modules.production.logistics.services import delivery
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',), handed_over_at=datetime(2026, 9, 20))
        assert delivery.dostarcz_wydane() == 1                     # „pierwszy” przebieg, zacommitowany
        db.session.commit()
        order.products[0].current_status = 'spakowane'             # pozycja wróciła po doróbce
        db.session.commit()
        monkeypatch.setattr(delivery, '_znacznik_wydane_dostarczone', lambda: None)   # odczyt „sprzed commitu”
        assert delivery.dostarcz_wydane() == 0
        db.session.commit()
        assert order.products[0].current_status == 'spakowane'
        assert len(_znacznik()) == 1


# ── Siatka w cronie: zamknięcia zapadłe na nieaktualnym stanie (decyzja Konrada 1.10, spec 4.6) ──
# Stanowisko decyduje o zamknięciu na migawce sposobu dostawy; zmiana sposobu z panelu w tej samej chwili
# zostawia zamówienie zamknięte wbrew regule. `przelicz_otwarte` otwiera je, ale TYLKO gdy zamknięcie jest
# późniejsze niż znacznik wdrożenia 4.3 (`logistyka_weryfikacja_od`) — migracja etapu 1 zamknęła historycznie
# ~1500 zamówień bez względu na sposób dostawy i bez zawężenia pierwszy przebieg otworzyłby je masowo.

ZNACZNIK = datetime(2026, 9, 30, 12, 0, 0)
PO_ZNACZNIKU = datetime(2026, 9, 30, 12, 5, 0)      # 5 minut po wdrożeniu 4.3


def _ustaw_znacznik(wartosc=ZNACZNIK):
    db.session.add(ProductionConfig(
        config_key='logistyka_weryfikacja_od', config_type='string',
        config_value=wartosc if isinstance(wartosc, str) else wartosc.strftime('%Y-%m-%d %H:%M:%S')))
    db.session.commit()


def _na_trasie(order, status):
    from modules.production.logistics.models import Route, RouteStop
    trasa = Route(name='T ' + status, date_from=datetime(2026, 10, 1).date(),
                  date_to=datetime(2026, 10, 1).date(), status=status)
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
    db.session.commit()


def _po_przebiegu(zamowienia):
    """Uruchamia siatkę crona i zwraca (liczba zmian, [czy zamówienie zostało zamknięte])."""
    from modules.production.logistics.services import delivery
    zmienione = delivery.przelicz_otwarte()
    db.session.commit()
    return zmienione, [ProductionOrder.query.get(o.id).logistics_closed_at is not None
                       for o in zamowienia]


def test_siatka_otwiera_zamkniecia_wbrew_regule(app):
    """Odbiór bez wydania, transport bez trasy, sposób NULL i `repack_required` — zamknięte po wdrożeniu
    4.3, a reguła `zamkniecie_wyliczone` daje False: wszystkie wracają na listę otwartych."""
    with app.app_context():
        _ustaw_znacznik()
        odbior = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',), logistics_closed_at=PO_ZNACZNIKU)
        transport = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',), logistics_closed_at=PO_ZNACZNIKU)
        brak = zamowienie(sposob=None, statusy=('spakowane',), logistics_closed_at=PO_ZNACZNIKU)
        przepakowanie = zamowienie(sposob=s.KURIER, statusy=('spakowane',), logistics_closed_at=PO_ZNACZNIKU,
                                   repack_required=True)
        zmienione, zamkniete = _po_przebiegu([odbior, transport, brak, przepakowanie])
        assert zamkniete == [False] * 4
        assert zmienione == 4   # licznik crona obejmuje zamówienia otwarte siatką


def test_siatka_otwiera_transport_z_pozycja_niedostarczona_na_trasie_wykonanej(app):
    """Krok 4.4 (spec 4.6): transport zamyka „dostarczone”, nie trasa wykonana — zamknięty po znaczniku z pozycją
    niedostarczoną wraca na listę otwartych, także na trasie wykonanej."""
    with app.app_context():
        _ustaw_znacznik()
        order = zamowienie(sposob=s.TRANSPORT, statusy=('dostarczone', 'zaladowane'),
                           logistics_closed_at=PO_ZNACZNIKU)
        _na_trasie(order, 'wykonana')
        zmienione, zamkniete = _po_przebiegu([order])
        assert zamkniete == [False] and zmienione == 1


def test_siatka_zostawia_zamkniecia_zgodne_z_regula(app):
    """Odbiór po wydaniu, transport dostarczony (pozycje „dostarczone”, krok 4.4), kurier w całości spakowany
    i zamówienie z samymi anulowanymi pozycjami (bez aktywnych reguła zamyka, nawet przy sposobie NULL) zostają
    zamknięte."""
    with app.app_context():
        _ustaw_znacznik()
        odebrany = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',), logistics_closed_at=PO_ZNACZNIKU,
                              handed_over_at=PO_ZNACZNIKU)
        dowieziony = zamowienie(sposob=s.TRANSPORT, statusy=('dostarczone',), logistics_closed_at=PO_ZNACZNIKU)
        _na_trasie(dowieziony, 'wykonana')
        kurier = zamowienie(sposob=s.KURIER, statusy=('spakowane',), logistics_closed_at=PO_ZNACZNIKU)
        anulowane = zamowienie(sposob=None, statusy=('anulowane', 'anulowane'), logistics_closed_at=PO_ZNACZNIKU)
        zmienione, zamkniete = _po_przebiegu([odebrany, dowieziony, kurier, anulowane])
        assert zamkniete == [True] * 4
        assert zmienione == 0


@pytest.mark.parametrize('sposob', [None, s.TRANSPORT, s.ODBIOR])
def test_siatka_nie_rusza_zamkniec_z_migracji_etapu_1(app, sposob):
    """Zamknięcie historyczne ma `logistics_closed_at <= znacznik` (migracja etapu 1 idzie przed migracją
    znacznika, `NOW()` w obu) — także gdy wypada w TEJ SAMEJ sekundzie (DATETIME bez ułamków) albo wcześniej.
    Zostaje zamknięte, mimo że sposób nie daje zamknięcia według reguły."""
    with app.app_context():
        _ustaw_znacznik()
        ta_sama_sekunda = zamowienie(sposob=sposob, statusy=('spakowane',), logistics_closed_at=ZNACZNIK)
        wczesniej = zamowienie(sposob=sposob, statusy=('spakowane',),
                               logistics_closed_at=datetime(2026, 9, 25, 8, 0, 0))
        zmienione, zamkniete = _po_przebiegu([ta_sama_sekunda, wczesniej])
        assert zamkniete == [True, True]
        assert zmienione == 0


@pytest.mark.parametrize('sposob', [None, s.TRANSPORT, s.ODBIOR])
def test_siatka_otwiera_to_samo_zamkniete_po_znaczniku(app, sposob):
    """Ten sam przypadek zamknięty 5 minut po znaczniku (kod aplikacji, nie migracja): otwarty."""
    with app.app_context():
        _ustaw_znacznik()
        po = zamowienie(sposob=sposob, statusy=('spakowane',), logistics_closed_at=PO_ZNACZNIKU)
        zmienione, zamkniete = _po_przebiegu([po])
        assert zamkniete == [False]
        assert zmienione == 1


@pytest.mark.parametrize('wartosc', [None, 'to nie data'])
def test_siatka_bez_znacznika_albo_z_nieczytelnym_nic_nie_otwiera(app, wartosc):
    """Brak wiersza `logistyka_weryfikacja_od` (albo nieczytelna data) wyłącza siatkę: `do_otwarcia`
    działa jak dotąd, a zamknięcia wbrew regule zostają."""
    with app.app_context():
        if wartosc is not None:
            _ustaw_znacznik(wartosc)
        odbior = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',), logistics_closed_at=PO_ZNACZNIKU)
        brak = zamowienie(sposob=None, statusy=('spakowane',), logistics_closed_at=PO_ZNACZNIKU)
        zmienione, zamkniete = _po_przebiegu([odbior, brak])
        assert zamkniete == [True, True]
        assert zmienione == 0


def test_siatka_nie_wylacza_dotychczasowych_warunkow(app):
    """Z siatką albo bez: nowa aktywna pozycja w zamkniętym zamówieniu kurierskim dalej je otwiera,
    także gdy zamknięcie jest sprzed znacznika."""
    with app.app_context():
        _ustaw_znacznik()
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',), logistics_closed_at=datetime(2026, 9, 25))
        produkt(order, status='czeka_na_wyciecie')
        db.session.commit()
        zmienione, zamkniete = _po_przebiegu([order])
        assert zamkniete == [False]
        assert zmienione == 1
