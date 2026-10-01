# -*- coding: utf-8 -*-
"""
„Zamówienie najpierw” (logistyka etap 4, krok 4.4a): ZAKOŃCZ i wejście do pakowania na tablecie, druk etykiet
całego zamówienia oraz cron osieroconych blokują wiersz zamówienia przed pozycjami i decydują na odczycie
bieżącym. Pozycje czytamy po `order_id`, więc kolekcja zamówienia po blokadzie ma pozycje dodane po migawce i nie
ma skasowanych, a zablokowane zamówienie i pozycje trzymają się nawzajem silnymi referencjami. Cron logistyki
jedzie fazami w osobnych transakcjach.

SQLite nie ma blokad wierszy ani migawki MySQL. Kolejność blokad sprawdzamy na kolejności zapytań
(tests/blokady_pomocnicze.py), a odczyt bieżący — obiektami zostawionymi w sesji w starym stanie, podczas gdy
w bazie leży już cudzy zapis (surowy UPDATE poza ORM). Stan „migawki” wstrzykujemy przelotką na
mobile_api._resolve_workers: to ostatni krok handlera przed odczytem pozycji, już po commicie
require_device_token (commit wygasza obiekty sesji, więc wcześniej wczytany stan by nie przetrwał).
"""
import gc
import itertools
from datetime import datetime

import pytest
from sqlalchemy.orm.attributes import set_committed_value

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import delivery
from modules.production.models import (
    LabelPrintJob, ProductionConfig, ProductionDevice, ProductionOrder, ProductionProduct)
from modules.production.routers import mobile_api
from modules.production.services import blokady_zamowien, label_print_service
from modules.production.services.mobile_api_service import generate_token
from tests.blokady_pomocnicze import (
    Zapytania, blokada_pozycji, blokada_zamowien, dodaj_pozycje_za_plecami, zapis)
from tests.logistyka_fixtures import BASE, SEKRET_CRONA, app, client, produkt, zamowienie  # noqa: F401

_licznik = itertools.count(1)
_ZAMOWIENIA = ProductionOrder.__table__
_POZYCJE = ProductionProduct.__table__


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    """Spakowanie i wyjście z produkcji planują status Base. po commicie — w testach go nie wysyłamy."""
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


def _naglowki(stanowisko='packaging'):
    """Nagłówki tabletu danego stanowiska. Wołać PRZED przygotowaniem migawki: commit wygasza sesję."""
    device = ProductionDevice(device_id='TAB-BLK-%d' % next(_licznik), device_name='Tablet',
                              station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return {'Authorization': 'Bearer ' + generate_token(device),
            'X-Operation-Id': 'op-blk-%d' % next(_licznik)}


def _zakoncz(client, pozycja_id, naglowki, stanowisko='packaging'):
    return client.post('/api/mobile/orders/%d/complete' % pozycja_id, headers=naglowki,
                       json={'station_code': stanowisko})


def _migawka_przed_zapisem(monkeypatch, order_id, zamowienie_w_bazie=None, pozycje_w_bazie=None):
    """
    Przelotka na mobile_api._resolve_workers: po prawdziwym wywołaniu wczytuje zamówienie i jego pozycje do sesji
    („migawka” żądania), a potem surowym UPDATE zapisuje w bazie cudzą zmianę (`zamowienie_w_bazie` — kolumny
    zamówienia, `pozycje_w_bazie` — {id pozycji: status}). Obiekty w sesji zostają stare: zmianę zobaczy tylko
    odczyt bieżący (populate_existing). Trzymamy je SILNIE do końca testu: identity map sesji jest słaba, a obiekt,
    który z niej zniknie, wczytałby się potem świeży, więc test nie sprawdzałby odczytu bieżącego.
    """
    oryginal = mobile_api._resolve_workers
    trzymane = []

    def przelotka():
        wynik = oryginal()
        order = db.session.get(ProductionOrder, order_id)
        pozycje = list(order.products)
        stare = (order.override_delivery_method, [p.current_status for p in pozycje])
        if zamowienie_w_bazie:
            db.session.execute(_ZAMOWIENIA.update().where(_ZAMOWIENIA.c.id == order_id)
                               .values(**zamowienie_w_bazie))
        for pid, status in (pozycje_w_bazie or {}).items():
            db.session.execute(_POZYCJE.update().where(_POZYCJE.c.id == pid).values(current_status=status))
        assert (order.override_delivery_method, [p.current_status for p in pozycje]) == stare
        trzymane.append((order, pozycje))
        return wynik

    monkeypatch.setattr(mobile_api, '_resolve_workers', przelotka)


def _po_zadaniu(order_id):
    db.session.expire_all()
    return db.session.get(ProductionOrder, order_id)


class _AtrapaDrukarki(object):
    """Gniazdo TCP drukarki bez sieci: zapamiętuje etykiety i to, ile zapytań do bazy poszło do chwili wysyłki."""

    def __init__(self, zapytania):
        self.etykiety = []
        self.zapytania_przy_wysylce = []
        self._zapytania = zapytania

    def sendall(self, dane):
        self.etykiety.append(dane)
        self.zapytania_przy_wysylce.append(len(self._zapytania.lista))

    def close(self):
        pass


# --- Moduł blokad ---------------------------------------------------------------------------------------

def test_zablokuj_zamowienia_rosnaco_bez_pustych_i_brakujacych(app):
    a, b = zamowienie(), zamowienie()
    assert blokady_zamowien.zablokuj_zamowienia([]) == []
    assert blokady_zamowien.zablokuj_zamowienia([None]) == []
    wynik = blokady_zamowien.zablokuj_zamowienia([b.id, a.id, b.id, None, 987654])
    assert [o.id for o in wynik] == sorted([a.id, b.id])


def test_zablokuj_zamowienie_pozycji_czyta_biezaco(app):
    """Zamówienie i pozycje w sesji są nieświeże (migawka), a w bazie leży cudzy zapis — po blokadzie obiekty
    mają wartości z bazy."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'czeka_na_pakowanie'))
    pierwsza, druga = order.products
    assert (order.override_delivery_method, pierwsza.current_status) == (s.KURIER, 'czeka_na_pakowanie')
    db.session.execute(_ZAMOWIENIA.update().where(_ZAMOWIENIA.c.id == order.id)
                       .values(override_delivery_method=s.ODBIOR))
    db.session.execute(_POZYCJE.update().where(_POZYCJE.c.id == pierwsza.id).values(current_status='spakowane'))
    assert (order.override_delivery_method, pierwsza.current_status) == (s.KURIER, 'czeka_na_pakowanie')
    assert blokady_zamowien.zablokuj_zamowienie_pozycji(druga.id) is druga
    assert (order.override_delivery_method, pierwsza.current_status) == (s.ODBIOR, 'spakowane')


def test_zablokuj_zamowienie_pozycji_trzyma_zamowienie_i_pozycje(app):
    """Przyczyna A z wyścigów MySQL (zadanie 3): mapa tożsamości sesji trzyma czyste obiekty SŁABO. Zamówienie
    zablokowane odczytem bieżącym, którego nikt nie trzymał, znikało z sesji, a późniejsze `pozycja.order`
    (po_spakowaniu) czytało je od nowa zwykłym SELECT-em, na MySQL ze starej migawki: ostatnie ZAKOŃCZ zamykało
    cykl odbioru osobistego na sposobie „kurier”. Zablokowane zamówienie i pozycje trzymają się więc nawzajem
    (`pozycja.order`, `order.products`): po zwróceniu samej pozycji i odśmieceniu pamięci dostęp do zamówienia
    i jego pozycji nie wysyła ani jednego zapytania."""
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    order_id = order.id
    pozycje = sorted(p.id for p in order.products)
    db.session.expunge_all()   # sesja pusta: obiekty przeżyją tylko dzięki referencjom zostawionym przez blokadę
    pozycja = blokady_zamowien.zablokuj_zamowienie_pozycji(pozycje[1])
    gc.collect()
    with Zapytania() as z:
        zamowienie_pozycji = pozycja.order
        wszystkie = list(zamowienie_pozycji.products)
        wzajemne = [p.order is zamowienie_pozycji for p in wszystkie]
    assert z.lista == [], z.lista
    assert (zamowienie_pozycji.id, [p.id for p in wszystkie]) == (order_id, pozycje)
    assert wzajemne == [True, True] and pozycja in wszystkie


def test_zablokuj_zamowienie_pozycji_bez_pozycji(app):
    assert blokady_zamowien.zablokuj_zamowienie_pozycji(987654) is None
    assert blokady_zamowien.zablokuj_zamowienie(987654) is None


def test_zablokuj_pozycje_wyrzuca_z_kolekcji_pozycje_skasowane_po_migawce(app):
    """Base. kasuje pozycje na twardo. Kolekcja `order.products` pochodzi z migawki (na MySQL zwykły odczyt po
    blokadzie zamówienia nadal widzi skasowany wiersz), a odczyt blokujący po `order_id` go nie znajduje. Taki
    „duch” liczyłby się w aktywne_produkty, a podbij_pozycje dałoby StaleDataError (500). Po blokadzie kolekcja ma
    tylko istniejące pozycje."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'czeka_na_pakowanie'))
    pierwsza, druga = order.products
    pierwsza_id, druga_id = pierwsza.id, druga.id
    assert [p.id for p in order.products] == [pierwsza_id, druga_id]  # kolekcja wczytana: „migawka”
    db.session.execute(_POZYCJE.delete().where(_POZYCJE.c.id == pierwsza_id))  # cudzy DELETE za plecami ORM
    assert [p.id for p in order.products] == [pierwsza_id, druga_id]  # sesja nadal widzi ducha
    zablokowane = blokady_zamowien.zablokuj_pozycje(order)
    assert [p.id for p in zablokowane] == [druga_id]
    assert [p.id for p in order.products] == [druga_id]
    assert [p.id for p in delivery.aktywne_produkty(order)] == [druga_id]


def test_zablokuj_zamowienie_wyrzuca_z_kolekcji_pozycje_skasowane_po_migawce(app, monkeypatch):
    """Ta sama reguła przez pełną ścieżkę (zamówienie, potem pozycje). SQLite nie ma migawki: po blokadzie
    zamówienia zwykły odczyt kolekcji widzi już skasowany wiersz. Migawkę MySQL (REPEATABLE READ) odtwarzamy
    przelotką: po prawdziwej blokadzie zamówienia kolekcja wraca w stanie sprzed cudzego DELETE."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'czeka_na_pakowanie'))
    pierwsza, druga = order.products
    pierwsza_id, druga_id = pierwsza.id, druga.id
    z_migawki = list(order.products)
    db.session.execute(_POZYCJE.delete().where(_POZYCJE.c.id == pierwsza_id))
    oryginal = blokady_zamowien.zablokuj_zamowienia

    def zamowienia_z_kolekcja_z_migawki(order_ids):
        zamowienia = oryginal(order_ids)
        for zamowienie_ in zamowienia:
            set_committed_value(zamowienie_, 'products', list(z_migawki))
        return zamowienia

    monkeypatch.setattr(blokady_zamowien, 'zablokuj_zamowienia', zamowienia_z_kolekcja_z_migawki)
    assert blokady_zamowien.zablokuj_zamowienie(order.id) is order
    assert [p.id for p in order.products] == [druga_id]


def test_zablokuj_zamowienie_blokuje_i_liczy_pozycje_dodane_po_migawce(app, monkeypatch):
    """Przyczyna B z wyścigów MySQL (zadanie 3): zmiany z Base. dodały pozycję po migawce ZAKOŃCZ, a przed jego
    blokadą zamówienia. Kolekcja `order.products` z migawki jej nie ma, więc lista kluczy z kolekcji nie
    blokowała jej i nie liczyła (zamówienie zamknięte, choć trzecia pozycja czeka na wycięcie). Pozycje czytamy
    po `order_id` odczytem blokującym: trzecia jest w kolekcji i przyszła z tego odczytu (na MySQL FOR UPDATE).
    SQLite nie ma migawki: po blokadzie zamówienia zwykły odczyt kolekcji widziałby już nową pozycję, więc
    migawkę odtwarzamy jak przy pozycjach skasowanych — po prawdziwej blokadzie zamówienia kolekcja wraca w stanie
    sprzed cudzego INSERT-u."""
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    z_migawki = list(order.products)
    ids = sorted(p.id for p in z_migawki)
    trzecia_id = dodaj_pozycje_za_plecami(order.id, 3)
    assert sorted(p.id for p in order.products) == ids   # sesja nie widzi nowej pozycji
    oryginal = blokady_zamowien.zablokuj_zamowienia

    def zamowienia_z_kolekcja_z_migawki(order_ids):
        zamowienia = oryginal(order_ids)
        for zamowienie_ in zamowienia:
            set_committed_value(zamowienie_, 'products', list(z_migawki))
        return zamowienia

    monkeypatch.setattr(blokady_zamowien, 'zablokuj_zamowienia', zamowienia_z_kolekcja_z_migawki)
    with Zapytania() as z:
        assert blokady_zamowien.zablokuj_zamowienie(order.id) is order
    assert [p.id for p in order.products] == ids + [trzecia_id]
    assert order.products[2].current_status == 'czeka_na_wyciecie'
    assert [p.id for p in delivery.aktywne_produkty(order)] == ids + [trzecia_id]
    # Jedyny odczyt pozycji w blokadzie to odczyt blokujący po order_id — z niego przyszła trzecia pozycja.
    odczyty_pozycji = [(sql, parametry) for sql, parametry in z.lista if 'FROM prod_products' in sql]
    assert len(odczyty_pozycji) == 1 and blokada_pozycji(odczyty_pozycji[0][0]), odczyty_pozycji
    assert list(odczyty_pozycji[0][1]) == [order.id]


# --- ZAKOŃCZ i wejście do pakowania ---------------------------------------------------------------------

def test_zakoncz_blokuje_zamowienie_przed_pozycjami_przed_zapisem(app, client):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    order_id = order.id
    pozycje = sorted(p.id for p in order.products)
    naglowki = _naglowki()
    with Zapytania() as z:
        r = _zakoncz(client, pozycje[1], naglowki)
    assert r.status_code == 200, r.get_data()[:300]
    zamowienia, blokada, pierwszy_zapis = z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    assert zamowienia < blokada < pierwszy_zapis
    assert list(z.lista[zamowienia][1]) == [order_id]
    assert list(z.lista[blokada][1]) == [order_id]   # wszystkie pozycje zamówienia, po order_id


def test_ostatnie_zakoncz_decyduje_na_biezacym_sposobie_dostawy(app, client, monkeypatch):
    """Spec 8.7 („Współbieżność”) i 4.6 („Siatka w cronie”): logistyk zmienił w panelu kuriera na odbiór w chwili
    ostatniego ZAKOŃCZ. Na MySQL tablet widział sposób z migawki i zamykał cykl odbioru, którego nikt nie wydał
    (11 z 62 przebiegów). ZAKOŃCZ czyta sposób bieżąco: odbiór czeka na „Wydane klientowi”."""
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    order_id, ostatnia = order.id, order.products[1].id
    naglowki = _naglowki()
    _migawka_przed_zapisem(monkeypatch, order_id, zamowienie_w_bazie={'override_delivery_method': s.ODBIOR})
    r = _zakoncz(client, ostatnia, naglowki)
    assert r.status_code == 200, r.get_data()[:300]
    order = _po_zadaniu(order_id)
    assert order.override_delivery_method == s.ODBIOR
    assert [p.current_status for p in order.products] == ['spakowane', 'spakowane']
    assert order.logistics_closed_at is None


def test_ostatnie_zakoncz_widzi_biezace_statusy_pozostalych_pozycji(app, client, monkeypatch):
    """Dwa tablety kończą ostatnie dwie pozycje zamówienia kurierskiego. Drugi czekał na blokadę zamówienia, a jego
    migawka pokazuje pierwszą pozycję jeszcze w pakowaniu — bez odczytu bieżącego cykl nie zamknąłby się wcale."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'czeka_na_pakowanie'))
    order_id = order.id
    pierwsza, druga = [p.id for p in order.products]
    naglowki = _naglowki()
    _migawka_przed_zapisem(monkeypatch, order_id, pozycje_w_bazie={pierwsza: 'spakowane'})
    r = _zakoncz(client, druga, naglowki)
    assert r.status_code == 200, r.get_data()[:300]
    order = _po_zadaniu(order_id)
    assert [p.current_status for p in order.products] == ['spakowane', 'spakowane']
    assert order.logistics_closed_at is not None


def test_wejscie_do_pakowania_widzi_biezace_statusy_pozostalych_pozycji(app, client, monkeypatch):
    """„Zeszło z produkcji” (logistics_completed_at) zapada przy wejściu OSTATNIEJ pozycji do pakowania — także
    gdy pierwszą przesunął w tej samej chwili inny tablet, a migawka pokazuje ją jeszcze na Krawędziach."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_krawedzie', 'czeka_na_krawedzie'))
    order_id = order.id
    pierwsza, druga = [p.id for p in order.products]
    naglowki = _naglowki('edges')
    _migawka_przed_zapisem(monkeypatch, order_id, pozycje_w_bazie={pierwsza: 'czeka_na_pakowanie'})
    r = _zakoncz(client, druga, naglowki, stanowisko='edges')
    assert r.status_code == 200, r.get_data()[:300]
    order = _po_zadaniu(order_id)
    assert [p.current_status for p in order.products] == ['czeka_na_pakowanie', 'czeka_na_pakowanie']
    assert order.logistics_completed_at is not None


def test_zakoncz_brak_pozycji_404(app, client):
    r = _zakoncz(client, 987654, _naglowki())
    assert r.status_code == 404 and r.get_json()['error'] == 'order_not_found'


# --- Druk etykiet całego zamówienia ---------------------------------------------------------------------

def test_druk_etykiet_zamowienia_blokuje_zamowienie_i_pozycje_przed_zapisem(app, client):
    """Tryb agenta zapisuje pozycje (liczniki wydrukowanych sztuk) jedną po drugiej, w kolejności numeracji etykiet
    (product_sequence_in_order). Doróbka kopiuje sekwencję oryginału, więc ta kolejność nie jest kolejnością id,
    w której ZAKOŃCZ blokuje pozycje: bez wspólnej blokady zamówienia to cykl (MySQL 1213). Druk blokuje więc
    zamówienie i wszystkie pozycje rosnąco, zanim cokolwiek zapisze, a kolejność samych etykiet zostaje ta sama."""
    db.session.add(ProductionConfig(config_key='LABEL_PRINTER_USE_AGENT', config_value='true'))
    order = zamowienie(statusy=())
    trzecia = produkt(order, status='czeka_na_pakowanie', sekwencja=3)   # najniższe id, najwyższa sekwencja
    pierwsza = produkt(order, status='czeka_na_pakowanie', sekwencja=1)
    druga = produkt(order, status='czeka_na_pakowanie', sekwencja=2)
    db.session.commit()
    order_id, bl_id = order.id, order.baselinker_order_id
    kolejnosc_druku = [pierwsza.short_product_id, druga.short_product_id, trzecia.short_product_id]
    naglowki = _naglowki()
    with Zapytania() as z:
        r = client.post('/api/mobile/orders/%d/print-labels' % bl_id, headers=naglowki)
    assert r.status_code == 200 and r.get_json()['success_count'] == 3, r.get_data()[:300]
    zamowienia, blokada, pierwszy_zapis = z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    assert zamowienia < blokada < pierwszy_zapis
    assert list(z.lista[zamowienia][1]) == [order_id]
    assert list(z.lista[blokada][1]) == [order_id]   # wszystkie pozycje zamówienia, po order_id
    zadania = LabelPrintJob.query.order_by(LabelPrintJob.id).all()
    assert [k for k, _ in itertools.groupby(j.short_product_id for j in zadania)] == kolejnosc_druku


def test_druk_etykiet_zamowienia_w_trybie_tcp_nie_blokuje_zamowienia(app, client, monkeypatch):
    """Tryb TCP (LABEL_PRINTER_USE_AGENT wyłączone, domyślny): pętla druku nie robi zapytań, więc zapisy pozycji idą
    w końcowym commicie, w kolejności klucza głównego (jak blokuje ZAKOŃCZ) — cyklu nie ma. Blokada trzymana przez
    druk po sieci (przy niedostępnej drukarce do ok. 6 s) tylko wstrzymywałaby ZAKOŃCZ tego zamówienia, więc
    w tym trybie jej nie bierzemy."""
    order = zamowienie(statusy=())
    produkt(order, status='czeka_na_pakowanie', sekwencja=3)
    produkt(order, status='czeka_na_pakowanie', sekwencja=1)
    produkt(order, status='czeka_na_pakowanie', sekwencja=2)
    db.session.commit()
    bl_id = order.baselinker_order_id
    naglowki = _naglowki()
    z = Zapytania()
    drukarka = _AtrapaDrukarki(z)
    monkeypatch.setattr(label_print_service, '_open_printer_socket', lambda cfg: drukarka)
    with z:
        r = client.post('/api/mobile/orders/%d/print-labels' % bl_id, headers=naglowki)
    assert r.status_code == 200 and r.get_json()['success_count'] == 3, r.get_data()[:300]
    assert len(drukarka.etykiety) == 6  # 3 pozycje po 2 sztuki, wysłane do (atrapy) drukarki
    assert not [sql for sql, _ in z.lista if blokada_zamowien(sql) or blokada_pozycji(sql)]
    # zapisy pozycji dopiero po wysyłce do drukarki (końcowy commit), nie w trakcie druku
    assert max(drukarka.zapytania_przy_wysylce) <= z.pierwsze(zapis)


# --- Cron: przeniesienie osieroconych ---------------------------------------------------------------------

def test_cron_osieroconych_blokuje_zamowienia_przed_zapisem_pozycji(app):
    a = zamowienie(sposob=s.KURIER, statusy=('czeka_na_logistyke',))
    b = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_logistyke'))
    ids = sorted([a.id, b.id])
    with Zapytania() as z:
        assert delivery.przenies_osierocone_z_logistyki() == 2
        db.session.flush()
    zamowienia, blokada, pierwszy_zapis = z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    assert zamowienia < blokada < pierwszy_zapis
    assert list(z.lista[zamowienia][1]) == ids


def test_cron_osieroconych_czyta_pozycje_biezaco(app, monkeypatch):
    """Inny zapis przenosi pierwszą pozycję MIĘDZY odczytem id zamówień a ich blokadą, a sesja trzyma ją jeszcze
    w starym stanie. Cron czyta pozycje bieżąco: nie liczy jej i nie nadpisuje jej updated_at (ETag kolejki
    pakowania)."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_logistyke', 'czeka_na_logistyke'))
    pierwsza, druga = order.products
    pierwsza_id, druga_id = pierwsza.id, druga.id
    cudzy_zapis, teraz = datetime(2026, 10, 1, 11, 0), datetime(2026, 10, 1, 12, 0)
    assert [p.current_status for p in (pierwsza, druga)] == ['czeka_na_logistyke'] * 2  # stan sprzed cudzego zapisu
    oryginal = blokady_zamowien.zablokuj_zamowienia

    def przelotka(order_ids):
        db.session.execute(_POZYCJE.update().where(_POZYCJE.c.id == pierwsza_id)
                           .values(current_status='czeka_na_pakowanie', updated_at=cudzy_zapis))
        assert pierwsza.current_status == 'czeka_na_logistyke'  # w sesji nadal stary stan
        return oryginal(order_ids)

    monkeypatch.setattr(blokady_zamowien, 'zablokuj_zamowienia', przelotka)
    assert delivery.przenies_osierocone_z_logistyki(teraz=teraz) == 1
    db.session.commit()
    db.session.expire_all()
    pierwsza, druga = db.session.get(ProductionProduct, pierwsza_id), db.session.get(ProductionProduct, druga_id)
    assert (pierwsza.current_status, pierwsza.updated_at) == ('czeka_na_pakowanie', cudzy_zapis)
    assert (druga.current_status, druga.updated_at) == ('czeka_na_pakowanie', teraz)


def _przeliczenie_pada(monkeypatch):
    """Ostatnia faza crona (przelicz_otwarte) rzuca wyjątek: cron odpowiada 500 i robi rollback tej fazy."""
    def pada(*a, **k):
        raise RuntimeError('awaria przeliczenia')
    monkeypatch.setattr(delivery, 'przelicz_otwarte', pada)


def test_cron_zapisuje_przeniesienie_osieroconych_mimo_bledu_pozniejszej_fazy(app, client, monkeypatch):
    """Cron jedzie fazami (przeniesienie osieroconych, dostarcz_wydane, przelicz_otwarte), każda w osobnej
    transakcji i każda blokuje zamówienia rosnąco. Jedna transakcja na całość trzymałaby zamówienia fazy
    pierwszej, prosząc o zamówienia drugiej (suma nie jest rosnąca: cykl z hurtową zmianą statusu). Skutek
    uboczny: błąd późniejszej fazy nie cofa wcześniejszej."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_logistyke',))
    order_id = order.id
    _przeliczenie_pada(monkeypatch)
    r = client.post(BASE + '/cron', headers={'X-Cron-Secret': SEKRET_CRONA})
    assert r.status_code == 500 and r.get_json()['success'] is False
    db.session.expire_all()
    assert [p.current_status for p in db.session.get(ProductionOrder, order_id).products] == ['czeka_na_pakowanie']


def test_cron_zapisuje_dostarcz_wydane_mimo_bledu_pozniejszej_fazy(app, client, monkeypatch):
    """Druga faza (dostarcz_wydane) też kończy się własnym commitem, razem ze znacznikiem jednorazowości."""
    order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',), handed_over_at=datetime(2026, 9, 20))
    order_id = order.id
    _przeliczenie_pada(monkeypatch)
    r = client.post(BASE + '/cron', headers={'X-Cron-Secret': SEKRET_CRONA})
    assert r.status_code == 500 and r.get_json()['success'] is False
    db.session.expire_all()
    assert [p.current_status for p in db.session.get(ProductionOrder, order_id).products] == ['dostarczone']
    assert ProductionConfig.query.filter_by(config_key=delivery.KLUCZ_WYDANE_DOSTARCZONE).count() == 1


# --- kod_mysql: kod błędu MySQL z OperationalError (jedno ponowienie hurtu po 1213) ----------------------------

def test_kod_mysql_zwraca_kod_z_orig():
    from sqlalchemy.exc import OperationalError
    blad = OperationalError('UPDATE prod_orders SET ...', {}, Exception(1213, 'Deadlock found'))
    assert blokady_zamowien.kod_mysql(blad) == 1213


@pytest.mark.parametrize('blad', [
    ValueError('to nie błąd bazy'),                           # brak `orig`
    type('Bez', (Exception,), {'orig': None})(),              # `orig` pusty
    type('Pusty', (Exception,), {'orig': Exception()})(),     # `orig` bez argumentów
])
def test_kod_mysql_bez_kodu_zwraca_none(blad):
    assert blokady_zamowien.kod_mysql(blad) is None
