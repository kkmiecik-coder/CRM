# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, text

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import bl_sync, dzierzawa
from modules.production.models import ProductionOrder
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401


class FakeBase(object):
    """Podstawka pod get_sync_service(): zapisuje wywołania, odpowiada skryptem."""

    def __init__(self, odpowiedzi=None):
        self.api_key = 'token'
        self.wywolania = []
        self.odpowiedzi = list(odpowiedzi or [])

    def _make_api_request(self, dane):
        import json
        self.wywolania.append((dane['method'], json.loads(dane['parameters'])))
        if self.odpowiedzi:
            return self.odpowiedzi.pop(0)
        return {'status': 'SUCCESS'}


@pytest.fixture()
def base(monkeypatch):
    fake = FakeBase()
    import modules.production.services.sync_service as ss
    monkeypatch.setattr(ss, 'get_sync_service', lambda: fake)
    return fake


def test_wysylka_metody_i_statusu_czysci_znaczniki(app, base):
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, delivery_method='Kurier',
                           bl_delivery_method_pending=True, bl_status_pending_id=417343)
        assert bl_sync.wyslij_zamowienie(order) == 2
        assert base.wywolania == [
            ('setOrderFields', {'order_id': order.baselinker_order_id,
                                'delivery_method': 'Transport WoodPower'}),
            ('setOrderStatus', {'order_id': order.baselinker_order_id, 'status_id': 417343}),
        ]
        assert order.bl_delivery_method_pending is False
        assert order.bl_status_pending_id is None
        assert order.delivery_method == 'Transport WoodPower'


def test_brak_zapytania_gdy_tekst_juz_zgodny(app, base):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, delivery_method='Kurier',
                           bl_delivery_method_pending=True)
        assert bl_sync.wyslij_zamowienie(order) == 0
        assert base.wywolania == [] and order.bl_delivery_method_pending is False


def test_blad_base_zostawia_znacznik(app, base):
    base.odpowiedzi = [{'status': 'ERROR', 'error_message': 'Invalid order_id'}]
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, bl_delivery_method_pending=True)
        bl_sync.wyslij_zamowienie(order)
        assert order.bl_delivery_method_pending is True


def test_limit_base_wstrzymuje_i_zostawia_znaczniki(app, base):
    """Review Focus 2."""
    base.odpowiedzi = [{'status': 'ERROR', 'error_message':
                        'Query limit exceeded, token blocked until 2099-01-01 15:40:05'}]
    with app.app_context():
        a = zamowienie(sposob=s.KURIER, bl_delivery_method_pending=True)
        b = zamowienie(sposob=s.ODBIOR, bl_delivery_method_pending=True)
        wynik = bl_sync.dopychaj(spij=lambda _: None)
        assert wynik['wstrzymane'] is True
        assert bl_sync.wstrzymane_do() == datetime(2099, 1, 1, 15, 40, 5)
        db.session.expire_all()
        assert ProductionOrder.query.get(a.id).bl_delivery_method_pending is True
        assert ProductionOrder.query.get(b.id).bl_delivery_method_pending is True
        assert len(base.wywolania) == 1  # po limicie nie pytamy dalej


def test_limit_na_statusie_nie_gubi_udanej_zmiany_metody(app, base):
    """Fix round 2 (review): jeśli setOrderFields się uda, a zaraz potem setOrderStatus
    trafi w limit Base. (LimitBase), udana zmiana metody MA zostać zastosowana - nie
    zgubiona razem z wyjątkiem z drugiego zapytania. `finally` w wyslij_zamowienie
    stosuje ją PRZED tym, jak dopychaj zacommituje przy obsłudze LimitBase."""
    base.odpowiedzi = [
        {'status': 'SUCCESS'},  # setOrderFields - udane
        {'status': 'ERROR', 'error_message':
         'Query limit exceeded, token blocked until 2099-01-01 15:40:05'},  # setOrderStatus
    ]
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, delivery_method='Kurier DPD',
                           bl_delivery_method_pending=True, bl_status_pending_id=417343)
        order_id = order.id
        wynik = bl_sync.dopychaj(spij=lambda _: None)
        assert wynik['wstrzymane'] is True
        db.session.expire_all()
        odswiezony = ProductionOrder.query.get(order_id)
        assert odswiezony.bl_delivery_method_pending is False  # zmiana metody zastosowana
        assert odswiezony.bl_status_pending_id == 417343  # status nietkniety - limit
        assert odswiezony.delivery_method == 'Transport WoodPower'


def test_brak_zapisu_do_bazy_miedzy_dwoma_wywolaniami_base(app, monkeypatch):
    """Fix round 2 (Important, re-review): między setOrderFields a setOrderStatus nie
    wolno wykonać ŻADNEGO zapisu (UPDATE) do prod_orders - InnoDB blokowałby wiersz
    przez czas DRUGIEGO wywołania (do ~105 s przy retry sync_service), a każda
    transakcja webowa/tabletowa pisząca to samo zamówienie (ustaw_sposob_dostawy,
    wydaj_klientowi, po_spakowaniu) czekałaby do innodb_lock_wait_timeout (50 s) >
    timeout gunicorna (30 s) - WORKER TIMEOUT/502 i zgubiona zmiana użytkownika."""
    zapisy_przed_statusem = []
    podsluchane = []

    class FakeBaseZPodsluchem(FakeBase):
        def _make_api_request(self, dane):
            if dane['method'] == 'setOrderStatus':
                # migawka: ile zapisow do prod_orders padlo, ZANIM ruszylo to zapytanie
                zapisy_przed_statusem.append(len(podsluchane))
            return super()._make_api_request(dane)

    def nasluch(conn, cursor, statement, parameters, context, executemany):
        # startswith('UPDATE'), NIE substring 'UPDATE' in statement — inaczej falszywie
        # dopasowuje SELECT z kolumna "updated_at" (UPDATE_AT zawiera UPDATE jako podciag)
        gorna = statement.strip().upper()
        if gorna.startswith('UPDATE') and 'PROD_ORDERS' in gorna:
            podsluchane.append(statement)

    fake = FakeBaseZPodsluchem()
    import modules.production.services.sync_service as ss
    monkeypatch.setattr(ss, 'get_sync_service', lambda: fake)
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, delivery_method='Kurier DPD',
                           bl_delivery_method_pending=True, bl_status_pending_id=417343)
        engine = db.engine
        event.listen(engine, 'before_cursor_execute', nasluch)
        try:
            zapytania = bl_sync.wyslij_zamowienie(order)
        finally:
            event.remove(engine, 'before_cursor_execute', nasluch)
        assert zapytania == 2
        # w chwili wywolania setOrderStatus baza NIE widziala jeszcze zadnego UPDATE-u
        # do prod_orders - oba UPDATE-y poszly DOPIERO po obu zapytaniach do Base.
        assert zapisy_przed_statusem == [0]
        assert len(podsluchane) == 2


def test_pauza_blokuje_dopychacz(app, base):
    """Review Focus 2."""
    with app.app_context():
        zamowienie(sposob=s.KURIER, bl_delivery_method_pending=True)
        bl_sync.wstrzymaj_do(datetime(2099, 1, 1))
        assert bl_sync.dopychaj(spij=lambda _: None)['wstrzymane'] is True
        assert base.wywolania == []


def test_druga_dzierzawa_jest_odrzucona(app):
    """Review Focus 1: jeden nadawca na cały serwer."""
    with app.app_context():
        teraz = datetime(2026, 9, 25, 12, 0, 0)
        klucz = bl_sync.KLUCZ_DZIERZAWY
        assert dzierzawa.przejmij(klucz, 90, teraz) is not None
        assert dzierzawa.przejmij(klucz, 90, teraz + timedelta(seconds=10)) is None
        # Po wygaśnięciu dzierżawy (proces padł) ktoś inny może ją przejąć.
        assert dzierzawa.przejmij(klucz, 90, teraz + timedelta(seconds=91)) is not None


def test_dzierzawy_o_roznych_kluczach_sa_niezalezne(app):
    with app.app_context():
        teraz = datetime(2026, 9, 25, 12, 0, 0)
        assert dzierzawa.przejmij('logistyka_bl_dzierzawa', 90, teraz)
        assert dzierzawa.przejmij('logistyka_geo_dzierzawa', 90, teraz)


def test_dopychacz_ma_odstep_i_zwalnia_dzierzawe(app, base):
    przerwy = []
    with app.app_context():
        for _ in range(3):
            zamowienie(sposob=s.TRANSPORT, bl_delivery_method_pending=True)
        wynik = bl_sync.dopychaj(spij=przerwy.append)
        assert wynik['zapytania'] == 3
        assert przerwy == [bl_sync.ODSTEP_S] * 3
        assert dzierzawa.przejmij(bl_sync.KLUCZ_DZIERZAWY, 90) is not None  # zwolniona


def test_dopychacz_odstep_proporcjonalny_do_liczby_zapytan(app, base):
    """F1 (review): jedno zamówienie z DWOMA znacznikami (metoda + status) robi dwa
    zapytania z rzędu — odstęp też musi być podwójny, inaczej dwa zapytania w jednym
    obiegu pętli omijają limit Base. (~40/min przy pojedynczym odstępie ODSTEP_S)."""
    przerwy = []
    with app.app_context():
        zamowienie(sposob=s.TRANSPORT, delivery_method='Kurier DPD',
                   bl_delivery_method_pending=True, bl_status_pending_id=417343)
        wynik = bl_sync.dopychaj(spij=przerwy.append)
        assert wynik['zapytania'] == 2
        assert przerwy == [bl_sync.ODSTEP_S * 2]


def test_limit_zapytan_przebiegu(app, base):
    with app.app_context():
        for _ in range(5):
            zamowienie(sposob=s.TRANSPORT, bl_delivery_method_pending=True)
        assert bl_sync.dopychaj(limit_zapytan=2, spij=lambda _: None)['zapytania'] == 2


def test_nieudane_zamowienie_nie_mieli_sie_w_kolko(app, base):
    base.odpowiedzi = [{'status': 'ERROR', 'error_message': 'x'}] * 10
    with app.app_context():
        zamowienie(sposob=s.TRANSPORT, bl_delivery_method_pending=True)
        wynik = bl_sync.dopychaj(spij=lambda _: None)
        assert wynik['zapytania'] == 1


def test_zamowienie_bez_id_base_czysci_znaczniki_bez_zapytania(app, base):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, bl_delivery_method_pending=True)
        order.baselinker_order_id = 0
        assert bl_sync.wyslij_zamowienie(order) == 0
        assert order.bl_delivery_method_pending is False and base.wywolania == []


def test_po_zmianie_uruchamia_dopychacz_w_tle_bez_zapytan_w_zadaniu(app, base, monkeypatch):
    """Timeout gunicorna 30 s: żądanie HTTP nigdy nie czeka na Base."""
    uruchomione = []
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: uruchomione.append(1))
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, bl_delivery_method_pending=True)
        bl_sync.po_zmianie([order.id])
        assert base.wywolania == [] and uruchomione == [1]


def test_po_zmianie_bez_zamowien_nic_nie_robi(app, monkeypatch):
    uruchomione = []
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: uruchomione.append(1))
    with app.app_context():
        bl_sync.po_zmianie([])
        assert uruchomione == []


def test_furtka_kierowcy_ustawia_znaczniki():
    from types import SimpleNamespace as NS
    order = NS(bl_status_pending_id=None)
    bl_sync.oznacz_wyslane(order)
    assert order.bl_status_pending_id == 149763
    bl_sync.oznacz_dostarczone(order)
    assert order.bl_status_pending_id == 149778


# ── F2 (review): błąd połączenia (nie odpowiedź Base.) przerywa cały przebieg ──────

class FakeBaseSiecPada(FakeBase):
    """`_make_api_request` rzuca wyjątkiem (np. timeout sieci) zamiast zwrócić
    odpowiedź — symuluje wyczerpanie prób w prawdziwym `_make_api_request`."""

    def _make_api_request(self, dane):
        import json
        self.wywolania.append((dane['method'], json.loads(dane['parameters'])))
        raise RuntimeError('timeout')


def test_awaria_sieci_przerywa_przebieg_bez_pauzy_i_zwalnia_dzierzawe(app, monkeypatch):
    """F2 (review): błąd sieci/konfiguracji to NIE limit API Base. — nie zapisujemy
    pauzy (`wstrzymane_do` zostaje None), ale dalsze zamówienia w tym przebiegu by
    padły tym samym błędem, więc przerywamy od razu (drugie zamówienie nie jest
    nawet próbowane) i mimo to zwalniamy dzierżawę (nie blokujemy jej na 300 s)."""
    fake = FakeBaseSiecPada()
    import modules.production.services.sync_service as ss
    monkeypatch.setattr(ss, 'get_sync_service', lambda: fake)
    with app.app_context():
        a = zamowienie(sposob=s.KURIER, bl_delivery_method_pending=True)
        b = zamowienie(sposob=s.ODBIOR, bl_delivery_method_pending=True)
        wynik = bl_sync.dopychaj(spij=lambda _: None)
        assert wynik['wstrzymane'] is False
        assert bl_sync.wstrzymane_do() is None
        assert len(fake.wywolania) == 1
        db.session.expire_all()
        assert ProductionOrder.query.get(a.id).bl_delivery_method_pending is True
        assert ProductionOrder.query.get(b.id).bl_delivery_method_pending is True
        assert dzierzawa.przejmij(bl_sync.KLUCZ_DZIERZAWY, 300) is not None  # zwolniona


# ── F3 (review): decyzja nadpisana W TRAKCIE trwania zapytania do Base. ────────────

class FakeBaseZBocznymZapisem(FakeBase):
    """
    Symuluje równoległego aktora (np. stanowisko kierowcy albo logistyka na drugiej
    karcie), który w trakcie trwania NASZEGO zapytania HTTP do Base. zdąży zapisać
    nową decyzję bezpośrednio w bazie (surowy SQL na tej samej sesji — w testach
    współdzielimy połączenie SQLite, więc widzimy zapis od razu, tak jak dwa procesy
    widziałyby się nawzajem po commicie na MySQL). Boczny zapis wykonuje się TYLKO
    przy pierwszym wywołaniu, żeby druga próba w tym samym przebiegu mogła się udać.
    """

    def __init__(self, sql, parametry):
        super().__init__()
        self._sql = sql
        self._parametry = parametry
        self._wykonano = False

    def _make_api_request(self, dane):
        odpowiedz = super()._make_api_request(dane)
        if not self._wykonano:
            self._wykonano = True
            db.session.execute(text(self._sql), self._parametry)
        return odpowiedz


def test_status_nadpisany_w_trakcie_wywolania_nie_jest_kasowany(app, monkeypatch):
    """F3 (review): stanowisko kierowcy ustawia NOWY status (149779) W TRAKCIE, gdy
    dopychacz wysyła STARY (149777) — dopychacz nie może skasować znacznika na None,
    bo nowa decyzja przepadłaby bez wysyłki."""
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, bl_status_pending_id=149777)
        order_id = order.id
        fake = FakeBaseZBocznymZapisem(
            'UPDATE prod_orders SET bl_status_pending_id = 149779 WHERE id = :id',
            {'id': order_id})
        import modules.production.services.sync_service as ss
        monkeypatch.setattr(ss, 'get_sync_service', lambda: fake)
        bl_sync.wyslij_zamowienie(order)
        db.session.commit()
        db.session.expire_all()
        assert ProductionOrder.query.get(order_id).bl_status_pending_id == 149779


def test_metoda_nadpisana_w_trakcie_wywolania_zostaje_znacznik(app, monkeypatch):
    """F3 (review): ktoś zmienia sposób dostawy (na odbiór osobisty) W TRAKCIE, gdy
    dopychacz wysyła 'Kurier' — znacznik `bl_delivery_method_pending` MUSI zostać
    (nowa decyzja czeka na wysyłkę), ale `delivery_method` ma tekst, który FAKTYCZNIE
    poszedł do Base. w tym wywołaniu (nie nowy, nieznany jeszcze Base.)."""
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, delivery_method='Kurier DPD',
                           bl_delivery_method_pending=True)
        order_id = order.id
        fake = FakeBaseZBocznymZapisem(
            "UPDATE prod_orders SET override_delivery_method = 'odbior_osobisty' "
            "WHERE id = :id",
            {'id': order_id})
        import modules.production.services.sync_service as ss
        monkeypatch.setattr(ss, 'get_sync_service', lambda: fake)
        bl_sync.wyslij_zamowienie(order)
        db.session.commit()
        db.session.expire_all()
        odswiezony = ProductionOrder.query.get(order_id)
        assert odswiezony.bl_delivery_method_pending is True
        assert odswiezony.delivery_method == 'Kurier'


def test_dopychacz_wysyla_ponownie_nadpisana_decyzje_w_tym_samym_przebiegu(app, monkeypatch):
    """F3 (review): zamówienie, któremu ktoś nadpisał decyzję W TRAKCIE wysyłki, NIE
    trafia do „pominiętych" na resztę przebiegu (to nie jest porażka Base.) — dopychacz
    próbuje je ponownie od razu, w tym samym przebiegu, z NOWĄ wartością."""
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, bl_status_pending_id=149777)
        order_id = order.id
        fake = FakeBaseZBocznymZapisem(
            'UPDATE prod_orders SET bl_status_pending_id = 149779 WHERE id = :id',
            {'id': order_id})
        import modules.production.services.sync_service as ss
        monkeypatch.setattr(ss, 'get_sync_service', lambda: fake)
        wynik = bl_sync.dopychaj(spij=lambda _: None)
        # pierwsza próba: boczny zapis „wygrywa" (149779), znacznik NIE jest kasowany;
        # druga próba w tym samym przebiegu wysyła już nową wartość i ją kasuje
        assert len(fake.wywolania) == 2
        assert fake.wywolania[0][1]['status_id'] == 149777
        assert fake.wywolania[1][1]['status_id'] == 149779
        assert wynik['zapytania'] == 2
        db.session.expire_all()
        assert ProductionOrder.query.get(order_id).bl_status_pending_id is None


# ── I3b (przegląd gałęzi): świeży znacznik statusu tuż przed setOrderStatus ────────

class FakeBaseInnyProcesCommituje(FakeBase):
    """
    W trakcie setOrderFields INNY proces (tablet pakowania, logistyk) zmienia znacznik
    statusu i COMMITUJE. Zapis idzie osobnym połączeniem (`engine.begin()`), a nie
    przez sesję dopychacza — sesja nic o nim nie wie, więc `order.bl_status_pending_id`
    w pamięci zostaje stary, tak jak w drugim procesie gunicorna na MySQL.
    """

    def __init__(self, sql, parametry):
        super().__init__()
        self._sql = sql
        self._parametry = parametry

    def _make_api_request(self, dane):
        odpowiedz = super()._make_api_request(dane)
        if dane['method'] == 'setOrderFields':
            with db.engine.begin() as polaczenie:
                polaczenie.execute(text(self._sql), self._parametry)
        return odpowiedz


def test_status_wyczyszczony_w_trakcie_setorderfields_nie_jest_wysylany(app, monkeypatch):
    """Sonda P5: przepakowanie na kuriera (znacznik 138620) — pakowacz kończy
    przepakowanie W TRAKCIE setOrderFields (po_spakowaniu czyści 138620, ścieżka
    pakowania wysyła 138623). Znacznik odczytany przed pierwszym wywołaniem HTTP
    wysłałby 138620 PO 138623 i cofnął Base. do „Produkcja zakończona”."""
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',),
                           delivery_method='Transport WoodPower')
        from modules.production.logistics.services import delivery
        delivery.ustaw_sposob_dostawy(order, s.KURIER)
        db.session.commit()
        assert order.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA
        assert order.bl_delivery_method_pending is True
        order_id, blid = order.id, order.baselinker_order_id
        fake = FakeBaseInnyProcesCommituje(
            'UPDATE prod_orders SET bl_status_pending_id = NULL, repack_required = 0 '
            'WHERE id = :id', {'id': order_id})
        import modules.production.services.sync_service as ss
        monkeypatch.setattr(ss, 'get_sync_service', lambda: fake)

        assert bl_sync.wyslij_zamowienie(order) == 1
        db.session.commit()
        assert fake.wywolania == [
            ('setOrderFields', {'order_id': blid, 'delivery_method': 'Kurier'})]
        db.session.expire_all()
        odswiezony = ProductionOrder.query.get(order_id)
        assert odswiezony.bl_status_pending_id is None
        assert odswiezony.bl_delivery_method_pending is False


def test_wysylany_jest_swiezy_status_z_bazy(app, monkeypatch):
    """I3b: znacznik zmieniony w trakcie setOrderFields (149777 → 149779, „Wydane
    klientowi”) — idzie wartość z bazy z chwili tuż przed setOrderStatus, a warunkowe
    czyszczenie porównuje z FAKTYCZNIE wysłaną wartością."""
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',), delivery_method='Kurier DPD',
                           bl_delivery_method_pending=True, bl_status_pending_id=149777)
        order_id, blid = order.id, order.baselinker_order_id
        fake = FakeBaseInnyProcesCommituje(
            'UPDATE prod_orders SET bl_status_pending_id = 149779 WHERE id = :id',
            {'id': order_id})
        import modules.production.services.sync_service as ss
        monkeypatch.setattr(ss, 'get_sync_service', lambda: fake)

        assert bl_sync.wyslij_zamowienie(order) == 2
        db.session.commit()
        assert fake.wywolania[1] == ('setOrderStatus', {'order_id': blid, 'status_id': 149779})
        db.session.expire_all()
        assert ProductionOrder.query.get(order_id).bl_status_pending_id is None
