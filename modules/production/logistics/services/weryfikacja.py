# -*- coding: utf-8 -*-
"""
Weryfikacja paczek (logistyka etap 4, krok 4.3, spec 4.4–4.5 i 8).

Tu żyje jedna reguła unieważniania etapów (paczki, weryfikacja, załadunek) po powrocie pozycji do
produkcji, definicja listy „Do weryfikacji” i akcje stanowiska Weryfikacja. Funkcje NIE commitują —
robi to wołający (API mobilne przez @with_idempotency, panel, cron, synchronizacja).
"""
from extensions import db
from modules.production.logistics import sposoby
from modules.production.logistics.services import delivery, paczki

# Pozycje, które wracają do 'spakowane', gdy zamówienie wróci do produkcji. 'dostarczone' zostaje
# (decyzja Konrada 30.09): towar u klienta jest u klienta.
_COFANE_DO_SPAKOWANYCH = ('zweryfikowane', 'zaladowane')


def uniewaznij_etapy(order, teraz, powod, user_id=None, worker_id=None, device_id=None):
    """
    Jedna reguła (spec 4.5, ostatni wiersz, i 8.5): zamówienie, którego któraś niezanulowana pozycja
    nie jest „spakowane lub dalej” (doróbka, nowa pozycja z Base., przepakowanie, cofnięcie do
    pakowania, ręczna zmiana statusu), traci paczki (unieważnione razem z oczekującymi zadaniami
    druku), weryfikację i załadunek, a jego pozycje zweryfikowane i załadowane wracają do
    'spakowane'. Po ponownym spakowaniu zamówienie przechodzi kroki od nowa.

    `powod` — tekst do logu i komunikatu wygaszonego zadania druku (np. u'nowa pozycja z Base.').
    Zwraca True, gdy coś zmieniła. Gdy nie ma czego kasować, nie pyta bazy (czyta kolumny zamówienia
    i statusy już wczytanych pozycji) — woła ją cron dla każdego otwartego zamówienia. NIE commituje.

    Kolejność blokad: najpierw zapis wiersza zamówienia (flush), potem paczki (odczyt blokujący) —
    ta sama kolejność co w deklaracji i akcjach Weryfikacji (zamówienie → paczki), więc nie tworzy
    z nimi cyklu. Globalnej blokady deklaracji NIE bierze: wołający (panel, synchronizacja, tablet)
    trzymają już inne blokady, a wiersz blokady musiałby być pierwszy.
    """
    aktywne = delivery.aktywne_produkty(order)
    if not aktywne or all(p.current_status in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne):
        return False
    cofane = [p for p in aktywne if p.current_status in _COFANE_DO_SPAKOWANYCH]
    if order.packages_declared_at is None and order.verified_at is None and not cofane:
        return False
    notatka = (powod or u'')[:255] or None
    for p in cofane:
        p.current_status = 'spakowane'
    if order.verified_at is not None:
        order.verified_at = None
        order.verified_by_worker_id = None
        delivery.zapisz_log(order, 'weryfikacja_cofnieta', note=notatka, user_id=user_id,
                            worker_id=worker_id, device_id=device_id, teraz=teraz)
    if order.packages_declared_at is not None:
        order.packages_declared_at = None
        db.session.flush()   # wiersz zamówienia przed paczkami (kolejność blokad — docstring)
        stare = paczki.aktualne_paczki(order.id, do_zapisu=True)
        paczki.uniewaznij(stare, teraz, powod=powod)
        delivery.zapisz_log(order, 'paczki', paczki.opis_paczek(stare), None, note=notatka,
                            user_id=user_id, worker_id=worker_id, device_id=device_id, teraz=teraz)
    delivery.podbij_pozycje(order, teraz)
    return True
