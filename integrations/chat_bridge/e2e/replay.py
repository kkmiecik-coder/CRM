# -*- coding: utf-8 -*-
"""
Odtwarzanie zapisanych rozmów (audyt produkcji) przeciwko bieżącej
konfiguracji modeli Dębusia Pro — Task 9, harness ewaluacyjny.

Użycie:
    python e2e/replay.py sciezka/do/shard_1.txt [shard_2.txt ...]

Transkrypty NIGDY nie leżą w repo — zawierają dane osobowe klientów (nazwiska,
adresy dostawy, telefony), a repo auto-deployuje się na produkcję. Podaj
ścieżkę bezwzględną poza repo (np. ~/Documents/woodpower-eval-dane/). Testy
tego modułu jeżdżą na SYNTETYCZNYCH fixture'ach w `e2e/dane/` — w pełni
zmyślonych, bez żadnych prawdziwych danych klientów.

Konfiguracja modeli idzie ze zmiennych MODEL_* (patrz bots_pro/models.py) —
porównanie dostawców (OpenAI <-> Anthropic) to uruchomienie TEGO SAMEGO
polecenia z inną wartością, np.:
    MODEL_WYCENA=litellm/anthropic/claude-sonnet-5 \\
    MODEL_WIEDZA=litellm/anthropic/claude-sonnet-5 \\
    MODEL_POSPRZEDAZ=litellm/anthropic/claude-sonnet-5 \\
    MODEL_ROUTER=litellm/anthropic/claude-sonnet-5 \\
    ANTHROPIC_API_KEY=... python e2e/replay.py ...

BEZPIECZEŃSTWO (krytyczne — harness NIE MOŻE pisać do prawdziwego Chatwoota
ani go odpytywać siecią). `bots_pro.tura` importuje `cw_agent_reply` PRZEZ
NAZWĘ (`from core.chatwoot import cw_agent_reply`) — ta linia WIĄŻE referencję
w przestrzeni nazw `tura` RAZ, przy imporcie modułu. Podmiana atrybutu na
module źródłowym `core.chatwoot` PO fakcie (naiwne podejście, jakie sugerował
pierwotny brief tego zadania) nie ma WIĘC żadnego wpływu na to, co
`tura.uruchom()` faktycznie wywołuje — trzeba podmienić `tura.cw_agent_reply`
i `tura.Runner` (oba importowane przez nazwę), NIE ich moduły źródłowe.
`stan.handoff`/`stan.wolno_prowadzic_rozmowe` są używane przez `tura.py` jako
atrybuty MODUŁU (`from bots_pro import stan`, potem `stan.handoff(...)`), więc
dla nich wystarczy podmiana atrybutu modułu — `odtworz()` niżej traktuje oba
przypadki jednolicie (`_podmien`), żeby przyszła zmiana stylu importu w
tura.py nie przemyciła po cichu regresji w tym punkcie. Zobacz
tests/test_replay_odtworz.py::TestPrzechwycenieWysylki — to WŁAŚNIE ten błąd
(podmiana złego miejsca) ma tam złapać.

Import `bots_pro.tura` (a więc i `agents`) jest LENIWY — dopiero wewnątrz
`odtworz()` — żeby parser transkryptów (`wczytaj_rozmowy`) dawał się używać
(i testować) TAKŻE bez zainstalowanego SDK, ten sam wzorzec co w
tests/test_pro_tura.py.
"""
import contextlib
import os
import re
import sys
import time

_NAGLOWEK_RE = re.compile(r"^ROZMOWA\s*#\s*(\d+)")
_LINIA_RE = re.compile(
    r"^\[[^\]]*\]\s*(KLIENT|BOT|AGENT|NOTATKA-PRYW|SYSTEM):\s*(.*)$")


def wczytaj_rozmowy(sciezka):
    """Parsuje plik transkryptu (format audytu produkcji) na listę rozmów:
    [{'id': int, 'wiadomosci': [(kto, tresc), ...]}, ...].

    Nagłówek `ROZMOWA #<id>` zaczyna nową rozmowę — dalszy tekst nagłówka
    (data, inbox...) jest ignorowany, liczy się tylko numer. Wiadomość to
    `[czas] KTO: treść`, KTO w {KLIENT, BOT, AGENT, NOTATKA-PRYW, SYSTEM}.
    UWAGA: „AGENT" w tym formacie to CZŁOWIEK-konsultant z Chatwoota
    (sender.type == "user"), NIE agent wyspecjalizowany Agents SDK (Wycena/
    Wiedza/Posprzedaz z bots_pro/agenci.py) — to dwa różne pojęcia o tej
    samej nazwie, jedno z transkryptu (dane), drugie z architektury bota
    (kod). `odtworz()` niżej korzysta WYŁĄCZNIE z linii KLIENT — reszta jest
    tu i tak sparsowana (nie odrzucana), żeby wywołujący mógł np. policzyć,
    ile razy STARY bot się powtarzał, do porównania z nowym.

    Linie, które nie pasują do żadnego wzorca — puste ALBO kontynuacja
    wieloliniowej wiadomości (realne transkrypty łamią np. adres dostawy na
    kilka linii) — są DOKLEJANE do OSTATNIO rozpoznanej wiadomości TEJ
    rozmowy. Puste linie same nie doklejają się, ale NIE zamykają też
    możliwości doklejenia kolejnej niepustej linii do tej samej wiadomości —
    akapit rozdzielony pustą linią to wciąż JEDNA wiadomość."""
    rozmowy = []
    biezaca = None
    ostatnia = None  # [kto, tresc] — mutowalna referencja do domklejania
    with open(sciezka, encoding="utf-8") as plik:
        for surowa in plik:
            linia = surowa.rstrip("\n\r")
            naglowek = _NAGLOWEK_RE.match(linia)
            if naglowek:
                biezaca = {"id": int(naglowek.group(1)), "wiadomosci": []}
                rozmowy.append(biezaca)
                ostatnia = None
                continue
            if biezaca is None:
                continue  # tekst przed pierwszym naglowkiem — ignorujemy
            trafienie = _LINIA_RE.match(linia)
            if trafienie:
                ostatnia = [trafienie.group(1), trafienie.group(2)]
                biezaca["wiadomosci"].append(ostatnia)
            elif linia.strip() and ostatnia is not None:
                ostatnia[1] = (ostatnia[1] + "\n" + linia).strip()
    for rozmowa in rozmowy:
        rozmowa["wiadomosci"] = [(k, t) for k, t in rozmowa["wiadomosci"]]
    return rozmowy


@contextlib.contextmanager
def _podmien(obiekt, atrybut, nowa_wartosc):
    """Podmienia `obiekt.atrybut` na czas bloku `with`, gwarantując
    przywrócenie oryginału (nawet po wyjątku). Odpowiednik `monkeypatch` z
    pytest — ale `replay.py` działa POZA testami (skrypt CLI), gdzie
    `monkeypatch` nie istnieje."""
    stara_wartosc = getattr(obiekt, atrybut)
    setattr(obiekt, atrybut, nowa_wartosc)
    try:
        yield
    finally:
        setattr(obiekt, atrybut, stara_wartosc)


def odtworz(rozmowa, conv_id_bazowy=900000):
    """Odtwarza JEDNĄ rozmowę: kolejne wiadomości KLIENTA idą do
    `tura.uruchom()` — prawdziwy Router, prawdziwi agenci wyspecjalizowani,
    prawdziwe narzędzia/kalkulator CRM, prawdziwe guardraile (I1 integralność
    ceny/G1, I2 potwierdzenie klienta) — harness ma te inwarianty MIERZYĆ, nie
    omijać. Jedyne, co jest przechwycone (nigdy nie leci siecią do
    prawdziwego Chatwoota): wysłanie odpowiedzi do klienta, oddanie rozmowy
    konsultantowi i odczyt statusu/historii rozmowy (bramka ciszy po
    handoffie, `stan.wolno_prowadzic_rozmowe`) — syntetyczny `conv_id`
    (`conv_id_bazowy + rozmowa['id']`) i tak nie odpowiada żadnej realnej
    rozmowie w Chatwoocie, więc bez tego przechwycenia każda tura kończyłaby
    się błędem sieci (albo, gdyby akurat trafiła na istniejące konto/ID,
    czymś dużo gorszym: realnym zapisem).

    Zwraca dict:
      odpowiedzi      — publiczne odpowiedzi bota, w kolejności (jedna tura
                        klienta może dać 0 lub więcej — zwykle 1, 0 gdy bot
                        milczał/został zablokowany guardrailem bez udanej
                        korekty)
      handoff         — czy w KTÓREJKOLWIEK turze doszło do oddania rozmowy
                        konsultantowi
      trasa           — nazwy agentów SDK (Router/Wycena/Wiedza/Posprzedaz),
                        którzy faktycznie odpowiedzieli — jedna pozycja na
                        KAŻDE wywołanie Runner.run_sync (jedna tura klienta
                        może wywołać go dwa razy, gdy G1 zażąda korekty)
      uzycia          — obiekty Usage z SDK (jeden na wywołanie
                        Runner.run_sync) — surowiec dla
                        `kryteria.koszt_rozmowy`
      czasy_tur       — sekundy na KAŻDĄ wiadomość KLIENTA (jedna tura może
                        zrobić 1-2 wywołania Runnera w środku — to CAŁKOWITY
                        czas tej tury, nie pojedynczego wywołania modelu)
      kwoty_niezgodne — ile razy guardrail G1 złapał w odpowiedzi cenę spoza
                        kalkulatora (licząc też próbę korekty — patrz
                        docstring `tura.uruchom`)."""
    from bots_pro import guardraile, stan, tura

    conv_id = conv_id_bazowy + rozmowa["id"]
    odpowiedzi = []
    trasa = []
    uzycia = []
    czasy_tur = []
    zdarzenia_handoff = []
    naruszenia_g1 = []
    wyslane_w_turze = []

    def _przechwyc_wyslanie(_conv_id, tekst, image_path=None, image_name=None,
                            image_mime="image/jpeg", token=None):
        wyslane_w_turze.append(tekst)
        return True

    def _przechwyc_handoff(powod):
        zdarzenia_handoff.append(powod)
        return {"ok": True, "powod": powod}

    def _wolno_zawsze(_conv_id):
        # Replay nie ma (i nie powinien mieć) prawdziwej rozmowy w Chatwoocie
        # do odpytania — bot ma w replayu ZAWSZE mówić, tak jak w świeżej
        # rozmowie w statusie 'pending', bez ludzkiego agenta w tle. To NIE
        # jest obchodzenie inwariantów I1/I2 (te żyją niezależnie od tej
        # bramki, w guardraile.py i potwierdzenia.py — nietknięte), tylko
        # usunięcie zależności od stanu zewnętrznego systemu, którego
        # replay z definicji nie posiada.
        return True

    oryginalny_runner = tura.Runner

    class _SzpiegRunnera:
        """Deleguje KAŻDE wywołanie do runnera, który faktycznie był
        podpięty pod `tura.Runner` w momencie wejścia do `odtworz()` —
        w produkcyjnym użyciu to prawdziwy `agents.Runner` (import na
        poziomie modułu w tura.py), w testach to, co test podstawił (patrz
        tests/test_replay_odtworz.py) — dzięki temu TEN SAM kod działa i na
        prawdziwym SDK (replay właściwy), i pod atrapą bez sieci/klucza API
        (testy). Po drodze zapisuje `last_agent`/`context_wrapper.usage` do
        metryk trasy/kosztu, których `tura.uruchom()` (funkcja bez wartości
        zwrotnej) nie ujawnia wywołującemu."""

        def run_sync(self, agent, tresc, session=None, max_turns=None):
            wynik = oryginalny_runner.run_sync(
                agent, tresc, session=session, max_turns=max_turns)
            nazwa_agenta = getattr(getattr(wynik, "last_agent", None), "name", None)
            if nazwa_agenta:
                trasa.append(nazwa_agenta)
            uzycie = getattr(getattr(wynik, "context_wrapper", None), "usage", None)
            if uzycie is not None:
                uzycia.append(uzycie)
            return wynik

    oryginalny_sprawdz_ceny = guardraile.sprawdz_ceny

    def _sprawdz_ceny_ze_zliczeniem(tekst, znane_kwoty):
        naruszenia = oryginalny_sprawdz_ceny(tekst, znane_kwoty)
        if naruszenia:
            naruszenia_g1.append(naruszenia)
        return naruszenia

    with contextlib.ExitStack() as podmiany:
        podmiany.enter_context(_podmien(tura, "cw_agent_reply", _przechwyc_wyslanie))
        podmiany.enter_context(_podmien(tura, "Runner", _SzpiegRunnera()))
        podmiany.enter_context(_podmien(stan, "handoff", _przechwyc_handoff))
        podmiany.enter_context(_podmien(stan, "wolno_prowadzic_rozmowe", _wolno_zawsze))
        podmiany.enter_context(_podmien(guardraile, "sprawdz_ceny", _sprawdz_ceny_ze_zliczeniem))

        stan.ustaw_kontekst(conv_id)
        for kto, tresc in rozmowa["wiadomosci"]:
            if kto != "KLIENT" or not tresc.strip():
                continue
            wyslane_w_turze.clear()
            poczatek = time.monotonic()
            tura.uruchom(conv_id, "replay", tresc, persona="pro")
            czasy_tur.append(time.monotonic() - poczatek)
            odpowiedzi.extend(wyslane_w_turze)

    return {
        "odpowiedzi": odpowiedzi,
        "handoff": bool(zdarzenia_handoff),
        "trasa": trasa,
        "uzycia": uzycia,
        "czasy_tur": czasy_tur,
        "kwoty_niezgodne": len(naruszenia_g1),
    }


def main(sciezki):
    """Runner CLI: odtwarza wszystkie rozmowy z podanych plików transkryptów,
    drukuje wynik KAŻDEJ i podsumowanie zbiorcze — do numerycznego porównania
    dwóch silników uruchom to polecenie DWA RAZY, z inną wartością MODEL_*
    (bots_pro/models.py) między przebiegami, i porównaj podsumowania."""
    from e2e import kryteria

    if not sciezki:
        print("Uzycie: python e2e/replay.py sciezka/do/shard_1.txt [shard_2.txt ...]")
        return

    # `quote_worker.py` (jedyny inny wolajacy tura.uruchom() w produkcji) robi
    # to raz, przy starcie procesu — replay.py jest OSOBNYM procesem/skryptem,
    # wiec musi to zrobic samo. Idempotentne (CREATE TABLE IF NOT EXISTS),
    # bezpieczne wolac przy kazdym uruchomieniu.
    from core.db import init_db
    from bots_pro.stan import init_pro
    init_db()
    init_pro()

    wyniki = []
    wszystkie_czasy_tur = []
    for sciezka in sciezki:
        for rozmowa in wczytaj_rozmowy(sciezka):
            wynik_odtworzenia = odtworz(rozmowa)
            wszystkie_czasy_tur.extend(wynik_odtworzenia["czasy_tur"])
            ocena = kryteria.ocen(
                rozmowa, wynik_odtworzenia["odpowiedzi"],
                handoff=wynik_odtworzenia["handoff"],
                kwoty_niezgodne=wynik_odtworzenia["kwoty_niezgodne"],
                trasa=wynik_odtworzenia["trasa"],
                uzycia=wynik_odtworzenia["uzycia"],
                czasy_tur=wynik_odtworzenia["czasy_tur"])
            wyniki.append(ocena)
            print("#%s tur=%s powtorki=%s wyjscie=%s handoff=%s kwoty_niezgodne=%s "
                  "trasa=%s koszt=%.2f"
                  % (ocena["id"], ocena["tur"], ocena["powtorki"], ocena["ma_wyjscie"],
                     ocena["handoff"], ocena["kwoty_niezgodne"],
                     "->".join(ocena["trasa"]) or "-", ocena["koszt"]))

    razem = len(wyniki)
    z_wyjsciem = sum(1 for w in wyniki if w["ma_wyjscie"])
    powtorki = sum(w["powtorki"] for w in wyniki)
    kwoty_niezgodne = sum(w["kwoty_niezgodne"] for w in wyniki)
    handoffy = sum(1 for w in wyniki if w["handoff"])
    koszt_calkowity = sum(w["koszt"] for w in wyniki)
    p95 = kryteria.p95_czas(wszystkie_czasy_tur)

    print("\n=== PODSUMOWANIE (%s rozmow) ===" % razem)
    print("z wyjsciem (handoff albo link): %s (%.0f%%)"
          % (z_wyjsciem, 100.0 * z_wyjsciem / razem if razem else 0))
    print("powtorzonych formulek lacznie: %s" % powtorki)
    print("kwot spoza kalkulatora (G1) lacznie: %s" % kwoty_niezgodne)
    print("handoffy na 100 rozmow: %.1f" % kryteria.handoffy_na_100(razem, handoffy))
    print("koszt calkowity (proxy tokenowe, patrz kryteria.CENNIK_DOMYSLNY): %.2f"
          % koszt_calkowity)
    print("p95 czasu tury: %s" % ("%.2fs" % p95 if p95 is not None else "brak danych"))
    print("trafnosc routingu: NIE liczona automatycznie — realne transkrypty audytu "
          "nie niosa etykiety 'ktory agent SDK POWINIEN odpowiedziec' (surowy tekst "
          "rozmowy, nie oznaczenie routingu). kryteria.trafnosc_routingu() jest gotowa "
          "do uzycia z kazdym zrodlem takich etykiet, gdy powstanie (patrz jej "
          "docstring i tests/test_replay_odtworz.py, gdzie liczona jest na "
          "syntetycznych danych ze znanym oczekiwanym routingiem).")


if __name__ == "__main__":
    # Uruchomione jako skrypt (`python e2e/replay.py ...`) — Python wtedy
    # wklada na sys.path WYLACZNIE katalog e2e/, nie jego rodzica, przez co
    # `from e2e import kryteria`/`from bots_pro import ...` (wolane wewnatrz
    # main()/odtworz()) by sie nie odnalazly. Dopisujemy katalog nadrzedny
    # (integrations/chat_bridge) — pod pytest ten sam efekt daje sam
    # rootdir, wiec ten fragment jest potrzebny WYLACZNIE do bezposredniego
    # `python e2e/replay.py`, nie do testow.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main(sys.argv[1:])
