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


def tresc_dla_agenta(powod, pozycje=None, dostawa=None, wycena=None, potwierdzenie=None,
                     pokazana_kwota=None):
    """Treść notatki: powód + komplet tego, co bot zdążył ustalić.

    Pozycje opisujemy przez `podsumowanie._linia` BEZ katalogu wykończeń
    (`options=None`) — ta funkcja bywa wołana na ścieżce awaryjnej (limit tur,
    guardrail, błąd), gdzie dokładanie sieciowego `crm_calc.get_options()`
    zamieniłoby brak notatki w drugą awarię. Konsultant i tak widzi surowy typ
    wykończenia, a pełną ścieżkę katalogową ma pod linkiem do wyceny."""
    from bots_pro.podsumowanie import _fmt_pln, _linia

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

    # Z4: kwota, ktora klient FAKTYCZNIE zobaczyl. Do tej poprawki notatka nie
    # drukowala ceny w ogole — konsultant, ktory przejmowal rozmowe, musial
    # odtworzyc ja z watku (zmierzone czasy reakcji: od 39 minut do 12 godzin).
    #
    # Etykieta mowi „ostatnia pokazana", a nie „cena" — bo to jest zapis
    # historyczny, nie aktualna wycena: pozycje mogly sie po wyslaniu
    # podsumowania zmienic, a ta kolumna swiadomie tego nie sledzi (patrz
    # `stan.pokazana_kwota`). Konsultant ma wiedziec, JAKA liczbe klient
    # zobaczyl, a nie ile ma mu policzyc.
    #
    # CZEGO TU CELOWO NIE MA: zdania „brakuje juz tylko jego »tak«". Jedyny
    # sygnal, ktory dalby sie pod nie podlozyc, to kolumna `oczekiwany_podpis` —
    # a ona ma DOKLADNIE JEDNEGO pisarza (`podsumowanie.wyslij`) i ZERO miejsc
    # czyszczacych, wiec przezywa jawna odmowe klienta. W produkcyjnej rozmowie
    # 4912 klient napisal „no nie pominales reszty elementow, jest ich ponad 10",
    # a `oczekiwany_podpis` dalej stal ustawiony przy kwocie osmiokrotnie
    # zanizonej (123,55 zl zamiast 993,97 zl) — notatka dalaby konsultantce
    # falszywa pewnosc dokladnie tam, gdzie potrzebna byla czujnosc. Do czasu,
    # az powstanie sygnal, ktory odmowa klienta KASUJE, notatka podaje same
    # fakty (kwota + pozycje + ewentualny cytat potwierdzenia) i zostawia ocene
    # czlowiekowi.
    if isinstance(pokazana_kwota, (int, float)):
        linie.append("Ostatnia kwota pokazana klientowi: %s brutto" % _fmt_pln(pokazana_kwota))

    wycena = wycena or {}
    if wycena.get("public_url") or wycena.get("edit_uuid"):
        linie.append("Wycena w CRM: %s (edit_uuid %s)"
                     % (wycena.get("public_url") or "brak linku",
                        wycena.get("edit_uuid") or "brak"))

    if potwierdzenie:
        linie.append("Potwierdzenie klienta: „%s”" % potwierdzenie)

    return "\n".join(linie)


def kod_notatki_ok(odpowiedz):
    """Czy Chatwoot PRZYJĄŁ notatkę (W2).

    `cw_note` zwraca obiekt odpowiedzi `requests`, a nie bool — samo „nie rzuciło
    wyjątku" NIC nie mówi o tym, czy notatka powstała. Sprawdzamy więc kod HTTP.
    Brak czytelnego `status_code` traktujemy jako sukces: produkcyjny `cw_note`
    zawsze zwraca odpowiedź `requests`, więc ta gałąź dotyczy wyłącznie atrap
    w testach — i lepiej, żeby nie generowała fałszywych alarmów."""
    kod = getattr(odpowiedz, "status_code", None)
    if kod is None:
        return True
    return 200 <= kod < 300


def wyslij_notatke(conv_id, tekst, oznacz_ture=True):
    """Wysyła notatkę. NIGDY nie rzuca — to ścieżka awaryjna, brak notatki nie
    może zablokować oddania rozmowy człowiekowi (ale MUSI być widoczny w logach,
    inaczej cichy brak notatki wygląda z zewnątrz jak jej obecność).

    W2: sprawdzamy KOD HTTP, nie tylko brak wyjątku. Wcześniejsza wersja
    meldowała sukces przy KAŻDYM kodzie, więc błędny albo wygasły
    `BOT_PRO_CW_AGENT_TOKEN` (401) przechodził jako „notatka wysłana" — a
    oznaczenie notatki w stanie tury blokowało wtedy ponowną próbę z
    `notatka_stanu`. Zły token objawiał się w notatkach CISZĄ zamiast błędem.
    `bots_pro/podsumowanie.py` wynik wysyłki sprawdza od U1 — tu jest tak samo.

    Udana notatka jest odnotowywana w stanie TURY (N7), żeby `notatka_stanu`
    nie dołożyła zaraz po niej drugiej, prawie identycznej. Zapis stanu tury
    nie może wywrócić wysyłki, która się już udała — stąd osobny `try`.

    `oznacz_ture=False` dla wołających SPOZA tury bota (dziś: `pro_watchdog`,
    przez `notatka_stanu(..., poza_tura=True)`). `stan._flagi_tury` to słownik
    MODUŁOWY, wspólny dla całego procesu — nie contextvar (patrz `stan`,
    naprawa X2) — więc zapalenie flagi z wątku watchdoga mutuje stan tury,
    którą w tej samej chwili może prowadzić worker. Skutkiem jest cicha strata
    notatki TUROWEJ: worker robi handoff, `notatka_stanu` trafia na bramkę N7
    i rezygnuje, bo „notatka w tej turze już była" — tyle że była to notatka
    watchdoga o innym zdarzeniu. Wołający spoza tury nie ma więc do
    `_flagi_tury` żadnej drogi."""
    try:
        odpowiedz = cw_note(conv_id, tekst, token=BOT_PRO_CW_AGENT_TOKEN)
    except Exception as e:
        log("notatki: notatka dla agenta NIEUDANA (conv %s): %r" % (conv_id, e))
        return False
    if not kod_notatki_ok(odpowiedz):
        log("notatki: notatka dla agenta ODRZUCONA przez Chatwoota (conv %s, HTTP %s) — "
            "sprawdz BOT_PRO_CW_AGENT_TOKEN" % (conv_id, getattr(odpowiedz, "status_code", "?")))
        return False
    if oznacz_ture:
        try:
            from bots_pro import stan
            stan.oznacz_notatke_w_turze()
        except Exception as e:   # pragma: no cover - obrona, nie sciezka
            log("notatki: nie udalo sie oznaczyc notatki w turze (conv %s): %r" % (conv_id, e))
    return True


def zamowienie_do_agenta(wycena, pozycje, dostawa, potwierdzenie, pokazana_kwota):
    """Allegro (U11, spec D8 wiersz 394): zamiast linku dla kupującego —
    notatka dla konsultanta z KOMPLETEM danych i oddanie mu rozmowy.

    Na Allegro `ALLEGRO_CAPS['links'] = False`, więc `wysylka._wytnij_linki`
    i tak skasowałby `public_url` z odpowiedzi modelu: bot obiecywałby link,
    którego kupujący nigdy nie zobaczy, i sprzedaży nie dałoby się domknąć.
    Notatka jest prywatna, więc link może w niej zostać — człowiek dostaje
    dokładnie to, czego bot nie ma prawa wysłać.

    R5: opis zamówienia przychodzi W ARGUMENTACH, jako MIGAWKA wzięta przez
    wołającego (`narzedzia.przygotuj_zamowienie`) — ta sama, na której przeszła
    bramka I2. Wcześniej ta funkcja sięgała po stan SAMA, czterema świeżymi
    odczytami (`pozycje`, `dostawa`, cytat potwierdzenia, pokazana kwota), i to
    JUŻ PO bramce, która liczyła podpis z jeszcze innego odczytu. Na Allegro ta
    notatka ZASTĘPUJE link do wyceny, więc konsultant dostawał opis zamówienia
    złożony z rozdartego stanu — i nie miał jak tego zauważyć. Argumenty są
    WYMAGANE (bez wartości domyślnych) świadomie: domyślne `None` po cichu
    przywracałoby notatkę bez pozycji, czyli gorszą wersję tego samego błędu.

    Zwraca True, gdy notatka poszła."""
    from bots_pro import stan
    tekst = tresc_dla_agenta(
        "Allegro — zamówienie do domknięcia przez konsultanta "
        "(regulamin marketplace'u zabrania wysłania linku kupującemu)",
        pozycje=pozycje, dostawa=dostawa, wycena=wycena,
        potwierdzenie=potwierdzenie, pokazana_kwota=pokazana_kwota)
    return wyslij_notatke(stan.conv_id(), tekst)


def notatka_stanu(conv_id, powod, poza_tura=False):
    """Notatka złożona z BIEŻĄCEGO stanu rozmowy (`bots_pro.stan`) — jedno
    wywołanie dla wszystkich wyjść handoffowych, żeby żadne z nich nie musiało
    samo zbierać tych samych czterech kawałków.

    N7 (rerecenzja): pomijana, gdy konsultant dostał już notatkę w TEJ turze.
    Wyjścia z własną, bogatszą notatką (Allegro w `przygotuj_zamowienie`,
    nieudane dopisanie dostawy w `zapisz_wycene`) wołają zaraz po niej
    `stan.handoff`, więc bez tego konsultant dostawał dwa wpisy o tym samym.
    Pierwsza notatka wygrywa, bo to zawsze ta konkretniejsza.

    `poza_tura=True` wyłącza tę bramkę — dla wołających, którzy NIE są w
    turze bota (dziś: `pro_watchdog`, który oddaje rozmowę z powodu ciszy
    klienta, a więc wtedy, gdy żadna tura nie trwa). Bramka N7 chroni przed
    DWIEMA notatkami o tym samym zdarzeniu w JEDNEJ turze; dla watchdoga nie
    ma „tej tury", a flagi w `stan._flagi_tury` zerują się dopiero na starcie
    następnej tury danej rozmowy — po handoffie tura już nie nadejdzie
    (`wolno_prowadzic_rozmowe` zamyka botowi drogę powrotu). Bez tego
    parametru notatka watchdoga przepadałaby po cichu dokładnie w tych
    rozmowach, w których ostatnia tura zdążyła coś do konsultanta napisać."""
    from bots_pro import stan
    if not poza_tura and stan.notatka_w_turze():
        log("notatki: notatka w tej turze juz byla — pomijam notatke stanu "
            "(conv %s, powod=%r)" % (conv_id, powod))
        return True
    try:
        tekst = tresc_dla_agenta(
            powod, pozycje=stan.pozycje(), dostawa=stan.dostawa(),
            wycena=stan.zapisana_wycena(), potwierdzenie=stan.cytat_potwierdzenia(),
            pokazana_kwota=stan.pokazana_kwota())
    except Exception as e:
        # Odczyt stanu padl — notatka z samym powodem jest wciaz lepsza niz brak.
        log("notatki: nie udalo sie zebrac stanu do notatki (conv %s): %r" % (conv_id, e))
        tekst = tresc_dla_agenta(powod)
    # `oznacz_ture=not poza_tura`: patrz `wyslij_notatke`. Bramka N7 to nie
    # jedyne miejsce, w ktorym `_flagi_tury` ma znaczenie — wolajacy spoza tury
    # ma tego slownika w ogole nie dotykac, ani czytajac, ani pisząc.
    return wyslij_notatke(conv_id, tekst, oznacz_ture=not poza_tura)
