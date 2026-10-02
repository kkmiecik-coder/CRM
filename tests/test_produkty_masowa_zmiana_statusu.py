# -*- coding: utf-8 -*-
"""
Masowa zmiana statusu produktów.

Dziś ten endpoint NIE MA żadnej walidacji — przypisuje surowy string
z requestu do product.current_status (products_api.py:1286) — a
db.session.commit() stoi POZA pętlą try (:1316). Enum SQLAlchemy nie sprawdza
wartości po stronie Pythona przy ZAPISIE (validate_strings domyślnie False),
więc błąd nie pojawia się w kodzie, tylko w bazie: po zwężeniu enuma
(czeka_na_wykanczanie -> czeka_na_krawedzie) wysłanie starego statusu wywala
na MySQL-u CAŁY batch błędem 1265 (Data truncated), łącznie z pozycjami,
które w ogóle nie były problemem.

Na SQLite Enum ma create_constraint=False (domyślne w SQLAlchemy 1.4), więc
baza nic nie sprawdzi — sprawdzone na kontenerze: dziś taki request kończy
się HTTP 200 i processed_count=1. Właśnie dlatego walidacja musi siedzieć
w kodzie i mieć własny test.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import gc
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from modules.production.models import ProductionProduct
from tests.blokady_pomocnicze import Zapytania, blokada_pozycji, blokada_zamowien
from tests.krawedzie_fixtures import BASE, app, client, produkt  # noqa: F401


def _masowo(client, ids, status):
    return client.post(BASE + '/products/bulk-action', json={
        'action': 'update_status',
        'product_ids': ids,
        'parameters': {'new_status': status},
    })


def test_nieznany_status_odrzucony_przed_zapisem(client, app):
    pid, _ = produkt(app, status='czeka_na_krawedzie')
    r = _masowo(client, [pid], 'czeka_na_wykanczanie')
    assert r.status_code == 400, r.get_data()[:500]
    assert r.get_json()['success'] is False
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_krawedzie'


def test_jeden_zly_status_nie_psuje_calego_batcha(client, app):
    """Walidacja stoi PRZED pętlą — żadna pozycja nie zostaje ruszona."""
    a, _ = produkt(app, status='czeka_na_krawedzie', numer='25/00001')
    b, _ = produkt(app, status='czeka_na_krawedzie', numer='25/00002')
    r = _masowo(client, [a, b], 'zupelnie_nieistniejacy_status')
    assert r.status_code == 400
    with app.app_context():
        for pid in (a, b):
            assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_krawedzie'


def test_status_krawedzi_przechodzi(client, app):
    pid, _ = produkt(app, status='czeka_na_formatowanie')
    r = _masowo(client, [pid], 'czeka_na_krawedzie')
    assert r.status_code == 200, r.get_data()[:500]
    assert r.get_json()['processed_count'] == 1
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_krawedzie'


def test_status_lakierni_przechodzi(client, app):
    pid, _ = produkt(app, status='czeka_na_formatowanie')
    r = _masowo(client, [pid], 'czeka_na_lakiernie')
    assert r.status_code == 200, r.get_data()[:500]
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_lakiernie'


def test_inne_akcje_nie_wymagaja_statusu(client, app):
    """Walidacja obowiązuje wyłącznie akcję update_status."""
    pid, _ = produkt(app)
    r = client.post(BASE + '/products/bulk-action', json={
        'action': 'update_priority',
        'product_ids': [pid],
        'parameters': {'new_priority': 42},
    })
    assert r.status_code == 200, r.get_data()[:500]
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).priority_rank == 42


@pytest.mark.parametrize('status', ['zweryfikowane', 'zaladowane', 'dostarczone'])
def test_statusow_logistyki_nie_ustawia_sie_recznie(client, app, status):
    """Spec 8.6: nowe statusy nadaje tylko logistyka — hurtowa zmiana ich nie oferuje."""
    pid, _ = produkt(app, status='czeka_na_pakowanie')
    r = _masowo(client, [pid], status)
    assert r.status_code == 400
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_pakowanie'


def test_reczna_zmiana_statusu_wola_regule_uniewaznienia(client, app, monkeypatch):
    from modules.production.logistics.services import weryfikacja
    wolania = []
    monkeypatch.setattr(weryfikacja, 'uniewaznij_etapy',
                        lambda order, teraz, powod, **k: wolania.append((order.id, powod)) or False)
    pid, _ = produkt(app, status='spakowane')
    assert _masowo(client, [pid], 'czeka_na_pakowanie').status_code == 200
    with app.app_context():
        order_id = db.session.get(ProductionProduct, pid).order_id
    assert wolania == [(order_id, u'zmiana statusu w panelu')]


def test_reczna_zmiana_statusu_uniewaznia_zamowienia_w_stalej_kolejnosci(client, app, monkeypatch):
    """
    Reguła unieważniania zapisuje wiersz zamówienia i bierze blokady paczek, więc dwa równoległe
    hurtowe zapisy na nakładających się zamówieniach muszą je brać w tej samej kolejności
    (rosnące id), niezależnie od kolejności product_ids w żądaniu — inaczej MySQL 1213.
    """
    from modules.production.logistics.services import weryfikacja
    wolania = []
    monkeypatch.setattr(weryfikacja, 'uniewaznij_etapy',
                        lambda order, teraz, powod, **k: wolania.append(order.id) or False)
    pids = [produkt(app, status='spakowane', numer='25/0010{}'.format(n))[0] for n in range(6)]
    # Żądanie w odwrotnej kolejności niż powstawały zamówienia.
    assert _masowo(client, list(reversed(pids)), 'czeka_na_pakowanie').status_code == 200
    with app.app_context():
        id_zamowien = sorted(db.session.get(ProductionProduct, pid).order_id for pid in pids)
    assert wolania == id_zamowien


def test_hurt_do_produkcji_uniewaznia_etapy_prawdziwa_regula(client, app):
    """
    Styk zadań (fala końcowa 4.3, F6a): hurtowa zmiana statusu z PRAWDZIWĄ regułą unieważnienia etapów,
    bez podmiany `uniewaznij_etapy`. Zamówienie ma dwie pozycje 'zweryfikowane', zadeklarowane i sprawdzone
    paczki. Hurt cofa jedną pozycję do produkcji: paczki tracą ważność, zamówienie traci weryfikację,
    druga pozycja wraca do 'spakowane' i zostaje wpis logu reguły.
    """
    from datetime import datetime

    from modules.production.logistics import sposoby
    from modules.production.logistics.models import LogisticsLog
    from modules.production.models import LabelPrintJob, ProductionOrder, ProductionPackage
    chwila = datetime(2026, 10, 1, 8, 0)
    with app.app_context():
        # Tych tabel nie zakłada wspólny zestaw tego modułu testów (reguła zapisuje log i paczki).
        db.metadata.create_all(bind=db.engine, tables=[
            LogisticsLog.__table__, ProductionPackage.__table__, LabelPrintJob.__table__])
    pierwsza_id, _ = produkt(app, status='zweryfikowane', numer='25/00301')
    with app.app_context():
        pierwsza = db.session.get(ProductionProduct, pierwsza_id)
        order = pierwsza.order
        druga = ProductionProduct(
            order_id=order.id, short_product_id='2500301_2', product_sequence_in_order=2,
            original_product_name='Blat dębowy', current_status='zweryfikowane', quantity=1, volume_m3=0.1)
        db.session.add(druga)
        order.override_delivery_method = sposoby.KURIER
        order.verified_at, order.verified_by_worker_id = chwila, 7
        order.packages_declared_at, order.logistics_closed_at = chwila, chwila
        db.session.add_all([ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=chwila,
                                              verified_at=chwila, verified_method='skan')
                            for i in (1, 2)])
        db.session.commit()
        order_id, druga_id = order.id, druga.id

    r = _masowo(client, [pierwsza_id], 'czeka_na_pakowanie')
    assert r.status_code == 200, r.get_data()[:500]
    assert r.get_json()['processed_count'] == 1

    with app.app_context():
        order = db.session.get(ProductionOrder, order_id)
        assert db.session.get(ProductionProduct, pierwsza_id).current_status == 'czeka_na_pakowanie'
        assert db.session.get(ProductionProduct, druga_id).current_status == 'spakowane'   # wraca ze zweryfikowanych
        paczki = ProductionPackage.query.filter_by(order_id=order_id).all()
        assert len(paczki) == 2 and all(p.voided_at is not None for p in paczki)
        assert order.verified_at is None and order.verified_by_worker_id is None
        assert order.packages_declared_at is None
        assert order.logistics_closed_at is None          # kurier nie jest już w całości po spakowaniu
        wpisy = {w.action: w for w in LogisticsLog.query.filter_by(order_id=order_id)}
        assert set(wpisy) == {'weryfikacja_cofnieta', 'paczki'}
        assert wpisy['weryfikacja_cofnieta'].note == u'zmiana statusu w panelu'
        assert wpisy['weryfikacja_cofnieta'].user_id == 1


# --- Hurt blokuje zamówienia przed pozycjami i czyta je bieżąco (fala końcowa 4.3, F9) -------------------
# SQLite nie ma migawki ani blokad wierszy, więc „tuż przed żądaniem” odtwarzamy jak
# tests/weryfikacja_pomocnicze.py: obiekty zostają w sesji w starym stanie, a w bazie ktoś inny (Weryfikacja)
# zapisał nowy — surowymi UPDATE poza ORM. Kolejność blokad pilnuje test na kolejności zapytań.

def _zamowienie_z_dwiema_pozycjami(app, numer, status='spakowane'):
    """(id_zamowienia, id_pierwszej, id_drugiej); kurier, dwie pozycje, dwie niesprawdzone paczki."""
    from datetime import datetime

    from modules.production.logistics import sposoby
    from modules.production.logistics.models import LogisticsLog
    from modules.production.models import LabelPrintJob, ProductionPackage
    chwila = datetime(2026, 10, 1, 8, 0)
    with app.app_context():
        # Tych tabel nie zakłada wspólny zestaw tego modułu testów (reguła zapisuje log i paczki).
        db.metadata.create_all(bind=db.engine, tables=[
            LogisticsLog.__table__, ProductionPackage.__table__, LabelPrintJob.__table__])
    pierwsza_id, _ = produkt(app, status=status, numer=numer)
    with app.app_context():
        pierwsza = db.session.get(ProductionProduct, pierwsza_id)
        order = pierwsza.order
        druga = ProductionProduct(
            order_id=order.id, short_product_id=numer.replace('/', '') + '_2', product_sequence_in_order=2,
            original_product_name='Blat dębowy', current_status=status, quantity=1, volume_m3=0.1)
        db.session.add(druga)
        order.override_delivery_method = sposoby.KURIER
        order.packages_declared_at = chwila
        db.session.add_all([ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=chwila)
                            for i in (1, 2)])
        db.session.commit()
        return order.id, pierwsza_id, druga.id


def test_hurt_czyta_zamowienie_biezaco_weryfikacja_zatwierdzona_tuz_przed_zadaniem(client, app):
    """Weryfikacja zatwierdziła się tuż przed żądaniem hurtu, a pozycje w sesji mają jeszcze stary stan
    ('spakowane'). Po hurcie zamówienie nie może zostać z `verified_at` przy pozycji w pakowaniu: weryfikacja
    czyszczona, paczki unieważnione, wpis `weryfikacja_cofnieta`.

    Zamówienia test NIE trzyma przez wywołanie hurtu (jak w produkcji, gdzie nikt go nie trzyma). Dawniej trzymał je
    w zmiennej, a to maskowało błąd: zamówienie zablokowane w hurcie przeżywało w mapie tożsamości tylko dzięki
    testowi, więc `p.order` nie czytało go od nowa zwykłym SELECT-em (na MySQL — z migawki sprzed blokady).
    Sam mechanizm (zero zwykłych odczytów zamówienia przed decyzją) sprawdza
    test_hurt_decyduje_na_zablokowanych_zamowieniach_bez_ponownego_odczytu."""
    from datetime import datetime

    from modules.production.logistics.models import LogisticsLog
    from modules.production.models import ProductionOrder, ProductionPackage
    chwila = datetime(2026, 10, 1, 8, 0)
    order_id, pierwsza_id, druga_id = _zamowienie_z_dwiema_pozycjami(app, '25/00302')

    order = db.session.get(ProductionOrder, order_id)                 # „migawka” żądania
    assert order.verified_at is None
    pozycje = list(order.products)                                    # pozycje zostają w sesji w starym stanie
    assert [p.current_status for p in pozycje] == ['spakowane', 'spakowane']
    db.session.execute(ProductionOrder.__table__.update().where(ProductionOrder.__table__.c.id == order_id)
                       .values(verified_at=chwila, verified_by_worker_id=7))
    db.session.execute(ProductionProduct.__table__.update()
                       .where(ProductionProduct.__table__.c.order_id == order_id)
                       .values(current_status='zweryfikowane'))
    db.session.execute(ProductionPackage.__table__.update()
                       .where(ProductionPackage.__table__.c.order_id == order_id)
                       .values(verified_at=chwila, verified_method='skan'))
    assert order.verified_at is None                                  # obiekt w sesji nadal stary
    assert [p.current_status for p in pozycje] == ['spakowane', 'spakowane']
    del order
    gc.collect()
    assert not [o for o in db.session.identity_map.values() if isinstance(o, ProductionOrder)]  # nic nie maskuje

    r = _masowo(client, [pierwsza_id], 'czeka_na_pakowanie')
    assert r.status_code == 200, r.get_data()[:500]
    assert r.get_json()['processed_count'] == 1

    db.session.expire_all()
    order = db.session.get(ProductionOrder, order_id)
    assert order.verified_at is None and order.verified_by_worker_id is None
    assert order.packages_declared_at is None
    assert db.session.get(ProductionProduct, pierwsza_id).current_status == 'czeka_na_pakowanie'
    assert db.session.get(ProductionProduct, druga_id).current_status == 'spakowane'   # z 'zweryfikowane'
    paczki = ProductionPackage.query.filter_by(order_id=order_id).all()
    assert len(paczki) == 2 and all(p.voided_at is not None for p in paczki)
    assert sorted(w.action for w in LogisticsLog.query.filter_by(order_id=order_id)) == \
        ['paczki', 'weryfikacja_cofnieta']


def test_hurt_blokuje_zamowienia_posortowane_przed_pozycjami_i_przed_pierwszym_zapisem(client, app):
    """Kolejność blokad jak w Weryfikacji: zamówienia (rosnące id) → wszystkie pozycje każdego zamówienia po
    `order_id` (blokady_zamowien.zablokuj_pozycje, zamówienia rosnąco) → dopiero pierwszy zapis. Blokowane są
    wszystkie pozycje zamówienia, nie tylko zaznaczone: reguła unieważniania i przeliczenie zamknięcia decydują na
    całym składzie zamówienia. SQLite pomija FOR UPDATE, więc pilnujemy kolejności samych zapytań."""
    trojka = [_zamowienie_z_dwiema_pozycjami(app, '25/0040{}'.format(n)) for n in range(3)]
    id_zamowien = sorted(t[0] for t in trojka)
    wybrane = [t[1] for t in reversed(trojka)]       # żądanie w odwrotnej kolejności niż powstawały

    with Zapytania() as z:
        assert _masowo(client, wybrane, 'czeka_na_pakowanie').status_code == 200

    zamowienia, pierwszy_zapis = z.pierwsze(blokada_zamowien), z.pierwsze(lambda q: q.startswith('UPDATE prod_'))
    pozycje = [i for i, (sql, _p) in enumerate(z.lista) if blokada_pozycji(sql) and i < pierwszy_zapis]
    assert pozycje and zamowienia < pozycje[0]
    assert list(z.lista[zamowienia][1]) == id_zamowien                     # zamówienia w kolejności rosnących id
    assert [list(z.lista[i][1]) for i in pozycje] == [[o] for o in id_zamowien]   # pozycje zamówienie po zamówieniu


def test_hurt_decyduje_na_zablokowanych_zamowieniach_bez_ponownego_odczytu(client, app, monkeypatch):
    """Przyczyna A z wyścigów MySQL (zadanie 3), tu w hurcie. Zamówienia blokowane odczytem bieżącym ginęły z sesji
    (mapa tożsamości trzyma czyste obiekty SŁABO, a wyniku blokady nikt nie trzymał), więc `p.order` przed regułą
    unieważniania i przeliczeniem zamknięcia czytało zamówienie od nowa zwykłym SELECT-em — na MySQL z migawki
    sprzed blokady, a `order.products` leniwie (pozycje niezaznaczone też z migawki). Przykład: deklaracja paczek
    zatwierdzona tuż przed hurtem zostawała nieunieważniona. Test nie trzyma ani zamówienia, ani pozycji. Przed
    decyzją jedynym odczytem zamówień jest ich blokada, a przy decyzji reguły i przeliczenia zamknięcia stan
    zamówienia i wszystkich jego pozycji jest już w pamięci (zero zapytań)."""
    from modules.production.logistics.models import LogisticsLog
    from modules.production.logistics.services import delivery, weryfikacja
    from modules.production.models import ProductionOrder, ProductionPackage
    order_id, pierwsza_id, druga_id = _zamowienie_z_dwiema_pozycjami(app, '25/00303')
    db.session.expunge_all()
    gc.collect()
    decyzje, os_czasu = [], []

    def szpieg(nazwa, oryginal):
        def opakowanie(order, *args, **kwargs):
            pozycja_na_osi = len(os_czasu[0].lista)
            with Zapytania() as przy_decyzji:
                stan = (order.id, order.packages_declared_at is not None,
                        [(p.id, p.current_status) for p in order.products])
            decyzje.append((nazwa, stan, przy_decyzji.lista, pozycja_na_osi))
            return oryginal(order, *args, **kwargs)
        return opakowanie

    monkeypatch.setattr(weryfikacja, 'uniewaznij_etapy', szpieg('regula', weryfikacja.uniewaznij_etapy))
    monkeypatch.setattr(delivery, 'przelicz_zamkniecie', szpieg('zamkniecie', delivery.przelicz_zamkniecie))
    with Zapytania() as z:
        os_czasu.append(z)
        r = _masowo(client, [pierwsza_id], 'czeka_na_pakowanie')
    assert r.status_code == 200, r.get_data()[:500]
    assert [d[0] for d in decyzje] == ['regula', 'zamkniecie']
    odczyty_zamowien = [sql for sql, _p in z.lista[:decyzje[0][3]]
                        if sql.startswith('SELECT') and 'FROM prod_orders' in sql]
    assert odczyty_zamowien and all(blokada_zamowien(sql) for sql in odczyty_zamowien), odczyty_zamowien
    for nazwa, _stan, zapytania_przy_decyzji, _poz in decyzje:
        assert zapytania_przy_decyzji == [], (nazwa, zapytania_przy_decyzji)   # stan już w pamięci, bez odczytu
    assert decyzje[0][1] == (order_id, True, [(pierwsza_id, 'czeka_na_pakowanie'), (druga_id, 'spakowane')])

    db.session.expire_all()
    order = db.session.get(ProductionOrder, order_id)
    assert order.packages_declared_at is None and order.logistics_closed_at is None
    assert all(p.voided_at is not None for p in ProductionPackage.query.filter_by(order_id=order_id))
    assert [w.action for w in LogisticsLog.query.filter_by(order_id=order_id)] == ['paczki']


def test_hurt_nieistniejace_pozycje_daja_404_jak_dotad(client, app):
    r = _masowo(client, [987654], 'czeka_na_pakowanie')
    assert r.status_code == 404 and r.get_json()['success'] is False


# --- Jedno automatyczne ponowienie po zakleszczeniu 1213 (krok 4.4a, runda 5) ---------------------------------
# Ścieżki spoza zasady „zamówienie najpierw” (ręczna synchronizacja z force_update) mogą rzadko zakleszczyć hurt.
# Hurt powtarza więc cały zapis najwyżej raz i tylko po 1213, tym samym wzorem co zmiana sposobu dostawy w panelu
# (tests/test_logistyka_zmiana_spakowanego.py, I1b). Drugie 1213 i każdy inny błąd kończą się 500 z rollbackiem
# (zewnętrzny `except Exception` w `bulk_action`), więc apka testowa nie potrzebuje własnego handlera.

def _blad_mysql(kod, komunikat):
    from sqlalchemy.exc import OperationalError
    return OperationalError('UPDATE prod_products SET ...', {}, Exception(kod, komunikat))


def _scenariusz(monkeypatch, wyniki):
    """Podmienia `weryfikacja.uniewaznij_etapy`: n-te wywołanie najpierw wykonuje PRAWDZIWĄ regułę (jej zapisy
    zostają w sesji, więc rollback musi je cofnąć), a potem rzuca `wyniki[n]`, gdy to wyjątek. Poza listą działa
    normalnie. Zwraca listę (id zamówienia, user_id, czy zamówienie MA deklarację paczek w chwili wejścia do
    reguły) z kolejnych wywołań: druga próba po rollbacku startuje ze stanu sprzed pierwszej, więc deklaracja
    jest przy wejściu tak samo jak za pierwszym razem."""
    from modules.production.logistics.services import weryfikacja
    oryginal = weryfikacja.uniewaznij_etapy
    wywolania = []

    def falszywa(order, teraz, powod, **kwargs):
        przy_wejsciu = (order.id, kwargs.get('user_id'), order.packages_declared_at is not None)
        wynik = oryginal(order, teraz, powod, **kwargs)
        numer = len(wywolania)
        wywolania.append(przy_wejsciu)
        if numer < len(wyniki) and wyniki[numer] is not None:
            raise wyniki[numer]
        return wynik
    monkeypatch.setattr(weryfikacja, 'uniewaznij_etapy', falszywa)
    return wywolania


def _stan_zamowienia(order_id):
    """(statusy pozycji, paczki: unieważnione?, akcje logu) ze świeżego odczytu bazy."""
    from modules.production.logistics.models import LogisticsLog
    from modules.production.models import ProductionOrder, ProductionPackage
    db.session.rollback()   # świeży odczyt, bez migawki z poprzedniego żądania
    statusy = [p.current_status for p in db.session.get(ProductionOrder, order_id).products]
    paczki = [p.voided_at is not None for p in ProductionPackage.query.filter_by(order_id=order_id)]
    akcje = sorted(w.action for w in LogisticsLog.query.filter_by(order_id=order_id))
    return statusy, paczki, akcje


def test_hurt_ponawia_raz_po_1213_i_zmienia_status(client, app, monkeypatch):
    """1213 przy pierwszej próbie (po prawdziwej regule, jej zapisy są w sesji) → jedno ponowienie: 200, status
    zmieniony, reguła zadziałała skutecznie raz (jeden wpis logu, paczki unieważnione), pozycja policzona raz."""
    order_id, pierwsza_id, druga_id = _zamowienie_z_dwiema_pozycjami(app, '25/00501')
    wywolania = _scenariusz(monkeypatch, [_blad_mysql(1213, 'Deadlock found when trying to get lock')])

    r = _masowo(client, [pierwsza_id], 'czeka_na_pakowanie')

    assert r.status_code == 200, r.get_data()[:500]
    assert r.get_json()['success'] is True and r.get_json()['processed_count'] == 1
    assert r.get_json()['failed_count'] == 0 and r.get_json()['errors'] == []
    # Pierwsza próba (1213) i jedno ponowienie, obie z tym samym user_id i obie ze stanu sprzed pierwszej próby
    # (deklaracja paczek wciąż jest przy wejściu do reguły): bez rollbacku druga próba widziałaby już zapisy pierwszej.
    assert wywolania == [(order_id, 1, True), (order_id, 1, True)]
    statusy, paczki, akcje = _stan_zamowienia(order_id)
    assert statusy == ['czeka_na_pakowanie', 'spakowane']
    assert paczki == [True, True]
    assert akcje == ['paczki']                                   # wpis logu z pierwszej próby wycofał rollback


def test_hurt_ponowienie_liczy_wyniki_od_zera(client, app, monkeypatch):
    """Hurt dwóch zamówień: 1213 na drugim w pierwszej próbie. Druga próba nie dokłada pozycji pierwszego
    zamówienia drugi raz: `processed_count` to liczba zaznaczonych pozycji (2), a każde zamówienie ma jeden wpis."""
    a = _zamowienie_z_dwiema_pozycjami(app, '25/00502')
    b = _zamowienie_z_dwiema_pozycjami(app, '25/00503')
    wywolania = _scenariusz(monkeypatch, [None, _blad_mysql(1213, 'Deadlock')])

    r = _masowo(client, [a[1], b[1]], 'czeka_na_pakowanie')

    assert r.status_code == 200, r.get_data()[:500]
    assert r.get_json()['processed_count'] == 2 and r.get_json()['failed_count'] == 0
    # Pierwszy w drugiej próbie (a) startuje ze stanu sprzed pierwszej: rollback cofnął jego unieważnienie.
    assert wywolania == [(a[0], 1, True), (b[0], 1, True), (a[0], 1, True), (b[0], 1, True)]
    for order_id in (a[0], b[0]):
        statusy, paczki, akcje = _stan_zamowienia(order_id)
        assert statusy == ['czeka_na_pakowanie', 'spakowane'] and paczki == [True, True]
        assert akcje == ['paczki']


def test_hurt_dwa_1213_z_rzedu_to_500_i_nic_nie_zapisane(client, app, monkeypatch):
    order_id, pierwsza_id, _druga_id = _zamowienie_z_dwiema_pozycjami(app, '25/00504')
    wywolania = _scenariusz(monkeypatch, [_blad_mysql(1213, 'Deadlock'), _blad_mysql(1213, 'Deadlock')])

    r = _masowo(client, [pierwsza_id], 'czeka_na_pakowanie')

    assert r.status_code == 500 and r.get_json()['success'] is False
    assert len(wywolania) == 2                                   # najwyżej jedno ponowienie
    statusy, paczki, akcje = _stan_zamowienia(order_id)
    assert statusy == ['spakowane', 'spakowane']                 # rollback cofnął obie próby
    assert paczki == [False, False] and akcje == []


def test_hurt_inny_kod_mysql_nie_jest_ponawiany(client, app, monkeypatch):
    """Tylko 1213 daje ponowienie: 1205 (lock wait timeout) to 500 po jednej próbie, bez zapisu."""
    order_id, pierwsza_id, _druga_id = _zamowienie_z_dwiema_pozycjami(app, '25/00505')
    wywolania = _scenariusz(monkeypatch, [_blad_mysql(1205, 'Lock wait timeout exceeded')])

    r = _masowo(client, [pierwsza_id], 'czeka_na_pakowanie')

    assert r.status_code == 500 and r.get_json()['success'] is False
    assert len(wywolania) == 1
    statusy, paczki, akcje = _stan_zamowienia(order_id)
    assert statusy == ['spakowane', 'spakowane'] and paczki == [False, False] and akcje == []


def test_hurt_blad_bez_kodu_mysql_nie_jest_ponawiany(client, app, monkeypatch):
    """OperationalError bez `orig.args` (np. zerwane połączenie opakowane przez sterownik) to nie 1213."""
    from sqlalchemy.exc import OperationalError
    order_id, pierwsza_id, _druga_id = _zamowienie_z_dwiema_pozycjami(app, '25/00508')
    wywolania = _scenariusz(monkeypatch, [OperationalError('SELECT 1', {}, Exception())])

    r = _masowo(client, [pierwsza_id], 'czeka_na_pakowanie')

    assert r.status_code == 500 and len(wywolania) == 1
    statusy, _paczki, akcje = _stan_zamowienia(order_id)
    assert statusy == ['spakowane', 'spakowane'] and akcje == []


def test_hurt_druga_proba_na_nowym_stanie_bez_pracy_nie_zostawia_wpisow_z_pierwszej(client, app, monkeypatch):
    """Ofiara zakleszczenia traci transakcję (rollback), a cudzy zapis się zatwierdza: Weryfikacja unieważniła
    deklarację paczek. Druga próba decyduje na nowym stanie — reguła nie ma już pracy, więc nie loguje niczego,
    a wpisy pierwszej próby nie wracają. Skutki uboczne poza bazą reguła nie planuje (nic w `flask.g`), więc nic
    nie może pójść podwójnie ani zostać po wycofanej próbie."""
    from datetime import datetime

    from flask import g

    from modules.production.logistics.services import weryfikacja
    from modules.production.models import ProductionOrder, ProductionPackage
    order_id, pierwsza_id, _druga_id = _zamowienie_z_dwiema_pozycjami(app, '25/00509')
    oryginal = weryfikacja.uniewaznij_etapy
    wywolania, zaplanowane_w_g = [], []

    def regula(order, teraz, powod, **kwargs):
        wywolania.append(order.id)
        # Zaplanowane „po commicie” (dopychacz Base., sygnał druku, status Base.) leżałyby w `flask.g` żądania.
        zaplanowane_w_g.append([k for k in vars(g) if 'po_commicie' in k or 'pending' in k])
        wynik = oryginal(order, teraz, powod, **kwargs)           # zapisy pierwszej próby: log, paczki
        if len(wywolania) == 1:
            db.session.rollback()                                  # serwer cofa transakcję ofiary
            db.session.execute(ProductionOrder.__table__.update()
                               .where(ProductionOrder.__table__.c.id == order_id)
                               .values(packages_declared_at=None))
            db.session.execute(ProductionPackage.__table__.update()
                               .where(ProductionPackage.__table__.c.order_id == order_id)
                               .values(voided_at=datetime(2026, 10, 1, 9, 0)))
            db.session.commit()                                    # cudzy zapis zatwierdzony
            raise _blad_mysql(1213, 'Deadlock')
        return wynik
    monkeypatch.setattr(weryfikacja, 'uniewaznij_etapy', regula)

    r = _masowo(client, [pierwsza_id], 'czeka_na_pakowanie')

    assert r.status_code == 200, r.get_data()[:500]
    assert r.get_json()['processed_count'] == 1
    assert wywolania == [order_id, order_id]
    statusy, paczki, akcje = _stan_zamowienia(order_id)
    assert statusy == ['czeka_na_pakowanie', 'spakowane']
    assert paczki == [True, True]                                  # unieważnione cudzym zapisem
    assert akcje == []                                             # ani wpis pierwszej próby, ani drugiej
    assert zaplanowane_w_g == [[], []]                              # nic zaplanowanego w `flask.g` w żadnej próbie


def test_hurt_ponowienie_blokuje_zamowienia_i_pozycje_od_nowa(client, app, monkeypatch):
    """Druga próba zaczyna od własnych blokad: zamówienia, potem pozycje, a jej zapis następuje dopiero po nich.
    Pierwsza próba zapisuje (flush reguły) przed rzuceniem 1213."""
    order_id, pierwsza_id, _druga_id = _zamowienie_z_dwiema_pozycjami(app, '25/00506')
    _scenariusz(monkeypatch, [_blad_mysql(1213, 'Deadlock')])

    with Zapytania() as z:
        assert _masowo(client, [pierwsza_id], 'czeka_na_pakowanie').status_code == 200

    blokady_z = [i for i, (sql, _p) in enumerate(z.lista) if blokada_zamowien(sql)]
    blokady_p = [i for i, (sql, _p) in enumerate(z.lista) if blokada_pozycji(sql)]
    zapisy = [i for i, (sql, _p) in enumerate(z.lista) if sql.startswith('UPDATE prod_')]
    assert len(blokady_z) == 2 and zapisy
    assert zapisy[0] > blokady_z[0]                              # pierwsza próba: blokada przed pierwszym zapisem
    assert [i for i in blokady_p if i > blokady_z[1]]            # druga próba blokuje pozycje po zamówieniach
    assert [i for i in zapisy if i > blokady_z[1]]               # i dopiero potem zapisuje


def test_hurt_druga_proba_decyduje_na_nowo_zablokowanych_zamowieniach_bez_odczytu(client, app, monkeypatch):
    """Rollback wygasza wszystkie obiekty sesji, w tym zamówienia z pierwszej próby. Druga próba nie może używać
    starej listy: blokuje zamówienia i pozycje od nowa, a przy decyzji reguły i przeliczenia zamknięcia stan
    jest już w pamięci (zero zapytań), taki sam jak w pierwszej próbie."""
    from modules.production.logistics.services import delivery, weryfikacja
    order_id, pierwsza_id, druga_id = _zamowienie_z_dwiema_pozycjami(app, '25/00507')
    db.session.expunge_all()
    gc.collect()
    oryginal_reguly = weryfikacja.uniewaznij_etapy
    proby = []   # (stan zamówienia przy decyzji, zapytania wykonane przy odczycie tego stanu) na kolejne próby

    def regula(order, teraz, powod, **kwargs):
        with Zapytania() as przy_decyzji:
            stan = (order.id, order.packages_declared_at is not None,
                    [(p.id, p.current_status) for p in order.products])
        proby.append((stan, przy_decyzji.lista))
        wynik = oryginal_reguly(order, teraz, powod, **kwargs)
        if len(proby) == 1:
            raise _blad_mysql(1213, 'Deadlock')
        return wynik
    monkeypatch.setattr(weryfikacja, 'uniewaznij_etapy', regula)
    oryginal_zamkniecia = delivery.przelicz_zamkniecie
    zamkniecia = []

    def zamkniecie(order, *args, **kwargs):
        with Zapytania() as przy_decyzji:
            stan = [(p.id, p.current_status) for p in order.products]
        zamkniecia.append((stan, przy_decyzji.lista))
        return oryginal_zamkniecia(order, *args, **kwargs)
    monkeypatch.setattr(delivery, 'przelicz_zamkniecie', zamkniecie)

    r = _masowo(client, [pierwsza_id], 'czeka_na_pakowanie')

    assert r.status_code == 200, r.get_data()[:500]
    assert len(proby) == 2
    oczekiwany = (order_id, True, [(pierwsza_id, 'czeka_na_pakowanie'), (druga_id, 'spakowane')])
    for stan, zapytania in proby:
        assert stan == oczekiwany and zapytania == [], (stan, zapytania)
    assert zamkniecia == [([(pierwsza_id, 'czeka_na_pakowanie'), (druga_id, 'spakowane')], [])]


# --- Decyzje Konrada 2.10 (fala końcowa kroku 4.4b) -------------------------------------------------------------
# A1: hurtowa zmiana na „spakowane” na zamówieniu zweryfikowanym unieważnia weryfikację (ta sama reguła co „Cofnij
# weryfikację”). A2: zamówienie, którego przystanek jest na trasie załadowanej albo w drodze, hurt odmawia (409 dla
# tego zamówienia, reszta zaznaczonych przechodzi) — status trasy czytany pod globalną blokadą tras, którą hurt bierze
# PRZED blokadami zamówień i pozycji (kolejność Dostawy).

def _tabele_logistyki(app):
    from modules.production.logistics.models import LogisticsLog
    from modules.production.models import LabelPrintJob, ProductionPackage
    with app.app_context():
        # Tych tabel nie zakłada wspólny zestaw tego modułu testów (reguły zapisują log i paczki).
        db.metadata.create_all(bind=db.engine, tables=[
            LogisticsLog.__table__, ProductionPackage.__table__, LabelPrintJob.__table__])


def _zamowienie_logistyki(app, numer, statusy=('zweryfikowane', 'zweryfikowane'), status_trasy=None,
                          zweryfikowane=True, paczek=2, zaladowane=False, nazwa_trasy=u'Rzeszów 02.10'):
    """
    (id zamówienia, [id pozycji], [id paczek], id trasy albo None). Transport własny, pozycje w `statusy`, `paczek`
    aktualnych paczek (sprawdzonych, gdy `zweryfikowane` — wtedy też verified_at zamówienia), przystanek na trasie
    o statusie `status_trasy` (None = bez trasy), paczki załadowane na tę trasę, gdy `zaladowane`.
    """
    from datetime import date, datetime

    from modules.production.logistics import sposoby
    from modules.production.logistics.models import Route, RouteStop
    from modules.production.models import ProductionPackage
    chwila = datetime(2026, 10, 1, 8, 0)
    _tabele_logistyki(app)
    pierwsza_id, _ = produkt(app, status=statusy[0], numer=numer)
    with app.app_context():
        order = db.session.get(ProductionProduct, pierwsza_id).order
        for i, status in enumerate(statusy[1:], start=2):
            db.session.add(ProductionProduct(
                order_id=order.id, short_product_id='%s_%d' % (numer.replace('/', ''), i), product_sequence_in_order=i,
                original_product_name='Blat dębowy', current_status=status, quantity=1, volume_m3=0.1))
        order.override_delivery_method = sposoby.TRANSPORT
        if zweryfikowane:
            order.verified_at, order.verified_by_worker_id = chwila, 7
        if paczek:
            order.packages_declared_at = chwila
        paczki = [ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=chwila,
                                    verified_at=chwila if zweryfikowane else None,
                                    verified_by_worker_id=7 if zweryfikowane else None,
                                    verified_method='skan' if zweryfikowane else None)
                  for i in range(1, paczek + 1)]
        db.session.add_all(paczki)
        trasa_id = None
        if status_trasy is not None:
            trasa = Route(name=nazwa_trasy, date_from=date(2026, 10, 2), date_to=date(2026, 10, 2),
                          status=status_trasy)
            db.session.add(trasa)
            db.session.flush()
            db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
            trasa_id = trasa.id
            if zaladowane:
                for p in paczki:
                    p.loaded_at, p.loaded_by_worker_id, p.loaded_method, p.loaded_route_id = chwila, 7, 'skan', trasa_id
        db.session.commit()
        pozycje = sorted(p.id for p in ProductionProduct.query.filter_by(order_id=order.id))
        return order.id, pozycje, [p.id for p in paczki], trasa_id


def _stan_logistyki(order_id):
    """(statusy pozycji rosnąco po id, verified_at zamówienia, paczki: [(verified_at, loaded_route_id, voided?)],
    akcje logu, przystanek jest?) ze świeżego odczytu bazy."""
    from modules.production.logistics.models import LogisticsLog, RouteStop
    from modules.production.models import ProductionOrder, ProductionPackage
    db.session.rollback()
    order = db.session.get(ProductionOrder, order_id)
    statusy = [p.current_status for p in ProductionProduct.query.filter_by(order_id=order_id)
               .order_by(ProductionProduct.id)]
    paczki = [(p.verified_at, p.loaded_route_id, p.voided_at is not None)
              for p in ProductionPackage.query.filter_by(order_id=order_id).order_by(ProductionPackage.id)]
    akcje = [w.action for w in LogisticsLog.query.filter_by(order_id=order_id).order_by(LogisticsLog.id)]
    przystanek = RouteStop.query.filter_by(order_id=order_id).first() is not None
    return statusy, order.verified_at, paczki, akcje, przystanek


def test_hurt_na_spakowane_uniewaznia_weryfikacje(client, app):
    """A1: jedna pozycja zamówienia zweryfikowanego → „spakowane”. Jak „Cofnij weryfikację”: wszystkie pozycje
    zweryfikowane → spakowane, verified_at zamówienia i znaczniki weryfikacji paczek czyszczone, znaczniki załadunku
    (załadunek na trasie zatwierdzonej w toku) czyszczone, wpis `weryfikacja_cofnieta` z użytkownikiem. Deklaracja paczek
    zostaje (paczki ważne) — dokładnie jak przy „Cofnij weryfikację”."""
    from modules.production.logistics.models import LogisticsLog
    from modules.production.models import ProductionOrder
    order_id, pozycje, _paczki, _trasa = _zamowienie_logistyki(app, '25/00601', status_trasy='zatwierdzona',
                                                               zaladowane=True)

    r = _masowo(client, [pozycje[0]], 'spakowane')

    assert r.status_code == 200, r.get_data()[:500]
    assert r.get_json()['processed_count'] == 1 and r.get_json()['errors'] == []
    statusy, verified_at, paczki, akcje, przystanek = _stan_logistyki(order_id)
    assert statusy == ['spakowane', 'spakowane']
    assert verified_at is None and db.session.get(ProductionOrder, order_id).verified_by_worker_id is None
    assert paczki == [(None, None, False), (None, None, False)]
    assert akcje == ['weryfikacja_cofnieta'] and przystanek
    wpis = LogisticsLog.query.filter_by(order_id=order_id).one()
    assert (wpis.note, wpis.user_id) == (u'zmiana statusu w panelu', 1)
    assert db.session.get(ProductionOrder, order_id).packages_declared_at is not None


def test_hurt_na_spakowane_bez_weryfikacji_niczego_nie_cofa(client, app):
    """A1 dotyczy tylko zamówienia zweryfikowanego: pozycja z pakowania → „spakowane” bez weryfikacji — bez wpisu."""
    order_id, pozycje, _paczki, _trasa = _zamowienie_logistyki(
        app, '25/00602', statusy=('czeka_na_pakowanie', 'spakowane'), zweryfikowane=False, paczek=0)

    r = _masowo(client, [pozycje[0]], 'spakowane')

    assert r.status_code == 200, r.get_data()[:500]
    statusy, verified_at, _p, akcje, _s = _stan_logistyki(order_id)
    assert statusy == ['spakowane', 'spakowane'] and verified_at is None and akcje == []


def test_hurt_na_spakowane_widzi_weryfikacje_zatwierdzona_tuz_przed_zadaniem(client, app):
    """A1 na odczycie bieżącym: obiekty w sesji pokazują zamówienie niezweryfikowane, a w bazie Weryfikacja zdążyła
    je zweryfikować tuż przed hurtem (surowy UPDATE poza ORM). Hurt → „spakowane” i tak cofa weryfikację."""
    from datetime import datetime

    from modules.production.models import ProductionOrder, ProductionPackage
    chwila = datetime(2026, 10, 1, 9, 0)
    order_id, pozycje, _paczki, _trasa = _zamowienie_logistyki(
        app, '25/00603', statusy=('spakowane', 'spakowane'), zweryfikowane=False)
    order = db.session.get(ProductionOrder, order_id)                       # „migawka” żądania
    stare = list(order.products)
    assert order.verified_at is None and [p.current_status for p in stare] == ['spakowane', 'spakowane']
    db.session.execute(ProductionOrder.__table__.update().where(ProductionOrder.__table__.c.id == order_id)
                       .values(verified_at=chwila, verified_by_worker_id=7))
    db.session.execute(ProductionProduct.__table__.update()
                       .where(ProductionProduct.__table__.c.order_id == order_id)
                       .values(current_status='zweryfikowane'))
    db.session.execute(ProductionPackage.__table__.update()
                       .where(ProductionPackage.__table__.c.order_id == order_id)
                       .values(verified_at=chwila, verified_method='skan'))
    assert order.verified_at is None                                        # obiekt w sesji nadal stary
    # Przesłanka testu: stare obiekty ZOSTAJĄ w sesji przez całe żądanie (trzymamy je) — decyzja A1 ma zapaść na
    # stanie z odczytu bieżącego hurtu (populate_existing nadpisuje te obiekty), a nie na ich starych wartościach.

    r = _masowo(client, [pozycje[0]], 'spakowane')

    assert r.status_code == 200, r.get_data()[:500]
    assert order.id == order_id and len(stare) == 2                          # przesłanka żyła do końca żądania
    statusy, verified_at, paczki, akcje, _s = _stan_logistyki(order_id)
    assert statusy == ['spakowane', 'spakowane'] and verified_at is None
    assert [p[0] for p in paczki] == [None, None] and akcje == ['weryfikacja_cofnieta']


def test_hurt_na_spakowane_nie_cofa_weryfikacji_drugi_raz_po_regule(client, app):
    """A1, gałąź `and not cofnieto`: gdy reguła unieważniania etapów sama cofnęła weryfikację (zamówienie ma też
    pozycję w produkcji), hurt nie woła „Cofnij weryfikację” drugi raz — jeden wpis `weryfikacja_cofnieta`."""
    order_id, pozycje, _paczki, _trasa = _zamowienie_logistyki(
        app, '25/00604', statusy=('zweryfikowane', 'czeka_na_pakowanie'))

    r = _masowo(client, [pozycje[0]], 'spakowane')

    assert r.status_code == 200, r.get_data()[:500]
    statusy, verified_at, paczki, akcje, _s = _stan_logistyki(order_id)
    assert statusy == ['spakowane', 'czeka_na_pakowanie'] and verified_at is None
    assert [p[2] for p in paczki] == [True, True]                            # reguła unieważniła paczki
    assert akcje == ['weryfikacja_cofnieta', 'paczki']


def test_hurt_na_przystanku_dostarczonym_podpowiada_cofniecie_dostarczenia(client, app):
    """Ruling 30.6: zamówienie z przystankiem już dostarczonym na trasie w drodze — odmowa zostaje, ale komunikat
    wskazuje wykonalny krok („najpierw Cofnij dostarczenie”), a nie załadunek ani „Niedostarczone”."""
    from datetime import datetime

    from modules.production.logistics.models import RouteStop
    order_id, pozycje, _paczki, _trasa = _zamowienie_logistyki(
        app, '25/00618', statusy=('dostarczone', 'dostarczone'), status_trasy='w_trasie', zaladowane=True)
    with app.app_context():
        stop = RouteStop.query.filter_by(order_id=order_id).one()
        stop.delivered_at, stop.delivered_by_worker_id = datetime(2026, 10, 2, 11, 0), 7
        db.session.commit()

    r = _masowo(client, [pozycje[0]], 'czeka_na_pakowanie')

    assert r.status_code == 409, r.get_data()[:500]
    assert r.get_json()['error'] == (u'Zamówienie 25/00618 jest dostarczone na trasie „Rzeszów 02.10” (w drodze) — '
                                     u'najpierw Cofnij dostarczenie.')
    assert _stan_logistyki(order_id)[0] == ['dostarczone', 'dostarczone']


def test_hurt_na_przystanku_niedostarczonym_mowi_o_koncu_trasy(client, app):
    """U10 (Ruling 32): przystanek oznaczony jako niedostarczony wisi na trasie w drodze do jej końca — hurt dalej
    odmawia (zamówienie jest na trasie), a komunikat wskazuje, kiedy zamówienie wróci do puli."""
    from datetime import datetime

    from modules.production.logistics.models import RouteStop
    order_id, pozycje, _paczki, _trasa = _zamowienie_logistyki(
        app, '25/00619', statusy=('zaladowane', 'zaladowane'), status_trasy='w_trasie', zaladowane=True)
    with app.app_context():
        stop = RouteStop.query.filter_by(order_id=order_id).one()
        stop.not_delivered_at, stop.not_delivered_reason = datetime(2026, 10, 2, 11, 0), 'odmowa'
        db.session.commit()

    r = _masowo(client, [pozycje[0]], 'czeka_na_pakowanie')

    assert r.status_code == 409, r.get_data()[:500]
    assert r.get_json()['error'] == (u'Zamówienie 25/00619 jest niedostarczone na trasie „Rzeszów 02.10” (w drodze) — '
                                     u'wróci do puli po zakończeniu trasy albo po „Zdejmij z trasy” w panelu tras.')
    assert _stan_logistyki(order_id)[0] == ['zaladowane', 'zaladowane']


@pytest.mark.parametrize('nowy_status', ['czeka_na_pakowanie', 'spakowane'])
@pytest.mark.parametrize('status_trasy, opis', [('zaladowana', u'załadowana'), ('w_trasie', u'w drodze')])
def test_hurt_odmawia_zamowieniu_z_trasy_zaladowanej_i_w_drodze(client, app, status_trasy, opis, nowy_status):
    """A2: zamówienie z trasy załadowanej albo w drodze — 409 z komunikatem, bez żadnych zmian (pozycje, paczki,
    weryfikacja, przystanek, log)."""
    from modules.production.models import ProductionOrder
    order_id, pozycje, _paczki, trasa_id = _zamowienie_logistyki(
        app, '25/00611', statusy=('zaladowane', 'zaladowane'), status_trasy=status_trasy, zaladowane=True)

    r = _masowo(client, [pozycje[0]], nowy_status)

    assert r.status_code == 409, r.get_data()[:500]
    komunikat = (u'Zamówienie 25/00611 jest na trasie „Rzeszów 02.10” ({}) — najpierw Cofnij załadunek albo '
                 u'Niedostarczone.'.format(opis))
    dane = r.get_json()
    assert dane['success'] is False and dane['error'] == komunikat
    assert (dane['processed_count'], dane['failed_count'], dane['errors']) == (0, 1, [komunikat])
    statusy, verified_at, paczki, akcje, przystanek = _stan_logistyki(order_id)
    assert statusy == ['zaladowane', 'zaladowane'] and verified_at is not None
    assert [p[1:] for p in paczki] == [(trasa_id, False), (trasa_id, False)]
    assert akcje == [] and przystanek
    assert db.session.get(ProductionOrder, order_id).bl_status_pending_id is None


def test_hurt_odmawia_tylko_zamowieniu_z_trasy_w_drodze_reszta_przechodzi(client, app):
    """A2, semantyka hurtu: odmowa per zamówienie w `errors` (wszystkie jego zaznaczone pozycje w failed_count), reszta
    zaznaczonych przechodzi — 200."""
    jedzie, pozycje_j, _p, _t = _zamowienie_logistyki(
        app, '25/00612', statusy=('zaladowane', 'zaladowane'), status_trasy='w_trasie', zaladowane=True)
    stoi, pozycje_s, _p2, _t2 = _zamowienie_logistyki(
        app, '25/00613', statusy=('spakowane', 'spakowane'), zweryfikowane=False, paczek=0)

    r = _masowo(client, pozycje_j + [pozycje_s[0]], 'czeka_na_pakowanie')

    assert r.status_code == 200, r.get_data()[:500]
    dane = r.get_json()
    assert dane['success'] is True and (dane['processed_count'], dane['failed_count']) == (1, 2)
    assert dane['errors'] == [u'Zamówienie 25/00612 jest na trasie „Rzeszów 02.10” (w drodze) — najpierw Cofnij '
                              u'załadunek albo Niedostarczone.']
    assert _stan_logistyki(jedzie)[0] == ['zaladowane', 'zaladowane']
    assert _stan_logistyki(stoi)[0] == ['czeka_na_pakowanie', 'spakowane']


@pytest.mark.parametrize('status_trasy', [None, 'robocza', 'zatwierdzona'])
def test_hurt_na_trasie_roboczej_zatwierdzonej_i_bez_trasy_jak_dotad(client, app, status_trasy):
    """A2 nie dotyczy tras roboczych i zatwierdzonych ani zamówień bez trasy: reguła unieważniania jak dotąd,
    przystanek zostaje."""
    order_id, pozycje, _paczki, _trasa = _zamowienie_logistyki(app, '25/00614', status_trasy=status_trasy)

    r = _masowo(client, [pozycje[0]], 'czeka_na_pakowanie')

    assert r.status_code == 200, r.get_data()[:500]
    assert r.get_json()['processed_count'] == 1
    statusy, verified_at, paczki, akcje, przystanek = _stan_logistyki(order_id)
    assert statusy == ['czeka_na_pakowanie', 'spakowane'] and verified_at is None
    assert [p[2] for p in paczki] == [True, True]                            # paczki unieważnione regułą
    assert akcje == ['weryfikacja_cofnieta', 'paczki']
    assert przystanek is (status_trasy is not None)


def test_hurt_anulowanie_pozycji_na_trasie_w_drodze_przechodzi(client, app):
    """Anulowanie to nie powrót do produkcji: Dostawa obsługuje anulowane (przystanek anulowanego w całości,
    „Niedostarczone”), więc hurt na „anulowane” nie odmawia także na trasie w drodze."""
    order_id, pozycje, _paczki, _trasa = _zamowienie_logistyki(
        app, '25/00615', statusy=('zaladowane', 'zaladowane'), status_trasy='w_trasie', zaladowane=True)

    r = _masowo(client, [pozycje[0]], 'anulowane')

    assert r.status_code == 200, r.get_data()[:500]
    statusy, _v, _p, _a, przystanek = _stan_logistyki(order_id)
    assert statusy == ['anulowane', 'zaladowane'] and przystanek


def test_hurt_blokuje_trasy_przed_zamowieniami_i_pozycjami(client, app):
    """A2: kolejność blokad jak w Dostawie — globalna blokada tras → przystanki i trasy zamówień (odczyt blokujący)
    → zamówienia rosnąco → wszystkie pozycje zamówienie po zamówieniu → pierwszy zapis. Przed blokadą tras hurt niczego
    nie blokuje."""
    from tests.blokady_pomocnicze import indeks_blokady_tras, odczyt_przystankow, zapis
    a = _zamowienie_logistyki(app, '25/00616', status_trasy='zatwierdzona')
    b = _zamowienie_logistyki(app, '25/00617')

    with Zapytania() as z:
        assert _masowo(client, [b[1][0], a[1][0]], 'czeka_na_pakowanie').status_code == 200

    trasy = indeks_blokady_tras(z)
    przystanki, zamowienia = z.pierwsze(odczyt_przystankow), z.pierwsze(blokada_zamowien)
    pozycje, pierwszy_zapis = z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    assert trasy < przystanki < zamowienia < pozycje < pierwszy_zapis
    assert list(z.lista[zamowienia][1]) == sorted([a[0], b[0]])
    assert not [sql for sql, _p in z.lista[:trasy] if sql.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))
                or zapis(sql)]


def test_zmiany_z_base_przekazuja_uzytkownika_panelu(client, app, monkeypatch):
    """Ruling 31.2: router zmian z Base. podaje serwisowi użytkownika panelu (pobranego przed wywołaniem serwisu, który
    commituje po pobraniu zamówienia z Base.) — zdjęcie zamówienia z trasy w drodze zapisze go w logach trasy."""
    from modules.production.services.sync_service import BaselinkerSyncService
    wywolania = []

    def zastosuj(self, baselinker_order_id, changes, user_id=None):
        wywolania.append((baselinker_order_id, user_id))
        return {'success': True, 'added': 0, 'removed': 0, 'updated': 0, 'errors': [], 'error': None}

    monkeypatch.setattr(BaselinkerSyncService, 'apply_baselinker_changes', zastosuj)
    r = client.post(BASE + '/admin/apply-baselinker-changes',
                    json={'baselinker_order_id': 2500777, 'changes': {'products_to_update': []}})
    assert r.status_code == 200, r.get_data()[:300]
    assert wywolania == [(2500777, 1)]
