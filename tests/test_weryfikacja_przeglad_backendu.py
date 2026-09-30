# -*- coding: utf-8 -*-
"""Przegląd miejsc z 'spakowane' (logistyka etap 4, krok 4.3, spec 8.6): nowe statusy po spakowaniu
liczą się jak „spakowane lub dalej” w backendzie produkcji."""
import os
import re
from types import SimpleNamespace as NS

import pytest

from modules.production.logistics import sposoby as s
from modules.production.services import baselinker_status_sync as bl
from modules.production.services import mobile_api_service, order_timeline_service, reports_service
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Pliki przeglądu tego zadania i dopuszczalna liczba porównań z dokładnym 'spakowane' po zmianie.
# dashboard_api: jedno zostaje — log diagnostyczny liczący wiersze o statusie 'spakowane' (klasa E).
PRZEGLADANE = {
    'modules/production/routers/api/dashboard_api.py': 1,
    'modules/production/routers/api/products_api.py': 0,
    'modules/production/routers/api/reports_api.py': 0,
    'modules/production/routers/api/sync_api.py': 0,
    'modules/production/routers/main_routers.py': 0,
    'modules/production/routers/admin_routers.py': 0,
    'modules/production/routers/stations/monitors.py': 0,
    'modules/production/routers/mobile_api.py': 0,
    'modules/production/services/daily_report_service.py': 0,
    'modules/production/services/dashboard_alerts.py': 0,
    'modules/production/services/display_monitor_service.py': 0,
    'modules/production/services/reports_service.py': 0,
    'modules/production/services/order_timeline_service.py': 0,
    'modules/production/services/baselinker_status_sync.py': 0,
}
# Każdy wzorzec łapie inny zapis tego samego pytania (bez nakładania się — jedno miejsce = jedno trafienie).
_WZORCE = (r"current_status\s*[!=]=\s*'spakowane'",            # p.current_status == 'spakowane'
           r"\(\s*'spakowane'\s*,\s*'anulowane'",             # ('spakowane', 'anulowane'…), także w SQL
           r"dominant_status'?\]?\s*==\s*'spakowane'",         # monitory hali
           r"\{\s*'czeka_na_pakowanie'\s*,\s*'spakowane'\s*\}")  # dawne POSTPROD_STATUSES


@pytest.mark.parametrize('sciezka, dozwolone', sorted(PRZEGLADANE.items()))
def test_brak_porownan_z_dokladnym_spakowane(sciezka, dozwolone):
    with open(os.path.join(KORZEN, sciezka), encoding='utf-8') as f:
        tresc = f.read()
    trafienia = [m.group(0) for w in _WZORCE for m in re.finditer(w, tresc)]
    assert len(trafienia) == dozwolone, trafienia


def test_archiwum_wyszukiwarki_i_statusy_zamkniete():
    assert mobile_api_service.ARCHIVE_STATUSES == frozenset(s.STATUSY_PO_SPAKOWANIU) | {'anulowane'}
    assert set(reports_service.STATUSY_ZAMKNIETE) == set(s.STATUSY_PO_SPAKOWANIU) | {'anulowane'}


def test_linia_czasu_zna_nowe_statusy():
    porzadek = order_timeline_service.STATUS_ORDINAL
    assert porzadek['spakowane'] < porzadek['zweryfikowane'] < porzadek['zaladowane'] < porzadek['dostarczone']
    for status, nazwa in (('zweryfikowane', 'Zweryfikowane'), ('zaladowane', u'Załadowane'),
                          ('dostarczone', 'Dostarczone')):
        assert order_timeline_service._STATUS_DISPLAY[status] == nazwa
        assert order_timeline_service._STATUS_BADGE[status] == 'badge-completed'


def test_postprod_obejmuje_statusy_po_spakowaniu():
    assert bl.POSTPROD_STATUSES == frozenset(('czeka_na_pakowanie',) + s.STATUSY_PO_SPAKOWANIU)


def _pozycje(*statusy, order=None):
    return [NS(current_status=st, order=order) for st in statusy]


def test_status_po_spakowaniu_dla_zamowienia_czesciowo_zweryfikowanego(app, monkeypatch):
    """Retry statusu po spakowaniu nie może przepaść, bo zamówienie w międzyczasie zweryfikowano."""
    monkeypatch.setattr(bl, '_determine_packaging_target_status', lambda order: 138623)
    assert bl._cel_po_stanowisku(_pozycje('spakowane', 'zweryfikowane'), 'packaging') == 138623
    assert bl._cel_po_stanowisku(_pozycje('zweryfikowane', 'anulowane'), 'packaging') == 138623


@pytest.mark.parametrize('statusy', [('spakowane', 'dostarczone'), ('zaladowane',)])
def test_status_po_spakowaniu_nie_cofa_zaladowanego_ani_dostarczonego(app, monkeypatch, statusy):
    monkeypatch.setattr(bl, '_determine_packaging_target_status', lambda order: 138623)
    assert bl._cel_po_stanowisku(_pozycje(*statusy), 'packaging') is None


def test_retry_produkcji_zakonczonej_pomijany_po_weryfikacji(app, monkeypatch):
    order = zamowienie(sposob=s.KURIER, statusy=('zweryfikowane',))
    monkeypatch.setattr(bl, '_produkty_zamowienia', lambda numer: list(order.products))
    powod = bl._powod_pominiecia_ponowienia(order.internal_order_number, 'edges',
                                            bl.PRODUCTION_COMPLETED_STATUS_ID)
    assert powod == u'zamówienie już spakowane'
