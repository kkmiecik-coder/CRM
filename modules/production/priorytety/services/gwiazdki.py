# -*- coding: utf-8 -*-
"""
Gwiazdki zamówienia (0–5) — priorytet, który biuro nadaje zamówieniu (spec 2026-10-04, sekcje 3.1, 9.2, 9.4).

Kolejność blokad: zamówienia FOR UPDATE rosnąco po id (`blokady_zamowien.zablokuj_zamowienia`) → zapis zamówień
i wpisów logu (FK do już zablokowanego zamówienia). Bez blokady tras i bez pozycji.

Serwis nie commituje i nie przelicza rang. Router woła: `db.session.commit()` (koniec transakcji z migawką sprzed
blokady) → `ustaw()` → `db.session.commit()` → `kolejka.utrwal_po_commicie()`.
"""
from extensions import db
from modules.production.models import get_local_now
from modules.production.priorytety import stale
from modules.production.priorytety.models import PriorityLog
from modules.production.services import blokady_zamowien


class BladGwiazdek(Exception):
    """Zła wartość gwiazdek albo lista zamówień — `komunikat` po polsku (router odpowiada 400)."""

    def __init__(self, komunikat):
        super(BladGwiazdek, self).__init__(komunikat)
        self.komunikat = komunikat


def _liczba(wartosc):
    """Liczba całkowita, ale nie bool (True to w Pythonie także int)."""
    return isinstance(wartosc, int) and not isinstance(wartosc, bool)


def ustaw(order_ids, gwiazdki, user_id=None, teraz=None):
    """
    Ustawia `gwiazdki` (0..5) zamówieniom `order_ids` (od 1 do `stale.LIMIT_HURTU` identyfikatorów). Zapisuje tylko
    zamówienia, którym wartość się zmienia: `priority_stars`, czas i autora zmiany oraz wpis `gwiazdki` w logu.

    Zwraca `{'zmienione': [id], 'bez_zmian': [id], 'brak': [id]}` (listy rosnąco). Złe dane → `BladGwiazdek`,
    zanim pójdzie jakiekolwiek zapytanie. Nie commituje.
    """
    if not _liczba(gwiazdki) or not 0 <= gwiazdki <= stale.GWIAZDKI_MAX:
        raise BladGwiazdek(u'Podaj liczbę gwiazdek od 0 do {}.'.format(stale.GWIAZDKI_MAX))
    if not isinstance(order_ids, (list, tuple, set, frozenset)) or not order_ids:
        raise BladGwiazdek(u'Podaj od 1 do {} zamówień.'.format(stale.LIMIT_HURTU))
    if len(order_ids) > stale.LIMIT_HURTU or not all(_liczba(i) for i in order_ids):
        raise BladGwiazdek(u'Podaj od 1 do {} zamówień.'.format(stale.LIMIT_HURTU))

    ids = sorted(set(order_ids))
    teraz = teraz or get_local_now()
    # Blokada jest PIERWSZYM zapytaniem: odczyt bieżący zamówień, rosnąco po id.
    zamowienia = blokady_zamowien.zablokuj_zamowienia(ids)
    znalezione = {zamowienie.id for zamowienie in zamowienia}

    zmienione, bez_zmian = [], []
    for zamowienie in zamowienia:
        stare = int(zamowienie.priority_stars or 0)
        if stare == gwiazdki:
            bez_zmian.append(zamowienie.id)
            continue
        zamowienie.priority_stars = gwiazdki
        zamowienie.priority_stars_set_at = teraz
        zamowienie.priority_stars_set_by = user_id
        db.session.add(PriorityLog(action='gwiazdki', order_id=zamowienie.id, old_value=str(stare),
                                   new_value=str(gwiazdki), user_id=user_id, created_at=teraz))
        zmienione.append(zamowienie.id)
    db.session.flush()
    return {'zmienione': zmienione, 'bez_zmian': bez_zmian, 'brak': [i for i in ids if i not in znalezione]}
