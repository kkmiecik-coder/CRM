# -*- coding: utf-8 -*-
"""Jednorazowe uzupełnienie dwóch kolumn, których backfill nie wypełnił.

  * `sales_clients.lead_id` — spec §3.1 przewidywała tę kolumnę, ale żaden
    kod jej nie zapisywał (znalezisko z finalnego przeglądu Planu A).
  * `sales_orders.client_origin` — spec §8 krok 4 przewidywał backfill
    z `prod_orders.order_source_display`; `scripts/backfill_sales_tables.py`
    nie ma tej kolumny w `_POLA_ZAMOWIENIA` i nigdy jej nie ustawił.

Od Planu C oba pola wypełnia zapis przyrostowy (`modules/reports/ingest.py`),
ale on dotyka wyłącznie zamówień, które właśnie przyszły z BaseLinkera.
Ten skrypt domyka to, co już leży w bazie po backfillu.

Idempotentny: obie funkcje biorą wyłącznie wiersze z kolumną NULL, więc
drugi przebieg nie ma czego robić.

UWAGA (partia E, punkt E6): do uzupełnienia `client_origin` służy dziś
`scripts/uzupelnij_pochodzenie_klienta.py` — z próbą na sucho, raportem
i drugim źródłem (słownik BaseLinkera po parze kanał-id). Tryb
`--tylko-origin` tutaj zostaje, ale bierze wyłącznie produkcję.

Uruchomienie:
    docker compose exec app python scripts/uzupelnij_sales_braki.py
    docker compose exec app python scripts/uzupelnij_sales_braki.py --tylko-leady
    docker compose exec app python scripts/uzupelnij_sales_braki.py --tylko-origin
"""

import argparse
import os
import sys
from typing import Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db   # noqa: E402
from modules.reports.dedup import dowiaz_lead   # noqa: E402
from modules.reports.ingest import origin_z_produkcji   # noqa: E402
from modules.reports.models_sales import SalesClient, SalesOrder   # noqa: E402

_PACZKA = 500


def uzupelnij_leady() -> Dict[str, int]:
    """Dowiązuje `lead_id` klientom, którzy go jeszcze nie mają. Commituje."""
    klienci = SalesClient.query.filter(SalesClient.lead_id.is_(None)).all()
    wynik = {'sprawdzonych': len(klienci), 'dowiazanych': 0, 'niejednoznacznych': 0}

    for i, klient in enumerate(klienci, start=1):
        przed_merge = klient.needs_merge
        if dowiaz_lead(klient) is not None:
            wynik['dowiazanych'] += 1
        elif klient.needs_merge and not przed_merge:
            wynik['niejednoznacznych'] += 1
        if i % _PACZKA == 0:
            db.session.commit()

    db.session.commit()
    return wynik


def uzupelnij_origin() -> Dict[str, int]:
    """Uzupełnia `client_origin` z modułu produkcji. Commituje."""
    zamowienia = (SalesOrder.query
                  .filter(SalesOrder.client_origin.is_(None),
                          SalesOrder.baselinker_order_id.isnot(None))
                  .all())
    wynik = {'sprawdzonych': len(zamowienia), 'uzupelnionych': 0}

    for i, zamowienie in enumerate(zamowienia, start=1):
        etykieta = origin_z_produkcji(zamowienie.baselinker_order_id)
        if etykieta:
            zamowienie.client_origin = etykieta
            wynik['uzupelnionych'] += 1
        if i % _PACZKA == 0:
            db.session.commit()

    db.session.commit()
    return wynik


def main() -> int:
    parser = argparse.ArgumentParser(description='Uzupełnienie lead_id i client_origin')
    parser.add_argument('--tylko-leady', action='store_true')
    parser.add_argument('--tylko-origin', action='store_true')
    args = parser.parse_args()

    from app import create_app
    app = create_app()
    with app.app_context():
        if not args.tylko_origin:
            wynik = uzupelnij_leady()
            print(f"lead_id: sprawdzonych {wynik['sprawdzonych']}, "
                  f"dowiązanych {wynik['dowiazanych']}, "
                  f"niejednoznacznych {wynik['niejednoznacznych']}")
        if not args.tylko_leady:
            wynik = uzupelnij_origin()
            print(f"client_origin: sprawdzonych {wynik['sprawdzonych']}, "
                  f"uzupełnionych {wynik['uzupelnionych']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
