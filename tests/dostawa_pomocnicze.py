# -*- coding: utf-8 -*-
"""Wspólne dane testów Dostawy (logistyka etap 4, krok 4.4): zamówienie z paczkami, trasa z przystankami,
paczki załadowane wprost, telefon kierowcy i jego nagłówki oraz narzędzia testów „decyzja na zablokowanych
obiektach” (Ruling P2). Importuj razem z fiksturami:

    from tests.dostawa_pomocnicze import T0, DZIEN, trasa, zamowienie_z_paczkami
    from tests.logistyka_fixtures import app, client  # noqa: F401
"""
import collections
import gc
import itertools
from datetime import date, datetime

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import Route, RouteStop
from modules.production.logistics.services import delivery, dostawa
from modules.production.models import ProductionDevice, ProductionPackage
from modules.production.services.mobile_api_service import generate_token
from tests.blokady_pomocnicze import blokada_zamowien
from tests.logistyka_fixtures import kierowca, zamowienie

T0 = datetime(2026, 10, 1, 8, 0)
# W granicach dat tras: „dziś” tras w testach to 26.09.2026 (tests/logistyka_fixtures.DZIS_TESTOW).
DZIEN = date(2026, 10, 1)
_licznik = itertools.count(1)


def zamowienie_z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), paczek=2, zweryfikowane=True,
                          sposob=s.TRANSPORT, **kolumny):
    """Zamówienie (domyślnie transport własny) z `paczek` aktualnymi paczkami, domyślnie sprawdzonymi."""
    order = zamowienie(sposob=sposob, statusy=statusy, packages_declared_at=T0,
                       verified_at=T0 if zweryfikowane else None, **kolumny)
    lista = [ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=T0,
                               verified_at=T0 if zweryfikowane else None,
                               verified_method='skan' if zweryfikowane else None)
             for i in range(1, paczek + 1)]
    db.session.add_all(lista)
    db.session.commit()
    return order, lista


def trasa(zamowienia, status='zatwierdzona', kierowca_id=None, nazwa=None, od=DZIEN, do=None, **kolumny):
    """Trasa z przystankami w kolejności `zamowienia` — wprost w bazie, bez blokad i walidacji serwisu tras."""
    t = Route(name=nazwa or u'Trasa %d' % next(_licznik), date_from=od, date_to=do or od, status=status,
              driver_worker_id=kierowca_id, **kolumny)
    db.session.add(t)
    db.session.flush()
    for pozycja, order in enumerate(zamowienia, start=1):
        db.session.add(RouteStop(route_id=t.id, order_id=order.id, position=pozycja))
    db.session.commit()
    return t


def zaladuj_wprost(paczki, trasa_, kto_id=None, chwila=T0):
    """Paczki załadowane na trasę (stan wyjściowy testu, bez API)."""
    for p in paczki:
        p.loaded_at, p.loaded_by_worker_id, p.loaded_method, p.loaded_route_id = chwila, kto_id, 'skan', trasa_.id
    db.session.commit()


def telefon_kierowcy():
    """(urządzenie stanowiska Dostawa, kierowca ze znacznikiem is_driver)."""
    device = ProductionDevice(device_id='TEL-DOSTAWA-%d' % next(_licznik), device_name='Telefon kierowcy',
                              station_code='delivery')
    db.session.add(device)
    db.session.commit()
    return device, kierowca()


def naglowki(device, kto=None, op_id=None):
    wynik = {'Authorization': 'Bearer ' + generate_token(device),
             'X-Operation-Id': op_id or 'op-dost-%d' % next(_licznik)}
    if kto is not None:
        wynik['X-Worker-Ids'] = str(kto.id)
    return wynik


# --- Decyzje na zablokowanych obiektach (krok 4.4a, przyczyna A; Ruling P2 kroku 4.4b) -------------------

_TABELE_STANU = ('FROM prod_orders', 'FROM prod_products', 'FROM prod_packages', 'FROM prod_route_stops',
                 'FROM prod_routes')


def odsmiecaj_po_blokadach(monkeypatch):
    """
    Odśmiecanie pamięci tuż po blokadach (przelotka na dostawa._wymagaj_statusu — pierwszy krok po zablokuj)
    i przy każdym wpisie logu (delivery.zapisz_log, także w routes.usun_przystanek). Mapa tożsamości sesji trzyma
    czyste obiekty SŁABO: zablokowane zamówienie, którego zapis Dostawy nie trzyma, znika wtedy z sesji (zamówienie
    i jego pozycje trzymają się tylko nawzajem — cykl, który zbiera dopiero gc), a późniejszy dostęp
    (`ProductionOrder.query.get`, `order.products`) czyta je od nowa zwykłym SELECT-em — na MySQL z migawki
    REPEATABLE READ sprzed blokad.

    Zwraca licznik wywołań przelotek według nazwy (`collections.Counter`: '_wymagaj_statusu', 'zapisz_log'). Test
    sprawdza nim, że odśmiecanie naprawdę zaszło — przelotka, której zapis nie woła, niczego by nie sprawdziła.
    """
    licznik = collections.Counter()
    for modul, nazwa in ((dostawa, '_wymagaj_statusu'), (delivery, 'zapisz_log')):
        oryginal = getattr(modul, nazwa)

        def przelotka(*a, _oryginal=oryginal, _nazwa=nazwa, **k):
            licznik[_nazwa] += 1
            gc.collect()
            return _oryginal(*a, **k)

        monkeypatch.setattr(modul, nazwa, przelotka)
    return licznik


def zwykle_odczyty_stanu(z):
    """Zwykłe (nieblokujące) SELECT-y zamówień, pozycji, paczek i tras od pierwszej blokady zamówień."""
    od = z.pierwsze(blokada_zamowien)
    return [sql for sql, _par in z.lista[od:]
            if sql.startswith('SELECT') and any(t in sql for t in _TABELE_STANU)
            and not sql.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))]
