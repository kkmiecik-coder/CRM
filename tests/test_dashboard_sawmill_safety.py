# -*- coding: utf-8 -*-
"""
Osłona dashboardu produkcji na błędy w agregatach trakowni.

dashboard_tab_content() w modules/production/routers/api/dashboard_api.py
ma na zewnątrz `except Exception` zwracający 500 dla CAŁEGO dashboardu —
błąd w sawmill_dashboard_stats() (brakująca tabela, gdyby DDL nie poszedł
przed deployem, albo uszkodzony wiersz) kładłby więc kafelki wszystkich
sześciu pozostałych, w pełni sprawnych stanowisk produkcyjnych, nie tylko
trakowni. _safe_sawmill_stats() ma łapać taki wyjątek i zwrócić fallback
zerowy — dokładnie ten sam wzorzec, jaki _safe_station_work() już stosuje
dla reszty stanowisk.

Test na poziomie samej funkcji pomocniczej (nie całego routingu Flask) —
dashboard_tab_content() dotyka ProductionItem/ProductionOrder/
ProductionError/ProductionSyncLog i telemetrii urządzeń, więc pełne
uruchomienie żądania HTTP wymagałoby DDL całego modułu produkcji, co jest
nieproporcjonalne wobec tego, co ta regresja ma wykryć: że wyjątek w
sawmill_dashboard_stats() NIE propaguje się dalej.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import modules.production.routers.api.dashboard_api as dashboard_api
import modules.production.sawmill.services.exports as sawmill_exports


def test_blad_agregatow_trakowni_nie_wywala_dashboardu(monkeypatch):
    def boom():
        raise RuntimeError('brak tabeli prod_sawmill_orders')

    monkeypatch.setattr(sawmill_exports, 'sawmill_dashboard_stats', boom)

    wynik = dashboard_api._safe_sawmill_stats()

    assert wynik == {
        'open_orders': 0, 'logs_today': 0, 'volume_today_m3': 0.0,
        'to_settle': 0, 'progress_pct': 0.0,
    }


def test_brak_bledu_przepuszcza_prawdziwe_dane(monkeypatch):
    """Osłona nie ma zniekształcać wyniku, gdy agregaty faktycznie działają."""
    prawdziwe_dane = {
        'open_orders': 3, 'logs_today': 7, 'volume_today_m3': 12.5,
        'to_settle': 1, 'progress_pct': 42.0,
    }
    monkeypatch.setattr(sawmill_exports, 'sawmill_dashboard_stats', lambda: prawdziwe_dane)

    assert dashboard_api._safe_sawmill_stats() == prawdziwe_dane
