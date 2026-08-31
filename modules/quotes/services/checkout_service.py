# -*- coding: utf-8 -*-
"""
Składanie zamówienia przez klienta ze strony wyceny.

BaselinkerService.create_order_from_quote nie ma żadnej idempotencji — w panelu
chroni to operator i confirm() w JS, ale checkout jest publiczny i przyjmuje
podwójne kliknięcie oraz retry przeglądarki. Druga próba utworzyłaby drugie
realne zamówienie i nadpisała base_linker_order_id, osierocając pierwsze
(zamówienia w BaseLinkerze nie da się cofnąć jednym ruchem).

Dlatego wiersz wyceny blokujemy (SELECT ... FOR UPDATE) i sprawdzamy warunek
POD blokadą, na wartości wczytanej świeżo z bazy — patrz zablokuj_wycene().
"""
from extensions import db
from modules.baselinker.service import BaselinkerService
from modules.calculator.models import Quote
from modules.quotes.services.checkout_config import build_checkout_order_config


def zablokuj_wycene(quote):
    """Blokuje wiersz wyceny do końca transakcji i zwraca ŚWIEŻY stan.

    Wzorzec blokady jak w modules/calculator/services/quote_service.py:481,
    ale z populate_existing(). Bez niego blokada byłaby dekoracją: SQLAlchemy
    zwraca dla wczytanego już wiersza ten sam obiekt z identity map i NIE
    nadpisuje jego atrybutów danymi z nowego SELECT-a. Drugie żądanie
    doczekałoby swojej kolei na blokadzie, po czym przeczytałoby własną,
    nieaktualną kopię wiersza (base_linker_order_id = NULL) i złożyło drugie
    zamówienie — czyli dokładnie to, przed czym blokada miała chronić.

    Zwraca None, gdy wiersz zniknął (wycena usunięta w międzyczasie).
    """
    return (Quote.query
            .populate_existing()
            .filter_by(id=quote.id)
            .with_for_update()
            .first())


def _numer_zamowienia(wartosc):
    """base_linker_order_id -> int, a gdy w kolumnie tekstowej siedzi coś innego,
    oddajemy wartość bez zmian. Powtórka nie ma prawa wywalić się wyjątkiem —
    zamówienie już istnieje i klient ma je zobaczyć."""
    try:
        return int(wartosc)
    except (TypeError, ValueError):
        return wartosc


def _odpowiedz(ok, order_id=None, order_page_url=None, duplikat=False, error=None,
               niepewne=False):
    """`niepewne` = nie wiemy, czy zamówienie w BaseLinkerze powstało.

    Ustawia je wyłącznie ścieżka błędu transportowego (patrz create_order_from_quote).
    Przy takim wyniku nie wolno ani twierdzić, że zamówienie jest, ani że go nie ma,
    ani zapraszać klienta do ponowienia.
    """
    return {
        "ok": ok,
        "order_id": order_id,
        "order_page_url": order_page_url,
        "duplikat": duplikat,
        "error": error,
        "niepewne": niepewne,
    }


def zloz_zamowienie_klienta(quote, order_source_id, bot_user_id):
    """Tworzy zamówienie w BaseLinkerze dla zaakceptowanej wyceny.

    Zwraca {"ok", "order_id", "order_page_url", "duplikat", "error", "niepewne"}.
    Nie rzuca wyjątków — create_order_from_quote też ich nie propaguje.
    """
    zablokowana = zablokuj_wycene(quote)
    if zablokowana is None:
        # Wiersz zniknął spod blokady — nie ma czego zamawiać i nie ma na czym
        # oprzeć guardu, więc odmawiamy zamiast strzelać do BaseLinkera.
        return _odpowiedz(False, error="NIEKWALIFIKOWANA")

    # Sprawdzenie POD blokadą — inaczej dwa równoległe żądania oba je przejdą.
    if zablokowana.base_linker_order_id:
        return _odpowiedz(
            True,
            order_id=_numer_zamowienia(zablokowana.base_linker_order_id),
            order_page_url=zablokowana.baselinker_order_page,
            duplikat=True,
        )

    if not zablokowana.is_eligible_for_order():
        return _odpowiedz(False, error="NIEKWALIFIKOWANA")

    config = build_checkout_order_config(zablokowana, order_source_id)
    wynik = BaselinkerService().create_order_from_quote(zablokowana, bot_user_id, config)

    if not wynik.get("success"):
        # Serwis nie robi rollbacku w żadnej ścieżce, a base_linker_order_id
        # nie został zapisany — zostawiamy sesję czystą. Uwaga: „nie zapisany"
        # NIE znaczy „zamówienia nie ma" (patrz niepewne) — o tym, czy klient
        # może powtórzyć, rozstrzyga flaga, a nie sam brak zapisu.
        db.session.rollback()
        return _odpowiedz(False, error=wynik.get("error") or "BLAD_BASELINKER",
                          niepewne=bool(wynik.get("niepewne")))

    return _odpowiedz(
        True,
        order_id=wynik.get("order_id"),
        order_page_url=zablokowana.baselinker_order_page,
    )
