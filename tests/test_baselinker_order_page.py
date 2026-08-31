# -*- coding: utf-8 -*-
"""
Link do strony zamówienia (order_page) z odpowiedzi getOrders.

BaseLinker zwraca order_page w getOrders, które _save_order_product_ids
i tak wywołuje zaraz po addOrder. Bez tego testu link ginie, a checkout
nie ma czym pokazać klientowi jego strony zamówienia.

Testujemy metodę na instancji utworzonej przez __new__ — pomijamy
__init__, który sięga po current_app.config.

Podmieniamy też QuoteItemDetails. Bez tego `QuoteItemDetails.query` wywala
się na „No application found", zewnętrzny try/except w metodzie łyka wyjątek
i test przechodziłby przez ścieżkę BŁĘDU zamiast przez normalną — nie
wykryłby regresji w commicie, bo do commitu w ogóle by nie dochodziło.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.baselinker.service import BaselinkerService  # noqa: E402


class _AtrapaSesji:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


class _AtrapaZapytania:
    """Minimum z Query, którego używa _save_order_product_ids."""

    def __init__(self, pozycje):
        self._pozycje = pozycje

    def filter_by(self, **kryteria):
        return self

    def all(self):
        return list(self._pozycje)


def _serwis(odpowiedz_getorders, monkeypatch, sesja, pozycje_wyceny=()):
    """Serwis z podmienionym transportem HTTP, sesją bazy i modelem pozycji."""
    serwis = BaselinkerService.__new__(BaselinkerService)
    serwis.logger = SimpleNamespace(
        info=lambda *a, **k: None, warning=lambda *a, **k: None,
        error=lambda *a, **k: None, debug=lambda *a, **k: None,
    )
    serwis._make_request = lambda metoda, parametry: odpowiedz_getorders
    monkeypatch.setattr("modules.baselinker.service.db", SimpleNamespace(session=sesja))
    monkeypatch.setattr(
        "modules.calculator.models.QuoteItemDetails",
        SimpleNamespace(query=_AtrapaZapytania(pozycje_wyceny)),
    )
    return serwis


class TestOrderPage:
    def test_order_page_zapisany_na_wycenie(self, monkeypatch):
        sesja = _AtrapaSesji()
        odpowiedz = {
            "status": "SUCCESS",
            "orders": [{
                "order_id": 12345,
                "order_page": "https://blsklep.pl/zamowienie/abc123",
                "products": [],
            }],
        }
        serwis = _serwis(odpowiedz, monkeypatch, sesja)
        wycena = SimpleNamespace(id=1, baselinker_order_page=None)

        serwis._save_order_product_ids(wycena, 12345)

        assert wycena.baselinker_order_page == "https://blsklep.pl/zamowienie/abc123"
        assert sesja.commits == 1  # commit także bez dopasowanych SKU

    def test_brak_order_page_nie_wywraca(self, monkeypatch):
        sesja = _AtrapaSesji()
        odpowiedz = {"status": "SUCCESS", "orders": [{"order_id": 1, "products": []}]}
        serwis = _serwis(odpowiedz, monkeypatch, sesja)
        wycena = SimpleNamespace(id=1, baselinker_order_page=None)

        serwis._save_order_product_ids(wycena, 1)

        assert wycena.baselinker_order_page is None
        assert sesja.commits == 0  # nie ma czego zapisywać

    def test_blad_getorders_nie_wywraca(self, monkeypatch):
        sesja = _AtrapaSesji()
        serwis = _serwis({"status": "ERROR"}, monkeypatch, sesja)
        wycena = SimpleNamespace(id=1, baselinker_order_page=None)

        serwis._save_order_product_ids(wycena, 1)

        assert wycena.baselinker_order_page is None
