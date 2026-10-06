# -*- coding: utf-8 -*-
"""Liczniki Weryfikacji na dashboardzie produkcji (logistyka etap 4, krok 4.3, spec 11)."""
from modules.production.logistics import sposoby as s
from modules.production.models import get_local_now
from modules.production.routers.api import dashboard_api
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401


def test_liczniki_weryfikacji(app):
    teraz = get_local_now()
    zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    zamowienie(sposob=s.KURIER, statusy=('spakowane',), problem_reason='inne', problem_at=teraz)
    zamowienie(statusy=('czeka_na_pakowanie',))
    assert dashboard_api._safe_weryfikacja() == {'pending': 2, 'problems': 1}


def test_blad_licznika_nie_psuje_odswiezenia(app, monkeypatch):
    from modules.production.logistics.services import weryfikacja
    monkeypatch.setattr(weryfikacja, 'liczba_problemow', lambda: 1 / 0)
    assert dashboard_api._safe_weryfikacja() is None
