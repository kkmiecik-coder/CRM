# -*- coding: utf-8 -*-
"""
Sygnały realtime dla tabletów stanowisk (spec 2026-10-04, sekcje 5.4, 9.4): kanał `station:<kod>`, sygnał BEZ
ładunku. Wzór agenta druku (`print_queue_service.zaplanuj_sygnal_po_commicie`): najpierw baza, potem sygnał — tablet
po sygnale woła `GET desk` i to ono jest źródłem prawdy. Zgubiony sygnał niczego nie psuje: tablet odpytuje `desk`
co 30 s przy pustym stole i co 5 min przy pełnym.

ZAWSZE PO COMMICIE, nigdy w transakcji: tablet obudzony przed commitem wróciłby po stary stan.
- API mobilne pod `with_idempotency` (handler nie commituje): handler tylko PLANUJE (`zaplanuj`), a dekorator po
  udanym commicie woła `wyslij()`; przy rollbacku (5xx, kody do ponowienia, wyjątek) woła `porzuc()`, a przy powtórce
  idempotentnej handler w ogóle się nie wykonuje — sygnał nie idzie.
- Routery panelu, `GET desk` i cron: `wyslij(kody…)` po własnym commicie.

`wyslij` niczego nie rzuca (`realtime_service.publish` łyka błędy brokera i zwraca False), więc awaria Centrifugo
nie zamienia się w awarię ZAKOŃCZ. Moduł nie dotyka bazy.
"""
from flask import g, has_request_context

from modules.logging import get_structured_logger
from modules.production.services import realtime_service
from modules.production.services.station_catalog import STATION_PENDING_STATUS

logger = get_structured_logger('production.priorytety.sygnaly')

# Lista kodów stanowisk w `g` żądania (w kolejności planowania, bez powtórek).
_PLAN_W_G = '_priorytety_sygnaly_stanowisk'
# Status pozycji → stanowisko, na którym czeka.
_STANOWISKO_STATUSU = {status: kod for kod, status in STATION_PENDING_STATUS.items()}


def _poprawne(kody):
    """Kody stanowisk z kolejką produktów, bez None i powtórek, w kolejności podania; nieznany kod → ostrzeżenie."""
    wynik = []
    for kod in kody:
        if kod is None or kod in wynik:
            continue
        if kod not in STATION_PENDING_STATUS:
            logger.warning('Sygnał stanowiska: nieznany kod, pomijam', extra={'kod': str(kod)[:32]})
            continue
        wynik.append(kod)
    return wynik


def zaplanuj(*kody):
    """Planuje sygnał `station:<kod>` na koniec żądania (wyśle go `wyslij()` po commicie). Poza żądaniem HTTP —
    nic nie robi (serwisy wołane z testów i skryptów)."""
    if not has_request_context():
        return
    plan = g.get(_PLAN_W_G)
    if plan is None:
        plan = []
        setattr(g, _PLAN_W_G, plan)
    for kod in _poprawne(kody):
        if kod not in plan:
            plan.append(kod)


def porzuc():
    """Rollback: zaplanowane sygnały przepadają razem z transakcją."""
    if has_request_context():
        g.pop(_PLAN_W_G, None)


def wyslij(*kody):
    """
    Wysyła sygnały: zaplanowane w tym żądaniu oraz `kody` podane wprost — po jednym na stanowisko, w kolejności
    planowania. Czyści plan. Wołać PO commicie. Zwraca kody, dla których publikacja się powiodła; niczego nie rzuca.
    """
    plan = []
    if has_request_context():
        plan = g.pop(_PLAN_W_G, None) or []
    wyslane = []
    for kod in _poprawne(list(plan) + list(kody)):
        try:
            if realtime_service.publish_station_signal(kod):
                wyslane.append(kod)
        except Exception as e:      # siatka: publish nie rzuca, ale sygnał nie może wywrócić zapisanej już akcji
            logger.error('Sygnał stanowiska: nieoczekiwany błąd publikacji', extra={'kod': kod, 'error': str(e)})
    return wyslane


def nastepne_stanowisko(item):
    """Stanowisko, na którym pozycja czeka PO przejściu statusu (po `complete_task`); None, gdy wyszła z produkcji
    (spakowana, statusy logistyczne) albo nie czeka na żadnym."""
    return _STANOWISKO_STATUSU.get(item.current_status)


def zaplanuj_po_zakonczeniu(item, station_code):
    """ZAKOŃCZ (spec 5.4): sygnał na to stanowisko (kafel zszedł — drugi tablet go zdejmie, pierwszy dociągnie
    następny) i na następne stanowisko pozycji (ma nową pracę; Formatowanie dowiaduje się o ostatniej pozycji
    zamówienia od razu, nie po 30 s — spec 5.6 p. 3)."""
    zaplanuj(station_code, nastepne_stanowisko(item))
