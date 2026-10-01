# -*- coding: utf-8 -*-
"""
Kolejność blokad pisarzy zamówienia — „zamówienie najpierw” (logistyka etap 4, krok 4.4a).

Zasada (ta sama co w panelu Logistyki, Weryfikacji, deklaracji paczek, hurtowej zmianie statusu i cronie
logistyki): wiersz zamówienia FOR UPDATE po kluczu głównym → pozycje zamówienia FOR UPDATE po kluczu głównym
→ dopiero zapisy. Stanowiska (ZAKOŃCZ i wejście do pakowania), doróbka i zmiany z Base. brały dotąd pozycję przed
zamówieniem: zapisywały pozycję (flush), a zamówienie dopiero w po_spakowaniu albo w regule unieważniania
etapów. Panel trzymał zamówienie i sięgał po pozycję, więc dwie odwrotne kolejności dawały MySQL 1213
(spec 8.7, „Współbieżność”).

Oba odczyty są BIEŻĄCE (`with_for_update().populate_existing()`). MySQL pracuje na REPEATABLE READ, a migawka
transakcji powstaje przy pierwszym zwykłym odczycie (w API mobilnym: sprawdzenie powtórki X-Operation-Id),
więc zwykły odczyt po czekaniu na blokadę pokazałby stan sprzed cudzego zapisu — tak ostatni ZAKOŃCZ zamykał
cykl odbioru osobistego na sposobie „kurier” z migawki (spec 4.6, „Siatka w cronie”). `populate_existing`
nadpisuje atrybuty obiektów już wczytanych do sesji: funkcje wołać PRZED pierwszą zmianą zamówienia i pozycji
w tej transakcji, inaczej niezapisane zmiany przepadną.

Lista kluczy pozycji pochodzi z `order.products` (zwykły odczyt), jak w paczki.zablokuj_stan: blokada po
`order_id` zakładałaby blokady luk indeksu. Pozycja dodana przez inny zapis po migawce, a przed blokadą
zamówienia, nie zostanie więc zablokowana ani policzona. Zmiany z Base. biorą tę samą blokadę zamówienia przed
dodaniem pozycji, więc okno jest rzędu milisekund, a resztę łata cron logistyki (przelicz_otwarte).
Pozycja SKASOWANA po migawce (Base. kasuje na twardo, od kroku 4.4a pod blokadą zamówienia) wisiałaby w tej
kolekcji ze stanem z migawki, a blokada po kluczu głównym jej nie znajduje: zablokuj_pozycje wyrzuca ją z
`order.products` (liczyłaby się w aktywne_produkty, a podbij_pozycje dałoby StaleDataError).

Funkcje nie commitują.
"""
from sqlalchemy.orm.attributes import set_committed_value

from extensions import db
from modules.production.models import ProductionOrder, ProductionProduct


def zablokuj_zamowienia(order_ids):
    """
    Wiersze zamówień `order_ids` FOR UPDATE, rosnąco po id — jedna kolejność dla zapisów, które blokują kilka
    zamówień (jak hurtowa zmiana statusu i cron). Odczyt bieżący. Zwraca zamówienia w tej kolejności, bez
    `None` i bez nieistniejących; pusta lista → [] bez zapytania.
    """
    ids = sorted({i for i in order_ids if i is not None})
    if not ids:
        return []
    return (ProductionOrder.query.filter(ProductionOrder.id.in_(ids)).order_by(ProductionOrder.id)
            .with_for_update().populate_existing().all())


def zablokuj_pozycje(order):
    """
    Wszystkie pozycje zamówienia (także anulowane) FOR UPDATE po kluczu głównym, rosnąco, odczytem bieżącym.
    Zwraca je w tej kolejności. Wołać PO zablokowaniu wiersza zamówienia.

    Kolekcja `order.products` pochodzi z migawki. Pozycje skasowane po niej znikają z kolekcji (usuwamy tylko te,
    których blokada nie znalazła; kolejność pozostałych i ewentualne niezapisane pozycje bez zmian), a dodane po
    migawce nadal są niewidoczne, jak dotąd — nie da się ich zablokować po kluczu głównym.
    """
    ids = sorted(p.id for p in order.products if p.id is not None)
    if not ids:
        return []
    zablokowane = (ProductionProduct.query.filter(ProductionProduct.id.in_(ids)).order_by(ProductionProduct.id)
                   .with_for_update().populate_existing().all())
    skasowane = set(ids) - {p.id for p in zablokowane}
    if skasowane:
        # set_committed_value: korekta pamięci, bez zdarzeń kolekcji (delete-orphan, backref) i bez zapisu w bazie.
        set_committed_value(order, 'products', [p for p in order.products if p.id not in skasowane])
    return zablokowane


def zablokuj_zamowienie(order_id):
    """Zamówienie, potem wszystkie jego pozycje (odczyt bieżący). Zwraca zamówienie albo None, gdy go nie ma."""
    zamowienia = zablokuj_zamowienia([order_id])
    if not zamowienia:
        return None
    zablokuj_pozycje(zamowienia[0])
    return zamowienia[0]


def zablokuj_zamowienie_pozycji(product_id):
    """
    Pisarz jednej pozycji (ZAKOŃCZ i wejście do pakowania na tablecie, doróbka): zamówienie tej pozycji, potem
    wszystkie jego pozycje — ZANIM cokolwiek zapisze. Zwraca pozycję po odczycie bieżącym albo None, gdy jej nie
    ma. `order_id` pozycji czytamy zwykłym odczytem: ta kolumna się nie zmienia.
    """
    wiersz = (db.session.query(ProductionProduct.order_id)
              .filter(ProductionProduct.id == product_id).first())
    if wiersz is None:
        return None
    zablokuj_zamowienie(wiersz.order_id)
    return (ProductionProduct.query.filter(ProductionProduct.id == product_id)
            .with_for_update().populate_existing().one_or_none())
