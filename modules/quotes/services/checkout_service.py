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

JAK DŁUGO WISI BLOKADA. Od `zablokuj_wycene()` do commitu wewnątrz
`create_order_from_quote`, czyli przez całe wywołanie `addOrder` (timeout HTTP
30 s). Krócej się nie da bez utraty ochrony: warunek „czy ta wycena ma już
zamówienie" musi być prawdziwy w chwili, w której strzelamy do BaseLinkera,
a nie tylko chwilę wcześniej. Zwolnienie blokady na czas wywołania wymagałoby
zaklepania wyceny osobną kolumną („próba w toku") — czyli migracji i drugiego
stanu do sprzątania; ochronę przed skutkami trzymania blokady daje taniej
zapis ratunkowy numeru zamówienia w BaselinkerService (lock wait timeout
i zerwane połączenie nie kończą się już fałszywym „zamówienia nie ma").
Uwaga: `getOrders` po order_page leci JUŻ PO tym commicie, więc drugiego
okna 30 s pod blokadą nie ma.
"""
from extensions import db
from modules.baselinker.models import BaselinkerOrderLog, STATUS_PROBA_NIEPEWNA
from modules.baselinker.service import BaselinkerService
from modules.calculator.models import Quote
from modules.quotes.services.checkout_config import build_checkout_order_config

__all__ = ['STATUS_PROBA_NIEPEWNA', 'zablokuj_wycene',
           'istnieje_nierozstrzygnieta_proba', 'zloz_zamowienie_klienta']


def istnieje_nierozstrzygnieta_proba(quote_id):
    """Czy na wycenie wisi próba zamówienia, której losu nie znamy.

    To jest znacznik trwały — w odróżnieniu od blokady w JavaScripcie, którą
    odświeżenie strony kasowało w całości. Po timeoucie numer zamówienia nie
    zapisuje się na wycenie, więc guard idempotencji jest ślepy: bez tego
    znacznika F5 po komunikacie „nie wiemy" przywracał aktywny przycisk
    i kończył się DRUGIM realnym zamówieniem.

    Znacznik zdejmuje się sam w chwili, w której wycena dostaje numer
    zamówienia (guard duplikatu rozstrzyga wcześniej). Gdy zamówienia jednak
    nie było, sprawę zamyka człowiek — zgodnie z komunikatem, który klient
    dostał: „skontaktuj się z nami".
    """
    return db.session.query(BaselinkerOrderLog.id).filter_by(
        quote_id=quote_id,
        action='create_order',
        status=STATUS_PROBA_NIEPEWNA,
    ).first() is not None


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
               niepewne=False, zamowienie_utworzone=False):
    """Trzy różne prawdy o nieudanej próbie — mylenie ich kosztuje pieniądze.

    `niepewne` = nie wiemy, czy zamówienie w BaseLinkerze powstało. Ustawia je
    ścieżka błędu transportowego (patrz create_order_from_quote). Przy takim
    wyniku nie wolno ani twierdzić, że zamówienie jest, ani że go nie ma, ani
    zapraszać klienta do ponowienia.

    `zamowienie_utworzone` = zamówienie NA PEWNO istnieje (addOrder potwierdził),
    a nie udało się zapisać jego numeru na wycenie. Wiedza mocniejsza niż
    `niepewne`: klientowi mówimy wprost, że zamówienie zostało złożone.

    Obie na False = zamówienia NA PEWNO nie ma i powtórka jest bezpieczna.
    """
    return {
        "ok": ok,
        "order_id": order_id,
        "order_page_url": order_page_url,
        "duplikat": duplikat,
        "error": error,
        "niepewne": niepewne,
        "zamowienie_utworzone": zamowienie_utworzone,
    }


def zloz_zamowienie_klienta(quote, order_source_id, bot_user_id,
                            is_self_pickup=False):
    """Tworzy zamówienie w BaseLinkerze dla zaakceptowanej wyceny.

    is_self_pickup — wybór klienta z bieżącego formularza. Musi tu dojechać,
    bo dla wyceny zaakceptowanej wcześniej nie ma go już skąd odczytać: dane
    dostawy zapisuje wyłącznie akceptacja, a ta się wtedy nie wykonuje.

    Zwraca {"ok", "order_id", "order_page_url", "duplikat", "error", "niepewne",
    "zamowienie_utworzone"}. Nie rzuca wyjątków — create_order_from_quote też
    ich nie propaguje.
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

    # Po nierozstrzygniętej próbie NIE wolno strzelać do BaseLinkera drugi raz:
    # tamto zamówienie mogło powstać, a my nie mamy jak tego sprawdzić.
    if istnieje_nierozstrzygnieta_proba(zablokowana.id):
        return _odpowiedz(False, error="NIEPEWNA_PROBA", niepewne=True)

    if not zablokowana.is_eligible_for_order():
        return _odpowiedz(False, error="NIEKWALIFIKOWANA")

    config = build_checkout_order_config(zablokowana, order_source_id,
                                         is_self_pickup=is_self_pickup)
    wynik = BaselinkerService().create_order_from_quote(zablokowana, bot_user_id, config)

    if not wynik.get("success"):
        utworzone = bool(wynik.get("zamowienie_utworzone"))
        if not utworzone:
            # base_linker_order_id nie został zapisany — zostawiamy sesję czystą.
            # Gdy zamówienie JEDNAK powstało, serwis zdążył już zrobić własny
            # rollback i zapis ratunkowy: kolejny rollback tutaj mógłby wywalić
            # ten zapis, a to on broni przed drugim realnym zamówieniem.
            db.session.rollback()
        # Uwaga: „nie zapisany" NIE znaczy „zamówienia nie ma" — o tym, czy
        # klient może powtórzyć, rozstrzygają flagi, a nie sam brak zapisu.
        return _odpowiedz(False, error=wynik.get("error") or "BLAD_BASELINKER",
                          order_id=wynik.get("order_id"),
                          niepewne=bool(wynik.get("niepewne")),
                          zamowienie_utworzone=utworzone)

    return _odpowiedz(
        True,
        order_id=wynik.get("order_id"),
        order_page_url=zablokowana.baselinker_order_page,
    )
