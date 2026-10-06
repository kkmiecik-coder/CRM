# -*- coding: utf-8 -*-
"""
Pisarze priorytetów — kolejność blokad i zapisów.

1. Przeciąganie priorytetów (`POST /production/api/update-priority`) usunięto w kroku K2 programu „Priorytety
   produkcji” razem z jego testami; zostaje test, że martwe końcówki starego systemu naprawdę zniknęły.
2. `kolejka.utrwal` (priorytety produkcji P1, krok K1) — nowa kolejność blokad: zamówienia → pozycje → zapisy tylko
   zmienionych wierszy; własna sesja, jedno ponowienie po 1213, `db.session` wołającego nietknięta.

ZAKOŃCZ i doróbka trzymają wiersz zamówienia i blokują wszystkie jego pozycje rosnąco po id
(services/blokady_zamowien.py). Pisarz, który zapisuje pozycje w innej kolejności, trzyma pozycję o wyższym id
i czeka na niższą, a ZAKOŃCZ odwrotnie — MySQL 1213. SQLite nie ma blokad, więc pilnujemy kolejności samych
zapytań (tests/blokady_pomocnicze.py): UPDATE zakłada blokadę X na wierszu.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
from datetime import date, datetime

import pytest
from sqlalchemy import event, text

from extensions import db
from modules.production.models import ProductionConfig, ProductionOrder, ProductionProduct
from modules.production.priorytety.models import PriorityLog
from modules.production.priorytety.services import kolejka
from modules.production.services import priority_service
from tests.blokady_pomocnicze import (
    Zapytania, blokada_pozycji_zamowien, blokada_zamowien, id_zapisow_pozycji, zapis,
)
from tests.krawedzie_fixtures import BASE, app, client, produkt  # noqa: F401
from tests.priorytety_fixtures import czyste_ustawienia, drabina_domyslna, zamrozony_dzien  # noqa: F401

pytestmark = pytest.mark.usefixtures('zamrozony_dzien', 'czyste_ustawienia')


# --- Martwe końcówki starego systemu priorytetów (usunięte w krokach K2 i K4a) ---------------------------------
# Przeciąganie (`update-priority`) było ostatnim pisarzem pozycji bez blokady zamówienia w tej grupie; jego testy
# kolejności zapisów zniknęły razem z końcówką. `set-priority` (gwiazdka pozycji) usunął krok K4a razem z jej JS.

MARTWE_KONCOWKI = (
    '/production/api/update-priority',
    '/production/api/products/<int:product_id>/priority',
    '/production/api/products/<int:product_id>/set-manual-priority',
    '/production/api/recalculate-all-priorities',
    '/production/api/priority-statistics',
    '/production/api/set-priority',
)


def test_martwe_koncowki_priorytetow_usuniete(app):
    """Martwe końcówki priorytetów nie istnieją (set-priority usunięte w K4a)."""
    reguly = {r.rule for r in app.url_map.iter_rules()}
    assert reguly.isdisjoint(MARTWE_KONCOWKI)


# --- Jedno ponowienie po MySQL 1213 ---------------------------------------------------------------------------------
# Pisarze rang zapisują pozycje rosnąco po id, a Dostawa blokuje pozycje wielu zamówień w kolejności (zamówienie, id)
# — rzadkie zakleszczenie zostaje możliwe, więc `kolejka.utrwal` ponawia raz (niżej), jak hurt i Dostawa.

def _blad_mysql(kod, komunikat='Deadlock found when trying to get lock'):
    from sqlalchemy.exc import OperationalError
    return OperationalError('UPDATE prod_products SET ...', {}, Exception(kod, komunikat))


# --- kolejka.utrwal: ranga zamówień i pozycji na WŁASNEJ sesji (priorytety produkcji P1, krok K1) ------------------
# Nowy pisarz dwóch tabel: zamówienia FOR UPDATE rosnąco po id → pozycje tych zamówień rosnąco po id → dopiero
# zapisy, i tylko wierszy, które się zmieniają (spec 2026-10-04, sekcje 4.2 i 9.4). Bez tej kolejności dałby 1213
# z ZAKOŃCZ, doróbką i hurtem, które trzymają zamówienie i sięgają po jego pozycje.

def _zamowienie(app, numer, termin, ile=2, status='czeka_na_sklejanie', **kolumny):
    """Zamówienie z `ile` pozycjami w `status` i terminem `termin`. Zwraca (order_id, [id pozycji rosnąco])."""
    pierwsza, _ = produkt(app, status=status, numer=numer, deadline_date=termin, **kolumny)
    with app.app_context():
        wzor = db.session.get(ProductionProduct, pierwsza)
        ids = [pierwsza]
        for sekwencja in range(2, ile + 1):
            pozycja = ProductionProduct(
                order_id=wzor.order_id, configuration_id=wzor.configuration_id,
                short_product_id='%s_%d' % (wzor.short_product_id.split('_')[0], sekwencja),
                product_sequence_in_order=sekwencja, original_product_name='Blat dębowy',
                current_status=status, quantity=1, volume_m3=0.1, parsed_thickness_cm=4.0, deadline_date=termin)
            db.session.add(pozycja)
            db.session.flush()
            ids.append(pozycja.id)
        db.session.commit()
        return wzor.order_id, ids


def _dwa_zamowienia(app):
    """Starsze zamówienie (niższe id) ma PÓŹNIEJSZY termin, więc dostaje rangę 2 — kolejność rang jest odwrotna do
    kolejności id i test kolejności zapisów coś mierzy."""
    drabina_domyslna()
    pozne, pozycje_poznego = _zamowienie(app, '25/00001', date(2026, 11, 20))
    pilne, pozycje_pilnego = _zamowienie(app, '25/00002', date(2026, 11, 10))
    assert pozne < pilne and max(pozycje_poznego) < min(pozycje_pilnego)
    return (pozne, pozycje_poznego), (pilne, pozycje_pilnego)


def _stan(order_ids=(), product_ids=()):
    """Rangi z bazy, świeżym odczytem: ({order_id: (rank, rung)}, {product_id: (rank, is_priority, override)})."""
    db.session.rollback()
    db.session.expire_all()
    zamowienia = {oid: (db.session.get(ProductionOrder, oid).priority_rank,
                        db.session.get(ProductionOrder, oid).priority_rung) for oid in order_ids}
    pozycje = {pid: (db.session.get(ProductionProduct, pid).priority_rank,
                     db.session.get(ProductionProduct, pid).is_priority,
                     db.session.get(ProductionProduct, pid).priority_manual_override) for pid in product_ids}
    return zamowienia, pozycje


def _id_zapisow_zamowien(lista):
    ids = []
    for sql, parametry in lista:
        if sql.startswith('UPDATE prod_orders') and sql.endswith('WHERE prod_orders.id = ?'):
            wiersze = parametry if parametry and isinstance(parametry[0], (list, tuple)) else [parametry]
            ids.extend(wiersz[-1] for wiersz in wiersze)
    return ids


def test_utrwal_blokuje_zamowienia_przed_pozycjami_przed_zapisem(app):
    with app.app_context():
        (pozne, _p1), (pilne, _p2) = _dwa_zamowienia(app)
        with Zapytania() as z:
            raport = kolejka.utrwal()
        assert raport['success'] is True, raport
        blokada_z = z.pierwsze(blokada_zamowien)
        blokada_p = z.pierwsze(blokada_pozycji_zamowien)
        assert blokada_z < blokada_p < z.pierwsze(zapis)
        # jedna blokada zamówień i jedna pozycji, obie rosnąco po id zamówienia
        assert len([1 for sql, _p in z.lista if blokada_zamowien(sql)]) == 1
        assert len([1 for sql, _p in z.lista if blokada_pozycji_zamowien(sql)]) == 1
        assert list(z.lista[blokada_z][1]) == [pozne, pilne]
        assert list(z.lista[blokada_p][1]) == [pozne, pilne]
        # migawka to zwykłe odczyty: przed blokadą zamówień nie ma żadnego odczytu blokującego ani zapisu
        assert not [sql for sql, _p in z.lista[:blokada_z]
                    if sql.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE')) or not sql.startswith('SELECT')]
        # utrwal nie bierze blokady tras ani żadnej innej blokady w prod_config
        assert not [sql for sql, _p in z.lista if 'FROM prod_config' in sql and sql.endswith(' FOR UPDATE')]


def test_utrwal_zapisuje_tylko_zmienione_rosnaco_po_id(app):
    with app.app_context():
        (pozne, pozycje_poznego), (pilne, pozycje_pilnego) = _dwa_zamowienia(app)
        with Zapytania() as z:
            def przy_commicie(conn):
                z.lista.append(('commit', None))

            event.listen(db.engine, 'commit', przy_commicie)
            try:
                raport = kolejka.utrwal()
            finally:
                event.remove(db.engine, 'commit', przy_commicie)
        assert (raport['zamowien'], raport['pozycji']) == (2, 4)
        assert (raport['zmienione_zamowienia'], raport['zmienione_pozycje']) == (2, 4)
        zamowienia, pozycje = _stan([pozne, pilne], pozycje_poznego + pozycje_pilnego)
        assert zamowienia == {pilne: (1, 9), pozne: (2, 9)}
        assert pozycje == {pozycje_pilnego[0]: (101, False, False), pozycje_pilnego[1]: (102, False, False),
                           pozycje_poznego[0]: (201, False, False), pozycje_poznego[1]: (202, False, False)}
        # jeden flush: zamówienia przed pozycjami, każda tabela rosnąco po id (nie w kolejności rang)
        assert _id_zapisow_zamowien(z.lista) == [pozne, pilne]
        assert id_zapisow_pozycji(z.lista) == pozycje_poznego + pozycje_pilnego
        ostatni_zamowien = max(i for i, (sql, _p) in enumerate(z.lista) if sql.startswith('UPDATE prod_orders'))
        pierwszy_pozycji = min(i for i, (sql, _p) in enumerate(z.lista) if sql.startswith('UPDATE prod_products'))
        assert ostatni_zamowien < pierwszy_pozycji
        # od pierwszego zapisu do commitu same zapisy — żadnego odczytu, który rozciąłby flush na dwa
        pierwszy_zapis = z.pierwsze(zapis)
        commit_zapisu = z.lista.index(('commit', None), pierwszy_zapis)
        assert not [sql for sql, _p in z.lista[pierwszy_zapis:commit_zapisu] if sql.startswith('SELECT')]
        # po commicie przebieg kontrolny: same zwykłe odczyty, bez blokad i bez zapisów
        po_commicie = [sql for sql, _p in z.lista[commit_zapisu + 1:] if sql != 'commit']
        assert po_commicie and all(sql.startswith('SELECT') for sql in po_commicie)
        assert not [sql for sql in po_commicie if sql.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))]

        # Zmienia się jedna pozycja pilnego zamówienia: blokada i zapis tylko tego zamówienia.
        db.session.execute(text('UPDATE prod_products SET priority_rank = 999 WHERE id = :id'),
                           {'id': pozycje_pilnego[1]})
        db.session.commit()
        with Zapytania() as z:
            raport = kolejka.utrwal()
        assert (raport['zmienione_zamowienia'], raport['zmienione_pozycje']) == (0, 1)
        assert list(z.lista[z.pierwsze(blokada_zamowien)][1]) == [pilne]
        assert list(z.lista[z.pierwsze(blokada_pozycji_zamowien)][1]) == [pilne]
        assert _id_zapisow_zamowien(z.lista) == []
        assert id_zapisow_pozycji(z.lista) == [pozycje_pilnego[1]]
        assert _stan(product_ids=[pozycje_pilnego[1]])[1] == {pozycje_pilnego[1]: (102, False, False)}


def test_utrwal_bez_zmian_nie_bierze_blokad(app):
    with app.app_context():
        _dwa_zamowienia(app)
        assert kolejka.utrwal()['success'] is True
        with Zapytania() as z:
            raport = kolejka.utrwal()
        assert raport['success'] is True
        assert (raport['zamowien'], raport['pozycji']) == (2, 4)
        assert (raport['zmienione_zamowienia'], raport['zmienione_pozycje']) == (0, 0)
        assert not [sql for sql, _p in z.lista if sql.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))]
        assert not [sql for sql, _p in z.lista if not sql.startswith('SELECT')]


def test_utrwal_zeruje_manual_override_i_podbija_updated_at(app):
    dawno = datetime(2026, 1, 1)
    with app.app_context():
        (pozne, pozycje_poznego), (pilne, pozycje_pilnego) = _dwa_zamowienia(app)
        assert kolejka.utrwal()['success'] is True
        # Ręczne nadpisanie z dawnego algorytmu na pozycji z poprawną już rangą + stara ranga na innej.
        tabela = ProductionProduct.__table__
        db.session.execute(tabela.update().where(tabela.c.id == pozycje_poznego[0])
                           .values(priority_manual_override=True))
        db.session.execute(tabela.update().where(tabela.c.id == pozycje_pilnego[0])
                           .values(priority_rank=5, is_priority=True))
        # zapis poza ORM z jawnym updated_at — onupdate kolumny go nie nadpisze
        db.session.execute(tabela.update().values(updated_at=dawno))
        db.session.commit()

        raport = kolejka.utrwal()

        assert raport['zmienione_pozycje'] == 2
        _zam, pozycje = _stan(product_ids=pozycje_poznego + pozycje_pilnego)
        assert pozycje[pozycje_poznego[0]] == (201, False, False)
        assert pozycje[pozycje_pilnego[0]] == (101, False, False)
        czasy = {pid: db.session.get(ProductionProduct, pid).updated_at
                 for pid in pozycje_poznego + pozycje_pilnego}
        # zmienione pozycje mają świeży updated_at (ETag kolejki starej appki), niezmienione — nietknięty
        assert czasy[pozycje_poznego[0]] > dawno and czasy[pozycje_pilnego[0]] > dawno
        assert czasy[pozycje_poznego[1]] == dawno and czasy[pozycje_pilnego[1]] == dawno


def test_utrwal_nie_dotyka_pozycji_nieaktywnych(app):
    with app.app_context():
        drabina_domyslna()
        zam, (aktywna, spakowana, wstrzymana) = _zamowienie(app, '25/00001', date(2026, 11, 20), ile=3)
        nieaktywne, pozycje_nieaktywnego = _zamowienie(app, '25/00002', date(2026, 11, 1), status='spakowane')
        for pid, status in ((spakowana, 'spakowane'), (wstrzymana, 'wstrzymane')):
            pozycja = db.session.get(ProductionProduct, pid)
            pozycja.current_status, pozycja.priority_rank = status, 7
            pozycja.is_priority, pozycja.priority_manual_override = True, True
        for pid in pozycje_nieaktywnego:
            db.session.get(ProductionProduct, pid).priority_rank = 3
        zamowienie_nieaktywne = db.session.get(ProductionOrder, nieaktywne)
        zamowienie_nieaktywne.priority_rank, zamowienie_nieaktywne.priority_rung = 5, 4
        db.session.commit()

        raport = kolejka.utrwal()

        assert (raport['zamowien'], raport['pozycji']) == (1, 1)
        zamowienia, pozycje = _stan([zam, nieaktywne], [aktywna, spakowana, wstrzymana] + pozycje_nieaktywnego)
        # „Rozpoczęte”: spakowana pozycja + pozycja na Sklejaniu → szczebel tagu (5)
        assert zamowienia == {zam: (1, 5), nieaktywne: (5, 4)}
        assert pozycje[aktywna] == (101, False, False)
        assert pozycje[spakowana] == (7, True, True) and pozycje[wstrzymana] == (7, True, True)
        assert all(pozycje[pid] == (3, False, False) for pid in pozycje_nieaktywnego)


def test_utrwal_pomija_pozycje_ktora_wyszla_z_produkcji_po_migawce(app, monkeypatch):
    """Przypisania idą wyłącznie na obiektach z odczytu blokującego: pozycja spakowana albo skasowana między
    migawką a blokadą nie dostaje rangi (i nie wraca z zaświatów)."""
    with app.app_context():
        drabina_domyslna()
        zam, (pierwsza, spakowana_potem, skasowana_potem) = _zamowienie(app, '25/00001', date(2026, 11, 20), ile=3)
        oryginal = kolejka.policz

        def policz_i_cudzy_zapis(migawka):
            wynik = oryginal(migawka)
            db.session.execute(text("UPDATE prod_products SET current_status = 'spakowane' WHERE id = :id"),
                               {'id': spakowana_potem})
            db.session.execute(text('DELETE FROM prod_products WHERE id = :id'), {'id': skasowana_potem})
            db.session.commit()
            return wynik

        monkeypatch.setattr(kolejka, 'policz', policz_i_cudzy_zapis)
        raport = kolejka.utrwal()

        assert raport['success'] is True, raport
        assert raport['zmienione_pozycje'] == 1
        _zam, pozycje = _stan(product_ids=[pierwsza, spakowana_potem])
        assert pozycje[pierwsza] == (101, False, False)
        assert pozycje[spakowana_potem] == (None, False, False)
        assert db.session.get(ProductionProduct, skasowana_potem) is None


def test_utrwal_po_zapisie_sprawdza_rangi_na_swiezej_migawce(app, monkeypatch):
    """Dwa przeliczenia naraz (przegląd końcowy K1, znalezisko I1). Migawka poprzedza blokady, więc przebieg, który
    zaczął przed cudzą zmianą, zapisuje rangi sprzed niej — a przeliczenie tej zmiany mogło już się skończyć, nie
    znajdując nic do poprawienia. Dlatego po każdym zapisie `utrwal` czyta migawkę od nowa i poprawia różnice, aż
    przebieg kontrolny nie znajdzie żadnej."""
    with app.app_context():
        (pozne, _p1), (pilne, _p2) = _dwa_zamowienia(app)
        oryginal = kolejka.policz
        przebiegi = []

        def policz_z_cudza_zmiana(migawka):
            wynik = oryginal(migawka)
            przebiegi.append(1)
            if len(przebiegi) == 1:
                # po migawce pierwszego przebiegu biuro daje późniejszemu zamówieniu pięć gwiazdek (zatwierdzone)
                tabela = ProductionOrder.__table__
                db.session.execute(tabela.update().where(tabela.c.id == pozne).values(priority_stars=5))
                db.session.commit()
            return wynik

        monkeypatch.setattr(kolejka, 'policz', policz_z_cudza_zmiana)

        raport = kolejka.utrwal()

        assert raport['success'] is True, raport
        # bez przebiegu kontrolnego zostałyby rangi sprzed gwiazdek: pilne (1, 9), późne (2, 9)
        assert _stan([pozne, pilne])[0] == {pozne: (1, 1), pilne: (2, 9)}
        # zapis na starej migawce, poprawka na świeżej, kontrola bez zmian
        assert len(przebiegi) == 3
        assert raport['zamowien'] == 2 and raport['zmienione_zamowienia'] == 4


def test_utrwal_konczy_po_trzech_przebiegach_gdy_stan_ciagle_sie_zmienia(app, monkeypatch):
    """Przebiegów jest najwyżej trzy: gdy dane zmieniają się szybciej, niż `utrwal` nadąża, kończymy z ostrzeżeniem
    w logu — rangi poprawi przeliczenie tej kolejnej zmiany (albo cron). Nigdy pętla bez końca."""
    with app.app_context():
        (pozne, _p1), (pilne, _p2) = _dwa_zamowienia(app)
        oryginal = kolejka.policz
        przebiegi, ostrzezenia = [], []

        def policz_z_ciagla_zmiana(migawka):
            wynik = oryginal(migawka)
            przebiegi.append(1)
            tabela = ProductionOrder.__table__
            db.session.execute(tabela.update().where(tabela.c.id == pozne)
                               .values(priority_stars=5 if len(przebiegi) % 2 else 0))
            db.session.commit()
            return wynik

        class Szpieg(object):
            def warning(self, message, **kwargs):
                ostrzezenia.append(message)

            debug = info = error = lambda self, *a, **k: None

        monkeypatch.setattr(kolejka, 'policz', policz_z_ciagla_zmiana)
        monkeypatch.setattr(kolejka, 'logger', Szpieg())

        raport = kolejka.utrwal()

        assert raport['success'] is True, raport
        assert len(przebiegi) == 3
        assert len(ostrzezenia) == 1


def _szpieg_sesji(monkeypatch):
    """Podgląda `commit()`, `rollback()` i `flush()` na WSPÓŁDZIELONEJ `db.session` (prawdziwy obiekt spod rejestru
    scoped_session — szpieg na klasie nie odróżniłby jej od własnej sesji utrwal)."""
    wolania = []
    sesja = db.session()
    for nazwa in ('commit', 'rollback', 'flush'):
        oryginal = getattr(sesja, nazwa)

        def opakowanie(*a, _oryginal=oryginal, _nazwa=nazwa, **k):
            wolania.append(_nazwa)
            return _oryginal(*a, **k)

        monkeypatch.setattr(sesja, nazwa, opakowanie)
    return wolania


def test_utrwal_nie_commituje_ani_nie_cofa_sesji_wolajacego(app, monkeypatch):
    from modules.production.services import config_service
    with app.app_context():
        (pozne, _p1), (pilne, _p2) = _dwa_zamowienia(app)
        # Praca wołającego: dodana do sesji, niezatwierdzona i niezflushowana.
        praca = ProductionConfig(config_key='praca_wolajacego', config_value='x')
        db.session.add(praca)
        # Zimna pamięć podręczna ustawień: odczyt progu „Blisko terminu” nie może pójść przez db.session
        # (autoflush wypchnąłby pracę wołającego).
        config_service.invalidate_config_cache()
        wolania = _szpieg_sesji(monkeypatch)

        raport = kolejka.utrwal()

        assert raport['success'] is True and raport['zmienione_zamowienia'] == 2
        assert wolania == []
        assert praca in db.session.new
        db.session.rollback()
        assert ProductionConfig.query.filter_by(config_key='praca_wolajacego').count() == 0
        # rollback wołającego nie cofnął rang — poszły własną transakcją
        assert _stan([pozne, pilne])[0] == {pilne: (1, 9), pozne: (2, 9)}


def _sesje_z_bledami(monkeypatch, bledy):
    """Własne sesje `utrwal`: n-ta sesja przy commicie najpierw wypycha zapisy (UPDATE-y idą do bazy, więc rollback
    musi je cofnąć), potem rzuca `bledy[n]` (gdy nie None). Zwraca listę założonych sesji."""
    oryginal = kolejka.nowa_sesja
    sesje = []

    def nowa():
        sesja = oryginal()
        numer = len(sesje)
        sesje.append(sesja)
        if numer < len(bledy) and bledy[numer] is not None:
            def commit():
                sesja.flush()
                raise bledy[numer]
            sesja.commit = commit
        return sesja

    monkeypatch.setattr(kolejka, 'nowa_sesja', nowa)
    return sesje


def test_utrwal_ponawia_raz_po_1213_na_nowej_sesji(app, monkeypatch):
    """Po 1213 rollback i zamknięcie własnej sesji, potem całe przeliczenie od nowa na NOWEJ sesji (stan liczony
    od zera — bez podwójnych skutków: utrwal nie ma skutków poza swoją sesją)."""
    with app.app_context():
        (pozne, _p1), (pilne, _p2) = _dwa_zamowienia(app)
        sesje = _sesje_z_bledami(monkeypatch, [_blad_mysql(1213)])

        raport = kolejka.utrwal()

        assert raport['success'] is True, raport
        assert len(sesje) == 2 and sesje[0] is not sesje[1]
        assert raport['zmienione_zamowienia'] == 2 and raport['error'] is None
        assert _stan([pozne, pilne])[0] == {pilne: (1, 9), pozne: (2, 9)}


def test_utrwal_dwa_1213_bez_zapisow(app, monkeypatch):
    with app.app_context():
        (pozne, pozycje_poznego), (pilne, pozycje_pilnego) = _dwa_zamowienia(app)
        przed = _stan([pozne, pilne], pozycje_poznego + pozycje_pilnego)
        sesje = _sesje_z_bledami(monkeypatch, [_blad_mysql(1213), _blad_mysql(1213)])

        raport = kolejka.utrwal()

        assert raport['success'] is False and len(sesje) == 2
        assert raport['error'] and (raport['zmienione_zamowienia'], raport['zmienione_pozycje']) == (0, 0)
        assert _stan([pozne, pilne], pozycje_poznego + pozycje_pilnego) == przed


def test_utrwal_inny_kod_bez_ponowienia(app, monkeypatch):
    with app.app_context():
        (pozne, _p1), (pilne, _p2) = _dwa_zamowienia(app)
        sesje = _sesje_z_bledami(monkeypatch, [_blad_mysql(1205, 'Lock wait timeout exceeded')])

        raport = kolejka.utrwal()

        assert raport['success'] is False and len(sesje) == 1
        assert _stan([pozne, pilne])[0] == {pilne: (None, None), pozne: (None, None)}


# --- K1-poprawka-1: limit czekania własnej sesji na cudzą blokadę (I2 z przeglądu K1) -------------------------------
# Własna sesja `utrwal` to drugie połączenie tego samego wątku: gdy `db.session` wołającego trzyma niezatwierdzony
# zapis zamówienia, `utrwal` czekałoby na jego blokadę do limitu serwera (50 s). Dlatego pracuje na JEDNYM przypiętym
# połączeniu z krótkim sesyjnym `innodb_lock_wait_timeout`, przywracanym przed oddaniem połączenia do puli. SQLite
# tego ustawienia nie zna, więc testy podglądają funkcję, która je wysyła; na MySQL sprawdza to raport kroku K3.

USTAW_LIMIT = 'SET SESSION innodb_lock_wait_timeout = 5'
PRZYWROC_LIMIT = 'SET SESSION innodb_lock_wait_timeout = DEFAULT'


def _szpieg_limitu(monkeypatch, mysql=True, blad_przywrocenia=None, dziennik=None):
    """Podmienia wysyłkę ustawienia sesji MySQL na zapis do listy (połączenie, SQL). `mysql=True` udaje bazę, która
    zna limit. `dziennik` — lista zapytań (`Zapytania.lista`), do której dopisujemy znacznik w kolejności wykonania."""
    wolania = []
    if mysql:
        monkeypatch.setattr(kolejka, '_ma_limit_czekania', lambda polaczenie: True)

    def wyslij(polaczenie, sql):
        wolania.append((polaczenie, sql))
        if dziennik is not None:
            dziennik.append(('USTAWIENIE ' + sql, None))
        if blad_przywrocenia is not None and sql == PRZYWROC_LIMIT:
            raise blad_przywrocenia

    monkeypatch.setattr(kolejka, '_wyslij_ustawienie', wyslij)
    return wolania


def test_utrwal_ustawia_limit_czekania_na_wlasnym_polaczeniu(app, monkeypatch):
    with app.app_context():
        _dwa_zamowienia(app)
        sesje = _sesje_z_bledami(monkeypatch, [])
        with Zapytania() as z:
            wolania = _szpieg_limitu(monkeypatch, dziennik=z.lista)
            raport = kolejka.utrwal()

        assert raport['success'] is True, raport
        assert len(sesje) == 1
        polaczenie = sesje[0].bind
        # jedno ustawienie i jedno przywrócenie, oba na połączeniu WŁASNEJ sesji
        assert wolania == [(polaczenie, USTAW_LIMIT), (polaczenie, PRZYWROC_LIMIT)]
        # limit obowiązuje od pierwszego zapytania do ostatniego: ustawienie przed wszystkim, przywrócenie po wszystkim
        assert z.lista[0][0] == 'USTAWIENIE ' + USTAW_LIMIT
        assert z.lista[-1][0] == 'USTAWIENIE ' + PRZYWROC_LIMIT
        assert len(z.lista) > 2
        # połączenie wróciło do puli
        assert polaczenie.closed


def test_utrwal_trzyma_jedno_polaczenie_przez_wszystkie_przebiegi(app, monkeypatch):
    """Sesja oddaje połączenie do puli przy każdym commicie i rollbacku — bez przypięcia przebieg kontrolny mógłby
    dostać inne połączenie (bez limitu), a to z limitem wróciłoby do puli między przebiegami."""
    with app.app_context():
        _dwa_zamowienia(app)
        sesje = _sesje_z_bledami(monkeypatch, [])
        uzyte = []

        def zapamietaj(conn, cursor, statement, parameters, context, executemany):
            uzyte.append(conn)

        event.listen(db.engine, 'before_cursor_execute', zapamietaj)
        try:
            raport = kolejka.utrwal()
        finally:
            event.remove(db.engine, 'before_cursor_execute', zapamietaj)

        # zapis (przebieg 1) i kontrola (przebieg 2): dwie transakcje
        assert raport['success'] is True and raport['zmienione_zamowienia'] == 2
        assert uzyte and all(conn is sesje[0].bind for conn in uzyte)


def test_utrwal_1205_bez_ponowienia_i_z_przywroceniem_limitu(app, monkeypatch):
    """Przekroczony limit czekania (MySQL 1205): przeliczenie kończy się od razu `success: False`, bez wyjątku
    i BEZ ponowienia (ponawiamy tylko zakleszczenie 1213) — rangi nadrobi cron. Limit wraca także po błędzie."""
    with app.app_context():
        (pozne, _p1), (pilne, _p2) = _dwa_zamowienia(app)
        sesje = _sesje_z_bledami(monkeypatch, [_blad_mysql(1205, 'Lock wait timeout exceeded; try restarting '
                                                                 'transaction')])
        wolania = _szpieg_limitu(monkeypatch)

        raport = kolejka.utrwal()

        assert raport['success'] is False and raport['error']
        assert len(sesje) == 1
        assert wolania == [(sesje[0].bind, USTAW_LIMIT), (sesje[0].bind, PRZYWROC_LIMIT)]
        assert sesje[0].bind.closed
        assert _stan([pozne, pilne])[0] == {pilne: (None, None), pozne: (None, None)}


def test_utrwal_po_1213_druga_sesja_tez_ma_limit(app, monkeypatch):
    with app.app_context():
        _dwa_zamowienia(app)
        sesje = _sesje_z_bledami(monkeypatch, [_blad_mysql(1213)])
        wolania = _szpieg_limitu(monkeypatch)

        raport = kolejka.utrwal()

        assert raport['success'] is True, raport
        assert len(sesje) == 2 and sesje[0].bind is not sesje[1].bind
        assert wolania == [(sesje[0].bind, USTAW_LIMIT), (sesje[0].bind, PRZYWROC_LIMIT),
                           (sesje[1].bind, USTAW_LIMIT), (sesje[1].bind, PRZYWROC_LIMIT)]
        assert sesje[0].bind.closed and sesje[1].bind.closed


def test_utrwal_nieudane_przywrocenie_uniewaznia_polaczenie(app, monkeypatch):
    """Połączenie, któremu nie udało się przywrócić limitu, nie może wrócić do puli: następne żądanie dostałoby je
    z krótkim limitem czekania. Wynik przeliczenia się nie zmienia."""
    with app.app_context():
        (pozne, _p1), (pilne, _p2) = _dwa_zamowienia(app)
        oryginal = kolejka.nowa_sesja
        uniewaznione = []

        def nowa():
            sesja = oryginal()
            # Bez prawdziwego unieważnienia: testy jadą na jednym połączeniu SQLite w pamięci (StaticPool).
            sesja.bind.invalidate = lambda *a, **k: uniewaznione.append(sesja.bind)
            return sesja

        monkeypatch.setattr(kolejka, 'nowa_sesja', nowa)
        _szpieg_limitu(monkeypatch, blad_przywrocenia=RuntimeError('zerwane polaczenie'))

        raport = kolejka.utrwal()

        assert raport['success'] is True, raport
        assert len(uniewaznione) == 1 and uniewaznione[0].closed
        assert _stan([pozne, pilne])[0] == {pilne: (1, 9), pozne: (2, 9)}


def test_utrwal_bez_limitu_poza_mysql(app, monkeypatch):
    """SQLite testów (i każda baza inna niż MySQL) nie dostaje `SET SESSION` — przeliczenie działa bez limitu."""
    with app.app_context():
        _dwa_zamowienia(app)
        wolania = _szpieg_limitu(monkeypatch, mysql=False)

        raport = kolejka.utrwal()

        assert raport['success'] is True, raport
        assert wolania == []


def test_utrwal_nie_rzuca_przy_bledzie_odczytu(app, monkeypatch):
    with app.app_context():
        _dwa_zamowienia(app)
        oryginal = kolejka.nowa_sesja
        zamkniete = []

        def zepsuta():
            sesja = oryginal()

            def query(*a, **k):
                raise RuntimeError('sztuczna awaria odczytu')
            sesja.query = query
            zamknij = sesja.close
            sesja.close = lambda: (zamkniete.append(1), zamknij())[1]
            return sesja

        monkeypatch.setattr(kolejka, 'nowa_sesja', zepsuta)
        raport = kolejka.utrwal()
        assert raport['success'] is False and 'sztuczna awaria odczytu' in raport['error']
        assert zamkniete, 'wlasna sesja musi byc zamknieta takze po bledzie'

        # nawet gdy nie da się założyć sesji
        def brak_sesji():
            raise RuntimeError('brak polaczen')
        monkeypatch.setattr(kolejka, 'nowa_sesja', brak_sesji)
        raport = kolejka.utrwal()
        assert raport['success'] is False and 'brak polaczen' in raport['error']


def test_nieudane_utrwal_zostawia_db_session_czysta(app, monkeypatch):
    """KANONICZNY test własności „błąd utrwal nie brudzi db.session” (następca testu brudnej sesji dawnego
    kalkulatora z tests/test_priority_statusy_krawedzi.py — znalezisko z 22.09.2026).

    Błąd wstrzyknięty po blokadach, przy commicie własnej sesji: zapisy były już w bazie (flush), rollback własnej
    sesji musi je cofnąć, a `db.session` wołającego nie może dostać ani jednego obiektu."""
    with app.app_context():
        (pozne, pozycje_poznego), (pilne, pozycje_pilnego) = _dwa_zamowienia(app)
        przed = _stan([pozne, pilne], pozycje_poznego + pozycje_pilnego)
        db.session.rollback()
        sesje = _sesje_z_bledami(monkeypatch, [RuntimeError('sztuczna awaria commitu')])
        wolania = _szpieg_sesji(monkeypatch)

        raport = kolejka.utrwal()

        assert raport['success'] is False
        assert 'sztuczna awaria commitu' in raport['error']
        assert len(sesje) == 1
        assert wolania == []
        # Sedno: sesja wołającego jest czysta, a niedokończona zmiana nie czeka na cudzy commit.
        assert list(db.session.new) == []
        assert list(db.session.dirty) == []

    with app.app_context():
        db.session.remove()
        assert _stan([pozne, pilne], pozycje_poznego + pozycje_pilnego) == przed
        assert db.session.get(ProductionOrder, pilne).priority_rank is None
        assert db.session.get(ProductionProduct, pozycje_pilnego[0]).priority_rank is None


def test_utrwal_loguje_przeliczenie_tylko_ze_zrodlem(app):
    with app.app_context():
        _dwa_zamowienia(app)
        assert kolejka.utrwal()['success'] is True                   # cron i wyzwalacze: bez wpisu
        assert PriorityLog.query.count() == 0
        db.session.execute(text('UPDATE prod_orders SET priority_rank = NULL'))
        db.session.commit()
        raport = kolejka.utrwal(zrodlo='panel', user_id=1)           # „Przelicz teraz”
        assert raport['success'] is True and raport['zmienione_zamowienia'] == 2
        wpis = PriorityLog.query.one()
        assert (wpis.action, wpis.note, wpis.new_value, wpis.user_id, wpis.order_id) == (
            'przeliczenie', 'panel', '2', 1, None)
        # ręczne przeliczenie bez zmian też zostawia ślad (kto i kiedy kliknął), ale niczego nie blokuje
        with Zapytania() as z:
            raport = kolejka.utrwal(zrodlo='panel', user_id=1)
        assert raport['zmienione_zamowienia'] == 0
        assert not [sql for sql, _p in z.lista if sql.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))]
        db.session.rollback()
        assert [w.new_value for w in PriorityLog.query.order_by(PriorityLog.id)] == ['2', '0']


def test_utrwal_ostrzezenia_i_ksztalt_raportu(app):
    with app.app_context():
        # baza bez szczebli: drabina domyślna liczona w locie, ostrzeżenia w raporcie
        zam, _pozycje = _zamowienie(app, '25/00001', date(2026, 11, 20))
        raport = kolejka.utrwal()
        assert set(raport) == {'success', 'zamowien', 'pozycji', 'zmienione_zamowienia', 'zmienione_pozycje',
                               'ostrzezenia', 'duration_seconds', 'error'}
        assert raport['success'] is True and raport['error'] is None
        assert len(raport['ostrzezenia']) == 9
        assert isinstance(raport['duration_seconds'], float) and raport['duration_seconds'] >= 0
        assert _stan([zam])[0] == {zam: (1, 9)}


def test_utrwal_trasa_i_gwiazdki_z_bazy(app):
    """Migawka czyta gwiazdki zamówienia i przystanki tras roboczych/zatwierdzonych; trasa załadowana się nie liczy."""
    from modules.production.logistics.models import Route, RouteStop
    from modules.production.priorytety.models import PriorityRung
    with app.app_context():
        drabina_domyslna()
        zwykle, _p = _zamowienie(app, '25/00001', date(2026, 11, 1))
        gwiazdkowe, pg = _zamowienie(app, '25/00002', date(2026, 11, 20))
        z_trasy, _p = _zamowienie(app, '25/00003', date(2026, 11, 25))
        zaladowane, _p = _zamowienie(app, '25/00004', date(2026, 11, 28))
        db.session.get(ProductionOrder, gwiazdkowe).priority_stars = 4
        for numer, (order_id, status, pozycja) in enumerate(
                ((z_trasy, 'zatwierdzona', 0), (zaladowane, 'zaladowana', 3)), start=1):
            trasa = Route(name='Trasa %d' % numer, date_from=date(2026, 11, 2), date_to=date(2026, 11, 2),
                          status=status)
            db.session.add(trasa)
            db.session.flush()
            db.session.add(RouteStop(route_id=trasa.id, order_id=order_id, position=1))
            db.session.add(PriorityRung(kind='route', route_id=trasa.id, position=pozycja))
        db.session.commit()

        raport = kolejka.utrwal()

        assert raport['success'] is True and raport['ostrzezenia'] == []
        zamowienia, pozycje = _stan([zwykle, gwiazdkowe, z_trasy, zaladowane], pg)
        # drabina widoczna: trasa(1), ★5(2), Po terminie(3), ★4(4), …, bez gwiazdek(10); trasa załadowana ukryta
        assert zamowienia == {z_trasy: (1, 1), gwiazdkowe: (2, 4), zwykle: (3, 10), zaladowane: (4, 10)}
        assert pozycje[pg[0]] == (201, True, False)          # gwiazdki ≥ 1 → ramka na tablecie


# --- Warstwa zgodności priority_service (do K8) ---------------------------------------------------------------------

def test_warstwa_zgodnosci_wola_utrwal(app, monkeypatch):
    import modules.production.services as pakiet_serwisow
    with app.app_context():
        (pozne, _p1), (pilne, _p2) = _dwa_zamowienia(app)
        wywolania = []
        oryginal = kolejka.utrwal

        def licznik(*a, **k):
            wywolania.append((a, k))
            return oryginal(*a, **k)

        monkeypatch.setattr(kolejka, 'utrwal', licznik)

        wynik = priority_service.get_priority_calculator().recalculate_all_priorities()

        assert wywolania == [((), {})]
        assert wynik['success'] is True, wynik
        # stare klucze (czyta je sync_service i martwa końcówka panelu) i nowe z raportu utrwal
        assert (wynik['products_updated'], wynik['products_prioritized'], wynik['manual_overrides_preserved']) == (
            4, 4, 0)
        assert (wynik['zmienione_pozycje'], wynik['zamowien'], wynik['zmienione_zamowienia']) == (4, 2, 2)
        assert 'duration_seconds' in wynik and wynik['error'] is None
        assert _stan([pozne, pilne])[0] == {pilne: (1, 9), pozne: (2, 9)}

        assert priority_service.recalculate_all_priorities()['success'] is True
        assert priority_service.recalculate_priorities()['products_updated'] == 0
        assert len(wywolania) == 3
        # nikt nie trafia na stary algorytm przez pakiet serwisów
        assert pakiet_serwisow.get_priority_calculator() is priority_service.get_priority_calculator()
        assert not isinstance(priority_service.get_priority_calculator(), priority_service.NewPriorityCalculator)
        assert pakiet_serwisow.recalculate_priorities()['success'] is True
        assert len(wywolania) == 4


def test_warstwa_zgodnosci_oddaje_porazke_starymi_kluczami(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr(kolejka, 'utrwal', lambda *a, **k: {
            'success': False, 'zamowien': 0, 'pozycji': 0, 'zmienione_zamowienia': 0, 'zmienione_pozycje': 0,
            'ostrzezenia': [], 'duration_seconds': 0.1, 'error': 'sztuczna awaria'})
        wynik = priority_service.recalculate_all_priorities()
        assert wynik['success'] is False and wynik['error'] == 'sztuczna awaria'
        assert wynik['products_updated'] == 0 and wynik['products_processed'] == 0
