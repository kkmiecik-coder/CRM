# -*- coding: utf-8 -*-
"""Jednorazowe uzupełnienie `bl_order_product_id` wierszom `sales_order_items`,
które go nie mają — RAZ, pod kontrolą człowieka, zanim ograniczenie
UNIQUE(order_id, bl_order_product_id) (migracja
2026-09-23-unikalnosc-klucza-pozycji.sql) spotka się z kolejną synchronizacją.

DLACZEGO TO JEST BLOKER WDROŻENIA
==================================
`_upsert_pozycje` (modules/reports/ingest.py) dopasowuje pozycje WYŁĄCZNIE po
`bl_order_product_id` — wiersz-dziedzictwo bez klucza nigdy nie dopasuje się
do przysyłki z BaseLinkera, nawet gdy ten sam produkt w niej jest, tylko już
z kluczem. Efekt: przy pierwszej kolejnej synchronizacji tego zamówienia
stary wiersz ZOSTAJE (reguła 2 w `_upsert_pozycje` — wiersz bez klucza nigdy
nie jest kasowany), a obok niego powstaje wiersz NOWY, z tym samym produktem.
Zmierzone na woodpower_crm_local (21.09.2026): w oknie trzech miesięcy, które
`getOrders` jeszcze widzi, siedzi 2168 takich pozycji w 1127 zamówieniach,
warte 1 199 089,08 zł — 26,9% całej sprzedaży w bazie. Bez tego skryptu suma
netto i m³ podskoczyłyby o tyle przy najbliższej synchronizacji.

DOPASOWANIE JEST ZGADYWANIEM, NIE ODCZYTEM FAKTU
=================================================
Sygnatura (nazwa produktu, ilość, cena netto) nie jest kluczem obcym z BL —
jest przybliżeniem zbudowanym z tego, co oba źródła (stara tabela
`baselinker_reports_orders`, z której poszedł backfill, i świeże `getOrders`)
akurat mają wspólnego. Dlatego:

  * DOMYŚLNY TRYB TO PRÓBA. Skrypt bez `--zapisz` tylko liczy i wypisuje
    raport — nie rusza ani jednego wiersza. Zapis wymaga jawnej flagi.
  * Dopasowanie jest JEDNOZNACZNE tylko wtedy, gdy w obrębie JEDNEGO
    zamówienia dokładnie JEDEN wiersz bez klucza i dokładnie JEDEN produkt
    z BaseLinkera (jeszcze nieprzypisany do innego wiersza) mają tę samą
    sygnaturę. Każdy inny układ — brak kandydata, więcej niż jeden po
    którejkolwiek stronie — jest NIEJEDNOZNACZNY i zostaje NIETKNIĘTY,
    nawet w trybie zapisu (patrz `dopasuj_pozycje_zamowienia`).
  * Skrypt jest idempotentny: `zbierz_kandydatow` filtruje po
    `bl_order_product_id IS NULL`, więc wiersz, który już dostał klucz
    (w tym albo w poprzednim przebiegu), nigdy nie wraca do puli. Wiersze
    niejednoznaczne WRACAJĄ przy każdym przebiegu — to zamierzone: dopóki
    ktoś ręcznie nie rozstrzygnie, mają zostać widoczne w raporcie, nie
    zniknąć po cichu.

Wzorzec: scripts/backfill_sales_tables.py (liczniki, raport, kod wyjścia)
i scripts/uzupelnij_sales_braki.py (jednorazowy skrypt na tabelach sales_*).

NIE PISZE DO BASELINKERA. Jedyne wywołanie API to `getOrders` z parametrem
`order_id` — odczyt jednego zamówienia. Skrypt nigdy nie woła żadnej metody
zapisującej.

Uruchomienie:
    docker compose exec app python scripts/uzupelnij_klucze_pozycji.py
    docker compose exec app python scripts/uzupelnij_klucze_pozycji.py --zapisz
    docker compose exec app python scripts/uzupelnij_klucze_pozycji.py --dni 30
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db   # noqa: E402
from modules.reports.ingest import mapuj_pozycje   # noqa: E402
from modules.reports.models_sales import SalesOrder, SalesOrderItem   # noqa: E402
from modules.reports.routers_analiza import MAKS_DNI_POBIERANIA   # noqa: E402

# Ta sama zaporowa długość okna co reszta Analizy sprzedażowej
# (routers_analiza.py) — BaseLinker przenosi zamówienia starsze niż trzy
# miesiące do archiwum, którego `getOrders` nie widzi żadnym parametrem.
# JEDNA definicja, nie kopia: rozjazd między tym skryptem a resztą modułu
# dałby dwie różne odpowiedzi na pytanie "co jeszcze da się dociągnąć z BL".
OKNO_DNI = MAKS_DNI_POBIERANIA

_PACZKA = 50  # commit co tyle PRZETWORZONYCH zamówień w trybie zapisu


def _sygnatura(nazwa: Optional[str], ilosc: Optional[int],
              cena_netto) -> Tuple[str, Optional[int], Optional[str]]:
    """Klucz dopasowania: nazwa (przycięta, bez wrażliwości na białe znaki
    na krawędziach), ilość i cena netto zaokrąglona do grosza — jako NAPIS,
    żeby `Decimal('100.00')` i `Decimal('100.0')` (BL bywa liczbą
    zmiennoprzecinkową po drodze) dały tę samą sygnaturę mimo różnej skali.
    """
    if cena_netto is None:
        cena = None
    else:
        cena = str(Decimal(str(cena_netto)).quantize(Decimal('0.01')))
    return ((nazwa or '').strip(), ilosc, cena)


def dopasuj_pozycje_zamowienia(
        wiersze_bez_klucza: List[SalesOrderItem],
        pozycje_bl: List[Dict],
) -> Tuple[List[Tuple[SalesOrderItem, int]], List[SalesOrderItem], List[SalesOrderItem]]:
    """Dopasowuje wiersze JEDNEGO zamówienia po sygnaturze (nazwa, ilość, cena).

    `pozycje_bl` ma być JUŻ przefiltrowane przez wywołującego do pozycji,
    których klucz nie jest zajęty przez żaden istniejący wiersz w bazie
    (patrz `_przetworz_zamowienie`) — funkcja sama tego nie sprawdza, bo nie
    ma dostępu do reszty wierszy zamówienia.

    Zwraca (dopasowania, niejednoznaczne, bez_dopasowania):
      * dopasowania — pary (wiersz, bl_order_product_id), gotowe do zapisu;
      * niejednoznaczne — wiersze, których sygnatura ma WIĘCEJ NIŻ JEDNEGO
        kandydata po którejkolwiek stronie;
      * bez_dopasowania — wiersze, których sygnatura nie ma ŻADNEGO
        kandydata w przysyłce z BaseLinkera.
    """
    grupy_db: Dict[tuple, List[SalesOrderItem]] = defaultdict(list)
    for wiersz in wiersze_bez_klucza:
        grupy_db[_sygnatura(wiersz.raw_product_name, wiersz.quantity,
                            wiersz.price_net)].append(wiersz)

    grupy_bl: Dict[tuple, List[Dict]] = defaultdict(list)
    for pola in pozycje_bl:
        if pola.get('bl_order_product_id') is None:
            continue
        grupy_bl[_sygnatura(pola.get('raw_product_name'), pola.get('quantity'),
                            pola.get('price_net'))].append(pola)

    dopasowania: List[Tuple[SalesOrderItem, int]] = []
    niejednoznaczne: List[SalesOrderItem] = []
    bez_dopasowania: List[SalesOrderItem] = []

    for sygnatura, wiersze in grupy_db.items():
        kandydaci = grupy_bl.get(sygnatura, [])
        if not kandydaci:
            bez_dopasowania.extend(wiersze)
        elif len(wiersze) == 1 and len(kandydaci) == 1:
            dopasowania.append((wiersze[0], kandydaci[0]['bl_order_product_id']))
        else:
            niejednoznaczne.extend(wiersze)

    return dopasowania, niejednoznaczne, bez_dopasowania


def zbierz_kandydatow(dni: int = OKNO_DNI) -> List[SalesOrder]:
    """Zamówienia z numerem BaseLinkera w oknie `dni` dni, które mają
    PRZYNAJMNIEJ JEDEN wiersz pozycji bez `bl_order_product_id`.

    Filtr po dacie idzie w zapytaniu SQL; „ma wiersz bez klucza" liczymy
    w Pythonie po stronie już wczytanej relacji `items` (`lazy='selectin'`
    w modelu) — przy skali ~1100 zamówień w oknie to jedno dodatkowe
    zapytanie zbiorcze, nie N+1.
    """
    from modules.reports.analiza_service import dzis_lokalnie

    granica = dzis_lokalnie() - timedelta(days=dni)
    zamowienia = (SalesOrder.query
                 .filter(SalesOrder.baselinker_order_id.isnot(None),
                         SalesOrder.date_created >= granica)
                 .all())
    return [z for z in zamowienia
            if any(w.bl_order_product_id is None for w in z.items)]


def _pusty_licznik() -> Dict[str, int]:
    return {
        'zamowien_sprawdzonych': 0,
        'zamowien_bez_danych_bl': 0,
        'pozycji_jednoznacznych': 0,
        'pozycji_niejednoznacznych': 0,
        'pozycji_bez_dopasowania': 0,
    }


def _przetworz_zamowienie(zamowienie: SalesOrder, order_bl: Dict, zapisz: bool,
                          statystyki: Dict[str, int],
                          niejednoznaczne_szczegoly: List[Dict]) -> None:
    """Dopasowuje i (opcjonalnie) zapisuje pozycje JEDNEGO zamówienia.
    Nakłada wynik na `statystyki` i `niejednoznaczne_szczegoly` w miejscu.
    """
    wiersze_bez_klucza = [w for w in zamowienie.items if w.bl_order_product_id is None]
    if not wiersze_bez_klucza:
        return

    # Klucze już ZAJĘTE przez wiersze tego zamówienia — pozycje BL z takim
    # kluczem są WYŁĄCZONE z puli kandydatów, inaczej dwa wiersze mogłyby
    # dostać ten sam klucz i złamać ograniczenie UNIQUE dodane migracją.
    klucze_zajete = {w.bl_order_product_id for w in zamowienie.items
                     if w.bl_order_product_id is not None}

    pozycje_bl = [p for p in mapuj_pozycje(order_bl)
                 if p.get('bl_order_product_id') is not None
                 and p['bl_order_product_id'] not in klucze_zajete]

    dopasowania, niejednoznaczne, bez_dopasowania = dopasuj_pozycje_zamowienia(
        wiersze_bez_klucza, pozycje_bl)

    statystyki['pozycji_jednoznacznych'] += len(dopasowania)
    statystyki['pozycji_niejednoznacznych'] += len(niejednoznaczne)
    statystyki['pozycji_bez_dopasowania'] += len(bez_dopasowania)

    for wiersz in niejednoznaczne:
        niejednoznaczne_szczegoly.append({
            'sales_order_id': zamowienie.id,
            'baselinker_order_id': zamowienie.baselinker_order_id,
            'item_id': wiersz.id,
            'raw_product_name': wiersz.raw_product_name,
            'quantity': wiersz.quantity,
            'price_net': wiersz.price_net,
        })

    if zapisz:
        for wiersz, klucz in dopasowania:
            wiersz.bl_order_product_id = klucz


def przetworz_wszystkie(
        zamowienia: List[SalesOrder],
        pobierz_zamowienie_bl: Callable[[int], Optional[Dict]],
        zapisz: bool = False,
) -> Tuple[Dict[str, int], List[Dict]]:
    """Pętla po zamówieniach-kandydatach. W trybie próby (`zapisz=False`)
    NIC nie commituje — `_przetworz_zamowienie` w ogóle nie modyfikuje
    obiektów, gdy `zapisz` jest fałszywe, więc nawet przypadkowy
    `db.session.commit()" gdzieś dalej w tej samej sesji nie zapisałby
    dopasowań próbnych.
    """
    statystyki = _pusty_licznik()
    niejednoznaczne_szczegoly: List[Dict] = []

    for i, zamowienie in enumerate(zamowienia, start=1):
        statystyki['zamowien_sprawdzonych'] += 1
        order_bl = pobierz_zamowienie_bl(zamowienie.baselinker_order_id)
        if not order_bl:
            statystyki['zamowien_bez_danych_bl'] += 1
            continue

        _przetworz_zamowienie(zamowienie, order_bl, zapisz, statystyki,
                              niejednoznaczne_szczegoly)

        if zapisz and i % _PACZKA == 0:
            db.session.commit()

    if zapisz:
        db.session.commit()

    return statystyki, niejednoznaczne_szczegoly


# Tempo zapytań do BaseLinkera. Limit konta to 100 zapytań na minutę NA CAŁE
# KONTO — liczy się też normalny ruch CRM (synchronizacje, statusy). Pierwsze
# uruchomienie na produkcji (24.09.2026) bez odstępu wysłało ok. 2300 zapytań
# w 4 minuty i BaseLinker zablokował API całego konta na kilkanaście minut.
# 1 s = 60 zapytań na minutę, z zapasem na resztę ruchu.
ODSTEP_ZAPYTAN_S = 1.0

# Fragmenty komunikatu BaseLinkera o przekroczonym limicie albo blokadzie.
# Po takim komunikacie NIE pytamy dalej — każde kolejne zapytanie tylko
# przedłużałoby blokadę całego konta.
_ZNAKI_BLOKADY = ('limit', 'block', 'zablok', 'too many')


def _to_blokada(odpowiedz: Dict) -> bool:
    tekst = ' '.join(str(odpowiedz.get(k) or '') for k in ('error_code', 'error_message')).lower()
    return any(znak in tekst for znak in _ZNAKI_BLOKADY)


def pobieracz_z_limitem(zapytanie, odstep_s: float = ODSTEP_ZAPYTAN_S, spij=None):
    """Funkcja `bl_order_id -> zamówienie albo None` z tempem i bezpiecznikiem.

    - między zapytaniami czeka `odstep_s` sekund;
    - po pierwszej odpowiedzi o limicie/blokadzie przestaje wołać API i dla
      każdego kolejnego zamówienia zwraca None (zamówienie trafia do „bez
      odpowiedzi z BaseLinkera" i zostaje na następny przebieg). To, co już
      dopasowano, zapisuje się normalnie.

    `zapytanie(bl_order_id) -> dict` to surowa odpowiedź API; w testach atrapa.
    Licznik zablokowanych jest w atrybucie `.pominiete_po_blokadzie`.
    """
    import time
    spij = spij or time.sleep
    stan = {'pierwsze': True, 'blokada': False}

    def pobierz(bl_order_id: int) -> Optional[Dict]:
        if stan['blokada']:
            pobierz.pominiete_po_blokadzie += 1
            return None
        if not stan['pierwsze']:
            spij(odstep_s)
        stan['pierwsze'] = False
        odpowiedz = zapytanie(bl_order_id) or {}
        if odpowiedz.get('status') != 'SUCCESS':
            if _to_blokada(odpowiedz):
                stan['blokada'] = True
                pobierz.blokada = True
                print("\n!!! BaseLinker zgłosił limit albo blokadę API — przerywam "
                      "zapytania. Dopasowania zebrane do tej chwili zapiszą się; "
                      "resztę uruchom ponownie po odblokowaniu.")
            return None
        zamowienia = odpowiedz.get('orders') or []
        return zamowienia[0] if zamowienia else None

    pobierz.pominiete_po_blokadzie = 0
    pobierz.blokada = False
    return pobierz


def _zapytanie_baselinkera():
    """Jedyne miejsce, które NAPRAWDĘ rozmawia z BaseLinkerem — tylko odczyt
    (`getOrders` z parametrem `order_id`, ten sam wzorzec co
    `modules/baselinker/service.py:948`). Testy jej nie wołają: dostają
    własny `pobierz_zamowienie_bl` przez wstrzyknięcie, patrz
    tests/test_uzupelnij_klucze_pozycji.py. Serwis tworzony RAZ na przebieg.
    """
    from modules.baselinker.service import BaselinkerService

    serwis = BaselinkerService()

    def zapytanie(bl_order_id: int) -> Dict:
        return serwis._make_request('getOrders', {
            'order_id': bl_order_id,
            'include_custom_extra_fields': True,
        })
    return zapytanie


def zbuduj_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Uzupełnienie bl_order_product_id w sales_order_items '
                    '(domyślnie: tryb próby, tylko raport)')
    parser.add_argument('--zapisz', action='store_true',
                        help='Zapisz jednoznaczne dopasowania. Bez tej flagi '
                             'skrypt tylko liczy i wypisuje raport.')
    parser.add_argument('--dni', type=int, default=OKNO_DNI,
                        help='Szerokość okna wstecz w dniach (domyślnie {}, '
                             'jak reszta Analizy sprzedażowej)'.format(OKNO_DNI))
    parser.add_argument('--odstep', type=float, default=ODSTEP_ZAPYTAN_S,
                        help='Sekundy między zapytaniami do BaseLinkera '
                             '(domyślnie {}; limit konta to 100/min na CAŁE '
                             'konto)'.format(ODSTEP_ZAPYTAN_S))
    return parser


def main() -> int:
    args = zbuduj_parser().parse_args()

    from app import create_app
    app = create_app()
    with app.app_context():
        zamowienia = zbierz_kandydatow(args.dni)
        print(f"Zamówień-kandydatów w oknie {args.dni} dni: {len(zamowienia)} "
              f"(odstęp {args.odstep} s, ok. {len(zamowienia) * args.odstep / 60:.0f} min)")

        pobierz = pobieracz_z_limitem(_zapytanie_baselinkera(), args.odstep)
        statystyki, niejednoznaczne = przetworz_wszystkie(
            zamowienia, pobierz, zapisz=args.zapisz)
        if pobierz.blokada:
            print(f"Zamówień pominiętych po blokadzie API: "
                  f"{pobierz.pominiete_po_blokadzie} — uruchom skrypt ponownie "
                  f"po odblokowaniu.")

        print("\n=== RAPORT ===")
        print(f"Zamówień sprawdzonych: {statystyki['zamowien_sprawdzonych']}")
        print(f"Zamówień bez odpowiedzi z BaseLinkera: "
              f"{statystyki['zamowien_bez_danych_bl']}")
        print(f"Pozycji dopasowanych jednoznacznie: "
              f"{statystyki['pozycji_jednoznacznych']}")
        print(f"Pozycji niejednoznacznych (NIETKNIĘTE): "
              f"{statystyki['pozycji_niejednoznacznych']}")
        print(f"Pozycji bez dopasowania (NIETKNIĘTE): "
              f"{statystyki['pozycji_bez_dopasowania']}")

        if niejednoznaczne:
            print(f"\nSzczegóły niejednoznacznych ({len(niejednoznaczne)}):")
            for wpis in niejednoznaczne:
                print(f"  sales_order_items.id={wpis['item_id']} "
                      f"(sales_orders.id={wpis['sales_order_id']}, "
                      f"BL={wpis['baselinker_order_id']}): "
                      f"'{wpis['raw_product_name']}' x{wpis['quantity']} "
                      f"@ {wpis['price_net']}")

        if args.zapisz:
            print(f"\nZAPISANO {statystyki['pozycji_jednoznacznych']} "
                  f"jednoznacznych dopasowań.")
        else:
            print("\nTRYB PRÓBY — nic nie zapisano. Uruchom z --zapisz, żeby "
                  "zapisać jednoznaczne dopasowania po przejrzeniu raportu.")

        return 1 if niejednoznaczne else 0


if __name__ == '__main__':
    sys.exit(main())
