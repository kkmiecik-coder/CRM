# -*- coding: utf-8 -*-
"""Jednorazowe uzupełnienie PUSTEGO `sales_orders.client_origin` (partia E, E6).

DLACZEGO
========
Wszystkie 3324 zamówienia z backfillu mają puste pochodzenie klienta —
`scripts/backfill_sales_tables.py` tej kolumny nie wypełnia w ogóle — a zapis
bieżący proponował je do 23.09.2026 tylko przy pierwszym zapisie i tylko
z produkcji. Karta „Klienci według: Pochodzenie klienta" i rozbicie kanału
ręcznego pokazywały przez to same „(brak)". Zapis bieżący wypełnia już puste
pole przy każdej synchronizacji (`ingest._pochodzenie_klienta`), ale dotyka
tylko zamówień, które właśnie przyszły z BaseLinkera. Ten skrypt domyka to,
co już leży w bazie.

SKĄD NAZWA — W TEJ KOLEJNOŚCI
=============================
  (a) `prod_orders.order_source_name` po `baselinker_order_id` — nazwa, którą
      produkcja zapisała ze słownika BaseLinkera (jedno zapytanie na całość);
  (b) dla zamówień z `order_source_id`: słownik `getOrderSources` po PARZE
      (kanał, id) — jedno wywołanie API, TYLKO ODCZYT, przez istniejący
      odczyt produkcji z pamięcią podręczną (`ingest.slownik_zrodel_baselinkera`).
      Samo id jest niejednoznaczne: 0 to „Detal" w `personal` i „Zwrot" w
      `order_return`.
Niczego nie zgadujemy z innych pól (e-mail, nazwa klienta). Czego nie da się
ustalić, zostaje puste — karta pokaże „(brak)".

BEZPIECZEŃSTWO
==============
  * DOMYŚLNIE PRÓBA NA SUCHO. Bez `--apply` skrypt tylko czyta i wypisuje
    raport — plan zapisu powstaje w pamięci, obiekty modelu nie są ruszane.
  * Wypełnia WYŁĄCZNIE puste pole (NULL, pusty napis, same spacje). Ręczna
    praca w Arkuszu jest nietykalna.
  * Idempotentny: drugi przebieg bierze tylko to, co zostało puste.
  * Awaria słownika nie przerywa skryptu — (a) i tak się wykonuje.

Wzorzec: scripts/uzupelnij_klucze_pozycji.py.

Uruchomienie:
    docker compose exec app python scripts/uzupelnij_pochodzenie_klienta.py
    docker compose exec app python scripts/uzupelnij_pochodzenie_klienta.py --apply
"""

import argparse
import os
import sys
from collections import Counter
from typing import Callable, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db   # noqa: E402
from modules.reports.ingest import _jest_tabela, nazwa_pochodzenia   # noqa: E402
from modules.reports.models_sales import SalesOrder   # noqa: E402

_PACZKA = 500  # commit co tyle wypełnionych zamówień w trybie zapisu

# Etykieta kanału bez wartości w raporcie — ta sama, którą pokazują karty.
_BRAK = '(brak)'


def _puste():
    """Warunek SQL „pochodzenie puste" — ta sama definicja co
    `ingest._puste_pochodzenie`: NULL, pusty napis albo same spacje."""
    return db.or_(SalesOrder.client_origin.is_(None),
                  db.func.trim(SalesOrder.client_origin) == '')


def _nazwy_z_produkcji(identyfikatory) -> Dict[int, str]:
    """(a) sales_orders.id -> nazwa z `prod_orders`, jednym zapytaniem.

    `prod_orders.baselinker_order_id` jest UNIQUE, więc złączenie nie
    powiela zamówień. Brak tabeli produkcji (moduł niewdrożony) = pusty wynik.
    """
    if not identyfikatory or not _jest_tabela('prod_orders'):
        return {}
    from modules.production.models import ProductionOrder

    wiersze = (
        db.session.query(SalesOrder.id, ProductionOrder.order_source_name)
        .join(ProductionOrder,
              ProductionOrder.baselinker_order_id == SalesOrder.baselinker_order_id)
        .filter(SalesOrder.id.in_(list(identyfikatory)))
        .all()
    )
    wynik = {}
    for id_zamowienia, surowa in wiersze:
        nazwa = nazwa_pochodzenia(surowa)
        if nazwa:
            wynik[id_zamowienia] = nazwa
    return wynik


def uzupelnij_pochodzenie(pobierz_slownik: Callable[[], Dict[str, Dict[int, str]]],
                          zapisz: bool = False) -> Dict[str, object]:
    """Liczy (i przy `zapisz=True` zapisuje) pochodzenie pustym zamówieniom.

    `pobierz_slownik` — wstrzykiwany, żeby testy nie rozmawiały z BaseLinkerem.
    Wołany najwyżej RAZ i tylko wtedy, gdy po kroku (a) zostało zamówienie
    z parą (kanał, id).
    """
    puste = (db.session.query(SalesOrder.id, SalesOrder.order_source,
                              SalesOrder.order_source_id)
             .filter(_puste()).order_by(SalesOrder.id).all())

    plan: Dict[int, str] = {}
    z_produkcji = _nazwy_z_produkcji([p.id for p in puste])
    plan.update(z_produkcji)

    # (b) słownik — tylko dla tego, czego produkcja nie zna.
    do_slownika = [p for p in puste
                   if p.id not in plan and p.order_source and p.order_source_id is not None]
    slownik: Optional[Dict[str, Dict[int, str]]] = None
    slownik_dostepny: Optional[bool] = None
    if do_slownika:
        try:
            slownik = pobierz_slownik() or {}
            slownik_dostepny = True
        except Exception as blad:   # awaria API nie przerywa kroku (a)
            print(f'UWAGA: słownik źródeł BaseLinkera niedostępny ({blad}) — '
                  f'wypełniam tylko z produkcji.')
            slownik_dostepny = False
    ze_slownika = 0
    for pozostale in do_slownika:
        nazwa = nazwa_pochodzenia(
            ((slownik or {}).get(pozostale.order_source) or {}).get(pozostale.order_source_id))
        if nazwa:
            plan[pozostale.id] = nazwa
            ze_slownika += 1

    zostaje = Counter(p.order_source or _BRAK for p in puste if p.id not in plan)

    if zapisz and plan:
        for numer, (id_zamowienia, nazwa) in enumerate(sorted(plan.items()), start=1):
            zamowienie = SalesOrder.query.get(id_zamowienia)
            # Druga linia obrony: pole mogło zostać wypełnione ręcznie między
            # odczytem a zapisem (Arkusz otwarty w tym samym czasie).
            if zamowienie is not None and not (zamowienie.client_origin or '').strip():
                zamowienie.client_origin = nazwa
            if numer % _PACZKA == 0:
                db.session.commit()
        db.session.commit()

    return {
        'pustych': len(puste),
        'z_produkcji': len(z_produkcji),
        'ze_slownika': ze_slownika,
        'zostaje_pustych': sum(zostaje.values()),
        'pozostale_wg_kanalu': dict(zostaje),
        'slownik_dostepny': slownik_dostepny,
        # Rozkład wypełnionych nazw — do raportu, żeby było widać, CO wpadnie.
        'wg_nazwy': dict(Counter(plan.values())),
    }


def zbuduj_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Uzupełnienie pustego pochodzenia klienta z produkcji i ze '
                    'słownika źródeł BaseLinkera (domyślnie: próba na sucho)')
    parser.add_argument('--apply', action='store_true',
                        help='Zapisz wypełnione pochodzenie. Bez tej flagi skrypt '
                             'tylko czyta i wypisuje raport.')
    return parser


def main() -> int:
    args = zbuduj_parser().parse_args()

    from app import create_app
    from modules.reports.ingest import slownik_zrodel_baselinkera
    app = create_app()
    with app.app_context():
        raport = uzupelnij_pochodzenie(slownik_zrodel_baselinkera, zapisz=args.apply)

        print('=== RAPORT ===')
        print(f"Zamówień z pustym pochodzeniem: {raport['pustych']}")
        print(f"(a) wypełnione z produkcji: {raport['z_produkcji']}")
        print(f"(b) wypełnione ze słownika BaseLinkera: {raport['ze_slownika']}"
              + ('' if raport['slownik_dostepny'] is not False
                 else ' (słownik niedostępny)'))
        print(f"Zostaje pustych: {raport['zostaje_pustych']}")
        for kanal, liczba in sorted(raport['pozostale_wg_kanalu'].items(),
                                    key=lambda p: -p[1]):
            print(f'    {kanal}: {liczba}')
        print('Wypełnione nazwy:')
        for nazwa, liczba in sorted(raport['wg_nazwy'].items(), key=lambda p: -p[1]):
            print(f'    {nazwa}: {liczba}')

        if args.apply:
            print(f"\nZAPISANO {raport['z_produkcji'] + raport['ze_slownika']} zamówień.")
        else:
            print('\nPRÓBA NA SUCHO — nic nie zapisano. Uruchom z --apply, żeby '
                  'zapisać po przejrzeniu raportu.')
        return 0


if __name__ == '__main__':
    sys.exit(main())
