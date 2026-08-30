# -*- coding: utf-8 -*-
"""
Jedna tura Dębusia Pro: pętla agentów -> guardrail -> wysyłka.

Rozstrzygnięcie ślepej uliczki między agentami (Task 6): agenci wyspecjalizowani
(Wycena/Wiedza/Posprzedaz, bots_pro/agenci.py) NIE MAJĄ własnych handoffs — tylko
Router ma handoffs=[Wycena, Wiedza, Posprzedaz]. Bez dodatkowego mechanizmu rozmowa,
która trafiła np. do agenta Wiedzy, nie miałaby jak dotrzeć do agenta Wyceny w TEJ
SAMEJ turze.

Rozwiązanie: KAŻDA tura wchodzi przez Router OD NOWA (`zbuduj_router()` wołane tu, przy
każdym `uruchom()`), a historia rozmowy (w tym to, który agent i co odpowiedział
poprzednio) leci przez `SQLiteSession`. Scenariusz „najpierw pytam o materiał (Wiedza),
potem chcę cenę (Wycena)" działa więc MIĘDZY turami: turn 1 -> Router -> Wiedza,
turn 2 -> Router (świeży, ale widzi historię z sesji) -> Wycena. Koszt: jedno
dodatkowe wywołanie routera na turę, w zamian za prostotę (bez N*(N-1) ręcznie
utrzymywanych handoffów między agentami wyspecjalizowanymi) i bez ryzyka, że agent
wyceny zacznie odpowiadać na pytania o wiedzę (i odwrotnie) tylko dlatego, że ma do
niego handoff pod ręką. Patrz test_pro_tura.py::TestScenariuszMaterialPotemCena.

Guardrail wyjściowy G1 (integralność ceny, bots_pro/guardraile.py) jest WYJŚCIOWY
celowo — łapie odpowiedź niezależnie od tego, KTÓRY agent ją wyprodukował (przy
handoffach guardraile WEJŚCIOWE Agents SDK działają tylko na pierwszym agencie,
nie na tym, do którego nastąpiło przekazanie — G1 musiałby więc być podpięty do
każdego agenta z osobna i tak i tak by nie widział wyniku PO handoffie w tej samej
turze). Sprawdzamy więc `wynik.final_output` PO całym Runner.run_sync, raz.

Guardrail NIE jest dublowany: bramki narzędzi (potwierdzenie klienta I2, integralność
ceny przy zapisie) mieszkają w bots_pro.potwierdzenia/.narzedzia — ten moduł dokłada
wyłącznie kontrolę WYJŚCIOWĄ (I1), której z definicji nie da się umieścić w narzędziu
(narzędzie nie widzi ostatecznego tekstu odpowiedzi modelu).

`podsumowanie.wyslij()` (wołane przez narzędzie `wyslij_podsumowanie`) SAM wysyła do
klienta i w tej turze zwraca modelowi wskazówkę, żeby zostawić `final_output` puste —
stąd wczesne wyjście `if not odpowiedz: return` niżej: bez niego wysłalibyśmy pustą
wiadomość, a gdyby model jednak coś dopisał, NIE moglibyśmy tego odróżnić od zwykłej
odpowiedzi — i tak nie ma potrzeby specjalnej obsługi, bo pusty final_output i tak
nic by nie wysłał.
"""
from agents import Runner
from agents import SQLiteSession

from config import BOT_PRO_CW_AGENT_TOKEN, BOT_PRO_MAX_TURNS, DB_PATH
from bots_pro import guardraile, stan, wysylka
from bots_pro.agenci import zbuduj_router
from core.chatwoot import cw_agent_reply
from core.log import log

_KOMUNIKAT_KOREKTY = (
    "Podałeś kwotę, której nie ma w wyniku kalkulatora. Napisz odpowiedź jeszcze raz, "
    "używając wyłącznie kwot zwróconych przez narzędzie policz_wycene albo policz_wysylke."
)


def _sesja(conv_id):
    """SQLiteSession z rdzenia `agents`, NIE SQLAlchemySession — ta ostatnia importuje
    `Select` z sqlalchemy, co istnieje dopiero w 2.0, a projekt ma twarde ograniczenie
    `<2.0` (requirements.txt). SQLiteSession pisze do tego samego pliku co reszta
    mostka (DB_PATH), więc nie dokłada żadnej nowej zależności/pliku."""
    return SQLiteSession(str(conv_id), DB_PATH)


def uruchom(conv_id, inbox_id, tresc, zalaczniki=None, persona="pro"):
    """Przeprowadza jedną turę i wysyła odpowiedź do klienta.

    `persona` MUSI trafić do `stan.ustaw_kontekst` (nie tylko zostać lokalnym
    parametrem) — `podsumowanie.wyslij()`, wołane jako narzędzie WEWNĄTRZ tej tury,
    czyta profil kanału przez `stan.persona()`, nie przez argument. Bez tego
    podsumowanie na Allegro wysyłałoby się z domyślnym profilem 'pro' (markdown,
    emoji, linki) zamiast z ALLEGRO_CAPS — dokładnie ten wyciek, przed którym
    ma chronić `wysylka.py` (link do wyceny w treści zabronionej regulaminem
    marketplace'u)."""
    stan.ustaw_kontekst(conv_id, persona_tury=persona)
    stan.init_pro()

    wynik = Runner.run_sync(
        zbuduj_router(), tresc, session=_sesja(conv_id), max_turns=BOT_PRO_MAX_TURNS)
    odpowiedz = (wynik.final_output or "").strip()
    if not odpowiedz:
        return

    # Guardrail G1: kwota spoza kalkulatora nie opuszcza procesu (inwariant I1).
    naruszenia = guardraile.sprawdz_ceny(odpowiedz, stan.znane_kwoty())
    if naruszenia:
        log("guardrail G1: kwoty spoza kalkulatora %s (conv %s)" % (naruszenia, conv_id))
        wynik = Runner.run_sync(zbuduj_router(), _KOMUNIKAT_KOREKTY,
                                session=_sesja(conv_id), max_turns=BOT_PRO_MAX_TURNS)
        odpowiedz = (wynik.final_output or "").strip()
        if guardraile.sprawdz_ceny(odpowiedz, stan.znane_kwoty()):
            log("guardrail G1: druga proba tez z naruszeniem -> handoff (conv %s)" % conv_id)
            stan.handoff("guardrail ceny — dwie próby z kwotą spoza kalkulatora")
            return

    for czesc in wysylka.przygotuj(odpowiedz, persona):
        if czesc:
            cw_agent_reply(conv_id, czesc, token=BOT_PRO_CW_AGENT_TOKEN)
