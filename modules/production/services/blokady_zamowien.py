# -*- coding: utf-8 -*-
"""
Kolejność blokad pisarzy zamówienia — „zamówienie najpierw” (logistyka etap 4, krok 4.4a).

Zasada (ta sama co w panelu Logistyki, Weryfikacji, deklaracji paczek, hurtowej zmianie statusu i cronie
logistyki): wiersz zamówienia FOR UPDATE po kluczu głównym → wszystkie pozycje zamówienia FOR UPDATE → dopiero
zapisy. Stanowiska (ZAKOŃCZ i wejście do pakowania), doróbka i zmiany z Base. brały dotąd pozycję przed
zamówieniem: zapisywały pozycję (flush), a zamówienie dopiero w po_spakowaniu albo w regule unieważniania
etapów. Panel trzymał zamówienie i sięgał po pozycję, więc dwie odwrotne kolejności dawały MySQL 1213
(spec 8.7, „Współbieżność”).

Oba odczyty są BIEŻĄCE (`with_for_update().populate_existing()`). MySQL pracuje na REPEATABLE READ, a migawka
transakcji powstaje przy pierwszym zwykłym odczycie (w API mobilnym: sprawdzenie powtórki X-Operation-Id),
więc zwykły odczyt po czekaniu na blokadę pokazałby stan sprzed cudzego zapisu — tak ostatni ZAKOŃCZ zamykał
cykl odbioru osobistego na sposobie „kurier” z migawki (spec 4.6, „Siatka w cronie”). Blokadę zamówienia brać
PRZED pierwszą zmianą zamówienia i pozycji: autoflush zapytania zapisałby zmienioną pozycję jeszcze przed
blokadą zamówienia (odwrotna kolejność, 1213). `populate_existing` nadpisuje atrybuty obiektów w sesji
wartościami z bazy; wcześniejsze zmiany z tej samej transakcji przetrwają dzięki autoflushowi przed zapytaniem
(z tego korzysta ponowne zablokuj_pozycje po własnych zapisach doróbki i zmian z Base.), a przy wyłączonym
autoflushu trzeba wcześniej `db.session.flush()`.

Pozycje czytamy po `order_id`, a nie po kluczach z `order.products`. Kolekcja pochodzi ze zwykłego odczytu
(migawki): pozycja dodana przez inny zapis po migawce, a przed blokadą zamówienia (zmiany z Base. tuż przed
ZAKOŃCZ), nie byłaby ani zablokowana, ani policzona, a pozycja skasowana wisiałaby w kolekcji jako „duch”
(liczyłaby się w aktywne_produkty, a podbij_pozycje dałoby StaleDataError). Odczyt bieżący po `order_id` widzi
pozycje dodane i skasowane po migawce, a jego wynik staje się kolekcją `order.products`.

Blokady następnego klucza, które ten odczyt zakłada na indeksie `order_id` (pozycje zamówienia i luka za ostatnią
z nich), nie tworzą cyklu z pisarzami tego zamówienia: doróbka i zmiany z Base. (dodanie i usunięcie pozycji)
najpierw blokują wiersz zamówienia, więc czekają już na nim. Wstawienie pozycji w cudzą lukę (pozycje NOWEGO
zamówienia z importu za ostatnim zamówieniem w indeksie, nowa pozycja zamówienia poprzedzającego w indeksie)
najwyżej czeka do końca transakcji trzymającej lukę. Na MySQL sprawdza to zadanie 3 (wyścigi kroku 4.4a).

Zablokowane zamówienie i pozycje trzymają się nawzajem silnymi referencjami (`order.products` i
`pozycja.order`). Mapa tożsamości sesji trzyma czyste obiekty SŁABO: zamówienie zablokowane odczytem bieżącym,
którego nikt nie trzymał, znikało z sesji, a późniejsze `pozycja.order` (po_spakowaniu) czytało je od nowa
zwykłym SELECT-em ze starej migawki (zadanie 3: ostatnie ZAKOŃCZ zamykało cykl odbioru osobistego na sposobie
„kurier” mimo odczytu bieżącego).

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
    Wszystkie pozycje zamówienia (także anulowane) FOR UPDATE, odczytem BIEŻĄCYM po `order_id`, rosnąco po id.
    Zwraca je w tej kolejności. Ta sama lista staje się kolekcją `order.products`, a każda pozycja dostaje
    `pozycja.order = order` (silne referencje, patrz docstring modułu). Wołać PO zablokowaniu wiersza zamówienia.

    Odczyt po `order_id` widzi pozycje dodane i skasowane po migawce transakcji, więc po wywołaniu kolekcja to
    bieżący skład zamówienia: bez „duchów” i z pozycjami dodanymi przez inny zapis. Ponowne wywołanie po własnych
    zapisach (doróbka, zmiany z Base.) odświeża kolekcję — autoflush wypycha najpierw zmiany do bazy.
    """
    pozycje = (ProductionProduct.query.filter(ProductionProduct.order_id == order.id)
               .order_by(ProductionProduct.id).with_for_update().populate_existing().all())
    # Silne referencje: mapa tożsamości trzyma czyste obiekty słabo — bez nich zablokowane zamówienie i pozycje
    # mogłyby zniknąć z sesji, a późniejsze `pozycja.order` / `order.products` przeczytałyby je od nowa zwykłym
    # SELECT-em ze starej migawki (MySQL REPEATABLE READ). set_committed_value: bez zdarzeń kolekcji i zapisu.
    set_committed_value(order, 'products', pozycje)
    for p in pozycje:
        set_committed_value(p, 'order', order)
    return pozycje


def zablokuj_zamowienie(order_id):
    """
    Zamówienie, potem wszystkie jego pozycje (odczyt bieżący; `order.products` = pozycje z tego odczytu).
    Zwraca zamówienie albo None, gdy go nie ma.
    """
    zamowienia = zablokuj_zamowienia([order_id])
    if not zamowienia:
        return None
    zablokuj_pozycje(zamowienia[0])
    return zamowienia[0]


def zablokuj_zamowienie_pozycji(product_id):
    """
    Pisarz jednej pozycji (ZAKOŃCZ i wejście do pakowania na tablecie, doróbka): zamówienie tej pozycji, potem
    wszystkie jego pozycje — ZANIM cokolwiek zapisze. Zwraca pozycję z odczytu bieżącego, powiązaną z zablokowanym
    zamówieniem (`pozycja.order`), albo None, gdy jej nie ma. `order_id` pozycji czytamy zwykłym odczytem: ta
    kolumna się nie zmienia.
    """
    wiersz = (db.session.query(ProductionProduct.order_id)
              .filter(ProductionProduct.id == product_id).first())
    if wiersz is None:
        return None
    zamowienie = zablokuj_zamowienie(wiersz.order_id)
    if zamowienie is None:
        return None
    # Pozycja z bieżącego odczytu, powiązana z zablokowanym zamówieniem (silna referencja przez `pozycja.order`);
    # skasowana po migawce → None (404, tablet ponowi albo pokaże komunikat).
    return next((p for p in zamowienie.products if p.id == product_id), None)


def kod_mysql(blad):
    """
    Kod błędu MySQL z `OperationalError` (np. 1213 = zakleszczenie, 1205 = przekroczony czas blokady) albo None,
    gdy wyjątek nie niesie kodu (brak `orig`, pusty `orig.args`). Po tym kodzie zapis ponawia się raz i tylko po
    1213: hurtowa zmiana statusu (`products_api.bulk_action`) i zmiana sposobu dostawy w panelu Logistyki
    (`panel_api.delivery_method`).
    """
    argumenty = getattr(getattr(blad, 'orig', None), 'args', None) or ()
    return argumenty[0] if argumenty else None
