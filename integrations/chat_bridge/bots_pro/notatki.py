# -*- coding: utf-8 -*-
"""
Prywatna notatka dla konsultanta (U7, U11).

Do tej poprawki w całym `bots_pro/` nie było ani jednego `cw_note`. Skutek:
konsultant dostawał rozmowę przełączoną do 'open' i musiał sam zgadnąć, co bot
zdążył ustalić i dlaczego przestał. Stary silnik robi to od dawna
(`bots.quotebot._do_handoff` — notatka z zebranymi danymi + komunikat
zamknięcia dla klienta), więc to jest wyrównanie do stanu, który już działa
w produkcji, nie nowy pomysł.

Notatka jest PRYWATNA (`private: true` w Chatwoocie) — klient jej nie widzi,
więc może zawierać ceny, identyfikator wyceny i link do niej NAWET na Allegro,
gdzie regulamin zabrania kierowania KUPUJĄCEGO poza platformę. To rozróżnienie
jest istotą ścieżki z D8: na Allegro link do wyceny idzie do CZŁOWIEKA
w notatce, nie do kupującego w wiadomości (patrz `bots_pro.narzedzia.
przygotuj_zamowienie`).

Token: JAWNIE `BOT_PRO_CW_AGENT_TOKEN` — domyślny `cw_note` sięga po token
admina, a notatka podpisana innym botem myli konsultanta co do tego, który
silnik prowadził rozmowę (ten sam powód, dla którego jawny token ma
`stan.handoff` i `pro_watchdog`).
"""
from config import BOT_PRO_CW_AGENT_TOKEN
from core.chatwoot import cw_note
from core.log import log

_PREFIKS = "🤖 Dębuś Pro"


def _linia_dostawy(dostawa):
    """Jedna linia opisu dostawy albo None, gdy nie ma czego opisać."""
    dostawa = dostawa or {}
    kod = dostawa.get("kod_pocztowy")
    kurier = dostawa.get("kurier")
    if not (kod or kurier):
        return None
    czesci = []
    if kurier:
        czesci.append(str(kurier))
    brutto = dostawa.get("brutto")
    if isinstance(brutto, (int, float)):
        czesci.append("%.2f zł brutto" % brutto)
    if kod:
        czesci.append("kod %s" % kod)
    return "Dostawa: " + ", ".join(czesci)


def tresc_dla_agenta(powod, pozycje=None, dostawa=None, wycena=None, potwierdzenie=None):
    """Treść notatki: powód + komplet tego, co bot zdążył ustalić.

    Pozycje opisujemy przez `podsumowanie._linia` BEZ katalogu wykończeń
    (`options=None`) — ta funkcja bywa wołana na ścieżce awaryjnej (limit tur,
    guardrail, błąd), gdzie dokładanie sieciowego `crm_calc.get_options()`
    zamieniłoby brak notatki w drugą awarię. Konsultant i tak widzi surowy typ
    wykończenia, a pełną ścieżkę katalogową ma pod linkiem do wyceny."""
    from bots_pro.podsumowanie import _linia

    linie = ["%s przekazuje rozmowę konsultantowi." % _PREFIKS,
             "Powód: %s" % (powod or "nie podano")]

    if pozycje:
        linie.append("")
        linie.append("Zebrane pozycje:")
        linie.extend(_linia(poz) for poz in pozycje)
    else:
        linie.append("Zebrane pozycje: brak")

    opis_dostawy = _linia_dostawy(dostawa)
    if opis_dostawy:
        linie.append(opis_dostawy)

    wycena = wycena or {}
    if wycena.get("public_url") or wycena.get("edit_uuid"):
        linie.append("Wycena w CRM: %s (edit_uuid %s)"
                     % (wycena.get("public_url") or "brak linku",
                        wycena.get("edit_uuid") or "brak"))

    if potwierdzenie:
        linie.append("Potwierdzenie klienta: „%s”" % potwierdzenie)

    return "\n".join(linie)


def wyslij_notatke(conv_id, tekst):
    """Wysyła notatkę. NIGDY nie rzuca — to ścieżka awaryjna, brak notatki nie
    może zablokować oddania rozmowy człowiekowi (ale MUSI być widoczny w logach,
    inaczej cichy brak notatki wygląda z zewnątrz jak jej obecność)."""
    try:
        cw_note(conv_id, tekst, token=BOT_PRO_CW_AGENT_TOKEN)
        return True
    except Exception as e:
        log("notatki: notatka dla agenta NIEUDANA (conv %s): %r" % (conv_id, e))
        return False


def notatka_stanu(conv_id, powod):
    """Notatka złożona z BIEŻĄCEGO stanu rozmowy (`bots_pro.stan`) — jedno
    wywołanie dla wszystkich wyjść handoffowych, żeby żadne z nich nie musiało
    samo zbierać tych samych czterech kawałków."""
    from bots_pro import stan
    try:
        tekst = tresc_dla_agenta(
            powod, pozycje=stan.pozycje(), dostawa=stan.dostawa(),
            wycena=stan.zapisana_wycena(), potwierdzenie=stan.cytat_potwierdzenia())
    except Exception as e:
        # Odczyt stanu padl — notatka z samym powodem jest wciaz lepsza niz brak.
        log("notatki: nie udalo sie zebrac stanu do notatki (conv %s): %r" % (conv_id, e))
        tekst = tresc_dla_agenta(powod)
    return wyslij_notatke(conv_id, tekst)
