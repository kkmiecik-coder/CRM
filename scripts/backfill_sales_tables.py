# -*- coding: utf-8 -*-
"""Jednorazowy backfill: baselinker_reports_orders -> sales_* .

Stara tabela ma 1 wiersz = 1 POZYCJA, z polami zamówienia powielonymi
w każdym wierszu. Grupujemy po `baselinker_order_id` i zapisujemy pola
zamówienia RAZ — z NAJŚWIEŻSZEGO wiersza w grupie (wg `updated_at`, a przy
remisie wg `id`) — a pozycje jako osobne wiersze.

Skrypt jest idempotentny WYŁĄCZNIE dla zamówień z numerem BaseLinkera:
zamówienie, które już jest w `sales_orders` (po `baselinker_order_id`),
pomijamy. Pierwsze przejście może paść w połowie i wtedy wystarczy uruchomić
ponownie.

Wiersze BEZ `baselinker_order_id` (ręczne) nie mają jak zostać przeniesione
idempotentnie bez dodatkowej kolumny wiążącej z rekordem źródłowym, a
dokładanie migracji schematu do skryptu jednorazowego jest nieproporcjonalne.
Skrypt je liczy i ŚWIADOMIE POMIJA — nie migruje wcale — i kończy się kodem 1,
żeby operator ręcznie zdecydował, co z nimi zrobić.

Uruchomienie:
    docker compose exec app python scripts/backfill_sales_tables.py
    docker compose exec app python scripts/backfill_sales_tables.py --tylko-raport
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func   # noqa: E402

from extensions import db   # noqa: E402
from modules.reports.dedup import znajdz_lub_utworz_klienta   # noqa: E402
from modules.reports.filters import liczy_sie_do_sprzedazy   # noqa: E402
from modules.reports.models import BaselinkerReportOrder   # noqa: E402
from modules.reports.models_sales import (   # noqa: E402
    SalesClient, SalesOrder, SalesOrderItem,
)

_ZERO = Decimal('0')

# Pola kopiowane 1:1 ze starego wiersza na SalesOrder. Po prawej nazwa
# w starym modelu, jeśli inna.
_POLA_ZAMOWIENIA = (
    'date_created', 'internal_order_number', 'customer_name', 'email', 'phone',
    'delivery_address', 'delivery_postcode', 'delivery_city', 'delivery_state',
    'caretaker', 'order_source', 'delivery_method', 'delivery_cost',
    'price_type', 'payment_method', 'current_status', 'baselinker_status_id',
)

_POLA_POZYCJI = (
    'wood_species', 'technology', 'wood_class', 'finish_state', 'group_type',
    'product_type', 'length_cm', 'width_cm', 'thickness_cm', 'quantity',
    'price_gross', 'price_net', 'value_gross', 'value_net', 'volume_per_piece',
    'total_volume', 'total_surface_m2', 'price_per_m3', 'raw_product_name',
)


def _dec(wartosc) -> Decimal:
    return _ZERO if wartosc is None else Decimal(str(wartosc))


def przenies_wiersze(wiersze):
    """Przenosi listę starych wierszy. Zwraca statystyki. NIE commituje."""
    grupy = defaultdict(list)
    bez_numeru_bl = 0
    for w in wiersze:
        # Wiersze bez numeru zamówienia BaseLinker (ręczne) nie da się przenieść
        # idempotentnie — nie ma kolumny wiążącej z rekordem źródłowym, więc
        # ponowne uruchomienie nie potrafiłoby rozpoznać "już przeniesionego".
        # Liczymy je i pomijamy świadomie zamiast ryzykować duplikaty.
        if not w.baselinker_order_id:
            bez_numeru_bl += 1
            continue
        grupy[w.baselinker_order_id].append(w)

    juz_sa = {
        x[0] for x in db.session.query(SalesOrder.baselinker_order_id)
        .filter(SalesOrder.baselinker_order_id.isnot(None)).all()
    }

    stat = {
        'zamowienia': 0, 'pozycje': 0, 'pominiete': 0, 'klienci': 0,
        'bez_numeru_bl': bez_numeru_bl, 'rozbiezne_saldo': 0,
    }

    for bl_id, pozycje in grupy.items():
        if bl_id in juz_sa:
            stat['pominiete'] += 1
            continue

        # Sortowanie deterministyczne: updated_at malejąco, przy remisie id
        # malejąco. Najświeższy wiersz wygrywa dla pól poziomu zamówienia.
        # Stara synchronizacja aktualizowała saldo na istniejących wierszach,
        # więc rozbieżność między duplikatami oznacza częściowy zapis —
        # najświeższy wiersz jest najlepszym przybliżeniem stanu faktycznego.
        # `updated_at or datetime.min` zabezpiecza sortowanie, gdyby w danych
        # historycznych (np. z bocznego importu) trafił się NULL — kolumna
        # jest dziś nullable=False, ale to skrypt jednorazowy na produkcji,
        # nie powinien wywalać się TypeError-em w środku pętli po grupach.
        pozycje_wg_swiezosci = sorted(
            pozycje, key=lambda p: (p.updated_at or datetime.min, p.id), reverse=True)
        najswiezszy = pozycje_wg_swiezosci[0]

        # Widoczność rozbieżności zamiast cichego wyboru (dawniej: MAX).
        saldo_wartosci = {_dec(p.balance_due) for p in pozycje}
        wplata_wartosci = {_dec(p.paid_amount_net) for p in pozycje}
        if len(saldo_wartosci) > 1 or len(wplata_wartosci) > 1:
            stat['rozbiezne_saldo'] += 1

        przed = SalesClient.query.count()
        klient = znajdz_lub_utworz_klienta(
            email=najswiezszy.email, nip=None,
            phone=najswiezszy.phone, nazwa=najswiezszy.customer_name,
        )
        if SalesClient.query.count() > przed:
            stat['klienci'] += 1

        zam = SalesOrder(baselinker_order_id=bl_id, client_id=klient.id)
        for pole in _POLA_ZAMOWIENIA:
            setattr(zam, pole, getattr(najswiezszy, pole, None))
        zam.balance_due = _dec(najswiezszy.balance_due)
        zam.paid_amount = _dec(najswiezszy.paid_amount_net)
        db.session.add(zam)
        db.session.flush()

        for p in pozycje:
            item = SalesOrderItem(order_id=zam.id)
            for pole in _POLA_POZYCJI:
                setattr(item, pole, getattr(p, pole, None))
            db.session.add(item)
            stat['pozycje'] += 1

        stat['zamowienia'] += 1

        # Denormalizacja klienta liczy WYŁĄCZNIE sprzedaż (partia E, punkt E5)
        # — ta sama reguła, co `ingest._przelicz_klienta`, z tej samej stałej.
        # Zamówienie anulowane i nieopłacone jest przeniesione (Arkusz ma je
        # pokazać), ale klientowi nie dolicza się ani do licznika, ani do
        # netto, ani do dat.
        if not liczy_sie_do_sprzedazy(zam.baselinker_status_id):
            continue

        netto_zamowienia = sum((_dec(p.value_net) for p in pozycje), _ZERO)
        klient.orders_count = (klient.orders_count or 0) + 1
        klient.lifetime_net = _dec(klient.lifetime_net) + netto_zamowienia
        if klient.first_order_at is None or zam.date_created < klient.first_order_at:
            klient.first_order_at = zam.date_created
        if klient.last_order_at is None or zam.date_created > klient.last_order_at:
            klient.last_order_at = zam.date_created

    return stat


def porownaj_sumy():
    """Porównuje sumy w starej i nowej strukturze. To jest bramka akceptacyjna.

    Saldo/wpłaty NIE wchodzą do flagi `zgodne` — przy rozbieżnych duplikatach
    w starej tabeli (patrz `rozbiezne_saldo`) te sumy mogą się legalnie różnić,
    a chcemy je zobaczyć w raporcie, nie blokować na nich wdrożenia.
    """
    # Obie strony porównania musza liczyc ten sam zbior wierszy: wiersze bez
    # baselinker_order_id sa swiadomie pomijane przez przenies_wiersze (patrz
    # bez_numeru_bl), wiec nowa tabela ich nie zawiera. Bez tego filtra stare
    # sumy liczylyby wiecej niz nowe i bramka falszywie zglaszalaby rozjazd
    # mimo poprawnego dzialania backfillu — ten przypadek jest juz osobno
    # raportowany jako bez_numeru_bl, nie trzeba go mieszac do tej flagi.
    stare_netto = _dec(db.session.query(func.sum(BaselinkerReportOrder.value_net))
                        .filter(BaselinkerReportOrder.baselinker_order_id.isnot(None)).scalar())
    stare_m3 = _dec(db.session.query(func.sum(BaselinkerReportOrder.total_volume))
                     .filter(BaselinkerReportOrder.baselinker_order_id.isnot(None)).scalar())
    stare_zam = db.session.query(
        func.count(func.distinct(BaselinkerReportOrder.baselinker_order_id))).scalar() or 0

    # Stare saldo/wpłata: MAX po grupach baselinker_order_id (tak jak dawniej
    # liczył je błędny kod przenies_wiersze) — dla porównania z nowym stanem,
    # NIE jako definicja poprawnego wyniku.
    stare_saldo = sum((
        _dec(x[0]) for x in db.session.query(
            func.max(BaselinkerReportOrder.balance_due))
        .filter(BaselinkerReportOrder.baselinker_order_id.isnot(None))
        .group_by(BaselinkerReportOrder.baselinker_order_id).all()
    ), _ZERO)
    stare_wplaty = sum((
        _dec(x[0]) for x in db.session.query(
            func.max(BaselinkerReportOrder.paid_amount_net))
        .filter(BaselinkerReportOrder.baselinker_order_id.isnot(None))
        .group_by(BaselinkerReportOrder.baselinker_order_id).all()
    ), _ZERO)

    nowe_netto = _dec(db.session.query(func.sum(SalesOrderItem.value_net)).scalar())
    nowe_m3 = _dec(db.session.query(func.sum(SalesOrderItem.total_volume)).scalar())
    nowe_zam = db.session.query(func.count(SalesOrder.id)).scalar() or 0
    nowe_saldo = _dec(db.session.query(func.sum(SalesOrder.balance_due)).scalar())
    nowe_wplaty = _dec(db.session.query(func.sum(SalesOrder.paid_amount)).scalar())

    roznica_netto = abs(stare_netto - nowe_netto)
    roznica_m3 = abs(stare_m3 - nowe_m3)

    return {
        'stare_netto': stare_netto, 'nowe_netto': nowe_netto,
        'stare_m3': stare_m3, 'nowe_m3': nowe_m3,
        'stare_zamowienia': stare_zam, 'nowe_zamowienia': nowe_zam,
        'stare_saldo': stare_saldo, 'nowe_saldo': nowe_saldo,
        'stare_wplaty': stare_wplaty, 'nowe_wplaty': nowe_wplaty,
        'roznica_netto': roznica_netto, 'roznica_m3': roznica_m3,
        'zgodne': roznica_netto < Decimal('0.01') and roznica_m3 < Decimal('0.000001'),
    }


def main():
    parser = argparse.ArgumentParser(description='Backfill tabel sales_*')
    parser.add_argument('--tylko-raport', action='store_true',
                        help='Nie przenoś danych, tylko porównaj sumy')
    args = parser.parse_args()

    from app import create_app
    app = create_app()
    with app.app_context():
        exit_kod = 0
        if not args.tylko_raport:
            wiersze = BaselinkerReportOrder.query.all()
            print(f"Wierszy do przeniesienia: {len(wiersze)}")
            stat = przenies_wiersze(wiersze)
            db.session.commit()
            print(f"Zamówienia: {stat['zamowienia']}, pozycje: {stat['pozycje']}, "
                  f"nowi klienci: {stat['klienci']}, pominięte: {stat['pominiete']}")
            print(f"Rozbieżne saldo/wpłata między duplikatami: {stat['rozbiezne_saldo']}")
            if stat['bez_numeru_bl'] > 0:
                print(f"\nUWAGA: {stat['bez_numeru_bl']} wierszy bez baselinker_order_id "
                      f"POMINIĘTYCH — nie da się ich przenieść idempotentnie bez dodatkowej "
                      f"kolumny wiążącej z rekordem źródłowym. Zdecyduj ręcznie, co z nimi "
                      f"zrobić.")
                exit_kod = 1

        raport = porownaj_sumy()
        print("\n=== WERYFIKACJA ===")
        print(f"Netto  stare {raport['stare_netto']:>14} | nowe {raport['nowe_netto']:>14} "
              f"| różnica {raport['roznica_netto']}")
        print(f"m³     stare {raport['stare_m3']:>14} | nowe {raport['nowe_m3']:>14} "
              f"| różnica {raport['roznica_m3']}")
        print(f"Zamówień stare {raport['stare_zamowienia']} | nowe {raport['nowe_zamowienia']}")
        print(f"Saldo  stare {raport['stare_saldo']:>14} | nowe {raport['nowe_saldo']:>14}")
        print(f"Wpłaty stare {raport['stare_wplaty']:>14} | nowe {raport['nowe_wplaty']:>14}")
        print(f"\nZGODNE: {raport['zgodne']}")

        if not raport['zgodne']:
            exit_kod = 1
        return exit_kod


if __name__ == '__main__':
    sys.exit(main())
