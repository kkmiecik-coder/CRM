# -*- coding: utf-8 -*-
"""Przeliczenie denormalizacji klientów Analizy sprzedażowej — przy każdym wdrożeniu.

DLACZEGO
========
Partia E (punkt E5, decyzja użytkownika 23.09.2026): zamówienia anulowane
i nieopłacone NIE SĄ sprzedażą. `sales_clients.orders_count`, `lifetime_net`,
`first_order_at` i `last_order_at` liczyły je do tej pory — i karta
„Klienci według" (kubełki, konwersja, nowi w okresie) stoi na tej
denormalizacji.

Zapis bieżący (`ingest._przelicz_klienta`) liczy już wyłącznie sprzedaż, ale
przelicza TYLKO klienta zamówienia, które właśnie przyszło z BaseLinkera.
Zamówienie anulowane dwa miesiące temu nie przyjdzie już nigdy (archiwum BL
po trzech miesiącach), więc jego klient zostałby z licznikiem sprzed zmiany
na zawsze. Ten skrypt przelicza wszystkich, tą samą funkcją
(`ingest.liczniki_klientow` — jedna definicja dla zapisu i dla skryptu).

KTO GO WOŁA
===========
`deploy.sh` przy KAŻDYM wdrożeniu, z `--apply`, po migracjach i przed
restartem. Weryfikacja partii E (Z1): dopóki skrypt był ręczny, karta liczyła
anulowane i nieopłacone, bo nie wołała go ani migracja, ani krok wdrożenia.
Zwykle nie ma nic do zrobienia; zmienia coś tylko wtedy, gdy zmieniła się
reguła (np. zbiór `STATUSY_POZA_SPRZEDAZA`) albo liczniki rozjechały się inną
drogą. Lokalna baza deweloperska nie przechodzi przez `deploy.sh` — tam
uruchamia się go ręcznie (polecenia niżej).

DLACZEGO NIE MIGRACJA
=====================
Migracja SQL byłaby drugą kopią reguły z `liczniki_klientow` (lista statusów
wpisana literalnie), a migracja wykonuje się raz — kolejna zmiana reguły
znów zostawiłaby stare liczniki. Krok wdrożenia woła JEDNĄ definicję za
każdym razem.

BEZPIECZEŃSTWO
==============
  * DOMYŚLNIE PRÓBA NA SUCHO. Bez `--apply` skrypt tylko czyta i wypisuje,
    co by zmienił — `liczniki_klientow` niczego nie ustawia, a pętla
    porównuje wartości zamiast je przypisywać.
  * Idempotentny: przeliczenie od nowa z bazy, drugi przebieg nie ma nic
    do zrobienia.
  * Nie dotyka `sales_orders` ani `sales_order_items` — zmienia wyłącznie
    cztery kolumny denormalizacji w `sales_clients`.

Uruchomienie:
    docker compose exec app python scripts/przelicz_klientow_sprzedazy.py
    docker compose exec app python scripts/przelicz_klientow_sprzedazy.py --apply
"""

import argparse
import os
import sys
from decimal import Decimal
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db   # noqa: E402
from modules.reports.ingest import BRAK_SPRZEDAZY, liczniki_klientow   # noqa: E402
from modules.reports.models_sales import SalesClient   # noqa: E402

_PACZKA = 500  # commit co tyle zmienionych klientów w trybie zapisu

# Ile zmian wypisać w raporcie. Reszta i tak jest policzona w nagłówku.
_ILE_W_RAPORCIE = 50


def _stan(klient: SalesClient) -> tuple:
    netto = Decimal(str(klient.lifetime_net or 0)).quantize(Decimal('0.01'))
    return (int(klient.orders_count or 0), netto,
            klient.first_order_at, klient.last_order_at)


def przelicz_klientow(zapisz: bool = False) -> Dict[str, object]:
    """Porównuje (i przy `zapisz=True` poprawia) denormalizację WSZYSTKICH
    klientów. Zwraca raport liczb — ten sam w obu trybach."""
    nowe = liczniki_klientow(db.session)
    klienci = SalesClient.query.order_by(SalesClient.id).all()

    zmiany: List[Dict[str, object]] = []
    netto_przed = Decimal('0.00')
    netto_po = Decimal('0.00')
    bez_sprzedazy = 0

    for numer, klient in enumerate(klienci, start=1):
        przed = _stan(klient)
        po = nowe.get(klient.id, BRAK_SPRZEDAZY)
        netto_przed += przed[1]
        netto_po += po[1]
        if po[0] == 0:
            bez_sprzedazy += 1
        if przed == tuple(po):
            continue
        zmiany.append({'id': klient.id, 'nazwa': klient.display_name,
                       'przed': przed, 'po': tuple(po)})
        if zapisz:
            (klient.orders_count, klient.lifetime_net,
             klient.first_order_at, klient.last_order_at) = po
            if len(zmiany) % _PACZKA == 0:
                db.session.commit()

    if zapisz:
        db.session.commit()

    return {
        'klientow': len(klienci),
        'zmienionych': len(zmiany),
        # Klienci BEZ ani jednego zamówienia w sprzedaży po przeliczeniu —
        # wypadają z kubełków karty „Klienci" i z mianownika konwersji.
        'bez_sprzedazy': bez_sprzedazy,
        'netto_przed': netto_przed,
        'netto_po': netto_po,
        'zmiany': zmiany,
    }


def _opis(stan: tuple) -> str:
    licznik, netto, pierwsze, ostatnie = stan
    return f'{licznik} zam., {netto} zł, {pierwsze or "—"} … {ostatnie or "—"}'


def zbuduj_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Przeliczenie denormalizacji klientów bez zamówień anulowanych '
                    'i nieopłaconych (domyślnie: próba na sucho, tylko raport)')
    parser.add_argument('--apply', action='store_true',
                        help='Zapisz przeliczone wartości. Bez tej flagi skrypt '
                             'tylko czyta i wypisuje raport.')
    return parser


def main() -> int:
    args = zbuduj_parser().parse_args()

    from app import create_app
    app = create_app()
    with app.app_context():
        raport = przelicz_klientow(zapisz=args.apply)

        print('=== RAPORT ===')
        print(f"Klientów sprawdzonych: {raport['klientow']}")
        print(f"Klientów z rozjechaną denormalizacją: {raport['zmienionych']}")
        print(f"Klientów bez zamówienia w sprzedaży po przeliczeniu: "
              f"{raport['bez_sprzedazy']}")
        print(f"Suma lifetime_net przed: {raport['netto_przed']} zł, "
              f"po: {raport['netto_po']} zł")
        for zmiana in raport['zmiany'][:_ILE_W_RAPORCIE]:
            print(f"  sales_clients.id={zmiana['id']} ({zmiana['nazwa']}): "
                  f"{_opis(zmiana['przed'])}  ->  {_opis(zmiana['po'])}")
        if len(raport['zmiany']) > _ILE_W_RAPORCIE:
            print(f"  … i {len(raport['zmiany']) - _ILE_W_RAPORCIE} kolejnych")

        if args.apply:
            print(f"\nZAPISANO {raport['zmienionych']} klientów.")
        else:
            print('\nPRÓBA NA SUCHO — nic nie zapisano. Uruchom z --apply, żeby '
                  'zapisać po przejrzeniu raportu.')
        return 0


if __name__ == '__main__':
    sys.exit(main())
