# -*- coding: utf-8 -*-
"""
Testy silnika odtwarzania (`e2e.replay.odtworz`) — wymagaja zainstalowanego
`agents` SDK (Runner/Agent/Model), dlatego caly plik jest POMIJANY bez niego
(ten sam wzorzec co tests/test_pro_tura.py — importy sa na poziomie modulu).

NAJWAZNIEJSZY test w tym pliku to TestPrzechwycenieWysylki: harness NIE MOZE
pisac do prawdziwego Chatwoota. `bots_pro.tura` importuje `cw_agent_reply`
PRZEZ NAZWE (`from core.chatwoot import cw_agent_reply`) — podmiana atrybutu
na module `core.chatwoot` PO fakcie (naiwne podejscie, jakie sugerowal
pierwotny brief tego zadania) nie ma WIEC zadnego wplywu na to, co
`tura.uruchom()` faktycznie wywoluje, bo referencja jest juz zwiazana w
przestrzeni nazw `tura` w momencie importu modulu. Testy nizej dowodza, ze
`replay.odtworz` patchuje WLASCIWE miejsce.

`cw_agent_reply`/`cw_bot_handoff` (core/chatwoot.py) NIGDY nie rzucaja same z
siebie — lapia wyjatki i po cichu zwracaja False + log. Sama nieobecnosc
wyjatku przy PRAWDZIWYM wywolaniu nie bylaby wiec dowodem niczego (test by
"przeszedl" nawet gdyby cichutko poszedl w siec i dostal blad polaczenia).
Podmiana prawdziwej funkcji na atrape, ktora RZUCA, jest jedynym niezawodnym
sposobem sprawdzenia, ze do niej w ogole nie doszlo."""
import types

import pytest

pytest.importorskip("agents")  # patrz naglowek modulu

from bots_pro import stan, tura
from e2e import kryteria, replay

stan.init_pro()


class _FalszywyRunnerRoutingu:
    """Jak `_FalszywyRunner` w test_pro_tura.py, wzbogacony o
    `last_agent`/`context_wrapper.usage` — `replay._SzpiegRunnera` czyta oba
    te pola do metryk trasy/kosztu (patrz jego docstring w e2e/replay.py)."""

    def __init__(self, odpowiedzi, agenci_nazwy=None, uzycia=None):
        self._odpowiedzi = list(odpowiedzi)
        self._agenci_nazwy = list(agenci_nazwy or [])
        self._uzycia = list(uzycia or [])
        self.wywolania = []

    def run_sync(self, agent, tresc, session=None, max_turns=None):
        self.wywolania.append(tresc)
        nazwa = self._agenci_nazwy.pop(0) if self._agenci_nazwy else None
        uzycie = self._uzycia.pop(0) if self._uzycia else None
        return types.SimpleNamespace(
            final_output=self._odpowiedzi.pop(0),
            last_agent=types.SimpleNamespace(name=nazwa) if nazwa else None,
            context_wrapper=types.SimpleNamespace(usage=uzycie))


class TestPrzechwycenieWysylki:
    """Krytyczny wymog zadania: harness nie moze pisac do produkcji."""

    def test_prawdziwy_cw_agent_reply_nigdy_nie_jest_wolany(self, monkeypatch):
        import core.chatwoot as cw

        def _wybuchnij(*a, **kw):
            raise AssertionError(
                "replay wywolal PRAWDZIWY core.chatwoot.cw_agent_reply — "
                "to byloby pisanie do produkcyjnego Chatwoota")

        monkeypatch.setattr(cw, "cw_agent_reply", _wybuchnij)
        monkeypatch.setattr(
            tura, "Runner",
            _FalszywyRunnerRoutingu(["Dziekuje, potrzebuje jeszcze wymiarow."]))

        rozmowa = {"id": 501, "wiadomosci": [("KLIENT", "poprosze wycene blatu")]}
        wynik = replay.odtworz(rozmowa)

        # Brak wyjatku (patrz _wybuchnij) DOWODZI, ze prawdziwa funkcja
        # sieciowa nie zostala wywolana — a odpowiedz mimo to zostala
        # poprawnie przechwycona przez wlasciwa podmiane (tura.cw_agent_reply).
        assert wynik["odpowiedzi"] == ["Dziekuje, potrzebuje jeszcze wymiarow."]

    def test_prawdziwy_cw_bot_handoff_nigdy_nie_jest_wolany(self, monkeypatch):
        import core.chatwoot as cw

        def _wybuchnij(*a, **kw):
            raise AssertionError(
                "replay wywolal PRAWDZIWY cw_bot_handoff — to byloby "
                "pisanie do produkcyjnego Chatwoota")

        monkeypatch.setattr(cw, "cw_bot_handoff", _wybuchnij)
        monkeypatch.setattr(
            tura, "Runner",
            _FalszywyRunnerRoutingu(["Cena wynosi 999,00 zl.", "Nadal 999,00 zl."]))

        rozmowa = {"id": 502, "wiadomosci": [("KLIENT", "ile kosztuje blat?")]}
        wynik = replay.odtworz(rozmowa)

        assert wynik["odpowiedzi"] == []   # zla cena NIGDY nie "dotarla do klienta"
        assert wynik["handoff"] is True     # ale fakt handoffu jest zarejestrowany

    def test_prawdziwy_chatwoot_nie_jest_odpytywany_o_status_ani_historie(self, monkeypatch):
        import core.chatwoot as cw

        def _wybuchnij(*a, **kw):
            raise AssertionError(
                "replay odpytal PRAWDZIWEGO Chatwoota o status/historie rozmowy "
                "(bramka ciszy po handoffie)")

        monkeypatch.setattr(cw, "cw_conv_status", _wybuchnij)
        monkeypatch.setattr(cw, "cw", _wybuchnij)
        monkeypatch.setattr(tura, "Runner", _FalszywyRunnerRoutingu(["ok"]))

        rozmowa = {"id": 503, "wiadomosci": [("KLIENT", "dzien dobry")]}
        replay.odtworz(rozmowa)  # brak wyjatku == bramka nie posiegnela po siec


class TestOdtworzZbieraMetryki:
    def test_trasa_zbiera_nazwe_agenta_ktory_odpowiedzial(self, monkeypatch):
        monkeypatch.setattr(
            tura, "Runner", _FalszywyRunnerRoutingu(["odp"], agenci_nazwy=["Wycena"]))
        rozmowa = {"id": 601, "wiadomosci": [("KLIENT", "cokolwiek")]}

        wynik = replay.odtworz(rozmowa)

        assert wynik["trasa"] == ["Wycena"]

    def test_uzycia_pozwalaja_policzyc_koszt_rozmowy(self, monkeypatch):
        uzycie = types.SimpleNamespace(input_tokens=100, output_tokens=20)
        monkeypatch.setattr(
            tura, "Runner",
            _FalszywyRunnerRoutingu(["odp"], agenci_nazwy=["Wycena"], uzycia=[uzycie]))
        rozmowa = {"id": 602, "wiadomosci": [("KLIENT", "cokolwiek")]}

        wynik = replay.odtworz(rozmowa)

        assert kryteria.koszt_rozmowy(wynik["uzycia"]) == 120.0

    def test_czas_tury_jest_mierzony_dla_kazdej_wiadomosci_klienta(self, monkeypatch):
        monkeypatch.setattr(tura, "Runner", _FalszywyRunnerRoutingu(["a", "b"]))
        rozmowa = {"id": 603,
                   "wiadomosci": [("KLIENT", "pierwsza"), ("KLIENT", "druga")]}

        wynik = replay.odtworz(rozmowa)

        assert len(wynik["czasy_tur"]) == 2
        assert all(t >= 0 for t in wynik["czasy_tur"])

    def test_niesklient_linie_sa_pomijane_w_odtwarzaniu(self, monkeypatch):
        fake = _FalszywyRunnerRoutingu(["jedyna odpowiedz"])
        monkeypatch.setattr(tura, "Runner", fake)
        rozmowa = {"id": 604, "wiadomosci": [
            ("BOT", "stara odpowiedz starego bota — MA byc zignorowana"),
            ("KLIENT", "jedyna wiadomosc klienta"),
            ("AGENT", "czlowiek dopisal cos pozniej — tez ignorowane"),
            ("NOTATKA-PRYW", "notatka wewnetrzna — ignorowana"),
            ("SYSTEM", "zdarzenie systemowe — ignorowane"),
        ]}

        wynik = replay.odtworz(rozmowa)

        assert fake.wywolania == ["jedyna wiadomosc klienta"]
        assert wynik["odpowiedzi"] == ["jedyna odpowiedz"]

    def test_kwoty_niezgodne_liczy_naruszenia_guardraila_g1(self, monkeypatch):
        # Dwie proby z ta sama zla cena -> DWA naruszenia zliczone (pierwsza
        # proba i proba korekty), zanim tura odda rozmowe konsultantowi.
        monkeypatch.setattr(
            tura, "Runner",
            _FalszywyRunnerRoutingu(["Cena wynosi 999,00 zl.", "Nadal 999,00 zl."]))
        rozmowa = {"id": 605, "wiadomosci": [("KLIENT", "ile kosztuje blat?")]}

        wynik = replay.odtworz(rozmowa)

        assert wynik["kwoty_niezgodne"] == 2

    def test_brak_naruszen_gdy_cena_pochodzi_z_rejestru_kalkulatora(self, monkeypatch):
        # Kontrola negatywna: PRAWDZIWA cena (zarejestrowana przez
        # zapamietaj_kwoty, jak robi to prawdziwe narzedzie policz_wycene)
        # NIE MA zostac policzona jako naruszenie — G1 ma zostac naprawde
        # zmierzony, nie sztucznie wyzerowany.
        def _run_sync(agent, tresc, session=None, max_turns=None):
            stan.zapamietaj_kwoty([999.0])
            return types.SimpleNamespace(
                final_output="Cena wynosi 999,00 zl.",
                last_agent=types.SimpleNamespace(name="Wycena"),
                context_wrapper=types.SimpleNamespace(usage=None))

        monkeypatch.setattr(tura, "Runner", types.SimpleNamespace(run_sync=_run_sync))
        rozmowa = {"id": 606, "wiadomosci": [("KLIENT", "ile kosztuje blat?")]}

        wynik = replay.odtworz(rozmowa)

        assert wynik["kwoty_niezgodne"] == 0
        assert wynik["odpowiedzi"] == ["Cena wynosi 999,00 zl."]

    def test_dwie_rozmowy_pod_rzad_nie_dzieda_stanu(self, monkeypatch):
        # Rozne conv_id (bazowe + rozmowa['id']) — druga rozmowa nie ma
        # widziec kwot/pozycji zarejestrowanych w pierwszej.
        def _run_sync_pierwsza(agent, tresc, session=None, max_turns=None):
            stan.zapamietaj_kwoty([999.0])
            return types.SimpleNamespace(
                final_output="Cena wynosi 999,00 zl.",
                last_agent=types.SimpleNamespace(name="Wycena"),
                context_wrapper=types.SimpleNamespace(usage=None))

        monkeypatch.setattr(tura, "Runner", types.SimpleNamespace(run_sync=_run_sync_pierwsza))
        pierwsza = replay.odtworz({"id": 607, "wiadomosci": [("KLIENT", "ile kosztuje?")]})
        assert pierwsza["kwoty_niezgodne"] == 0

        # Nowe conv_id (900608) nie ma zarejestrowanej kwoty 999.00 z
        # poprzedniej rozmowy (900607) — ta sama cena tutaj JEST naruszeniem,
        # wiec G1 zada korekty (druga proba, tez zla -> DWA naruszenia).
        monkeypatch.setattr(
            tura, "Runner",
            _FalszywyRunnerRoutingu(["Cena wynosi 999,00 zl.", "Nadal 999,00 zl."]))
        druga = replay.odtworz({"id": 608, "wiadomosci": [("KLIENT", "ile kosztuje?")]})
        assert druga["kwoty_niezgodne"] == 2


class TestOdtworzTrasaZPrawdziwymRouterem:
    """Trasa musi odzwierciedlac PRAWDZIWY routing SDK (Router -> agent
    wyspecjalizowany), nie tylko to, co atrapa Runnera deklaruje sama o
    sobie — ten test podmienia WYLACZNIE model (jak
    TestScenariuszMaterialPotemCena w test_pro_tura.py), zeby prawdziwy
    Router i prawdziwy Runner.run_sync z SDK naprawde wykonaly handoff."""

    def test_pytanie_o_cene_trafia_do_wyceny_i_trasa_to_odzwierciedla(self, monkeypatch):
        from agents.items import ModelResponse
        from agents.models.interface import Model
        from agents.usage import Usage
        from openai.types.responses import (
            ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText,
        )

        from bots_pro import agenci

        def _wiadomosc_tekstowa(tekst, ident, usage):
            return ModelResponse(
                output=[ResponseOutputMessage(
                    id="msg_%s" % ident, status="completed", role="assistant",
                    type="message",
                    content=[ResponseOutputText(type="output_text", text=tekst,
                                                annotations=[])])],
                usage=usage, response_id=None)

        def _wywolanie_transferu(nazwa_agenta, ident, usage):
            nazwa_narzedzia = "transfer_to_%s" % nazwa_agenta.lower()
            return ModelResponse(
                output=[ResponseFunctionToolCall(
                    type="function_call", call_id="call_%s" % ident,
                    name=nazwa_narzedzia, arguments="{}", id="fc_%s" % ident)],
                usage=usage, response_id=None)

        class _ModelRouterDoWyceny(Model):
            def __init__(self):
                self.licznik = 0

            async def get_response(self, system_instructions, input, model_settings,
                                    tools, output_schema, handoffs, tracing, *,
                                    previous_response_id, conversation_id, prompt):
                self.licznik += 1
                if len(tools) == 0:   # Router — brak narzedzi
                    return _wywolanie_transferu("Wycena", self.licznik, Usage(
                        input_tokens=8, output_tokens=2, total_tokens=10))
                return _wiadomosc_tekstowa(
                    "Aby przygotowac wycene, potrzebuje material, wymiary i ilosc sztuk.",
                    self.licznik, Usage(input_tokens=10, output_tokens=5, total_tokens=15))

            def stream_response(self, *args, **kwargs):
                raise NotImplementedError

        monkeypatch.setattr(agenci, "model_dla_roli", lambda rola: _ModelRouterDoWyceny())

        rozmowa = {"id": 701,
                   "wiadomosci": [("KLIENT", "ile bedzie kosztowac blat 200x60x4?")]}
        wynik = replay.odtworz(rozmowa)

        assert wynik["trasa"] == ["Wycena"]
        assert wynik["odpowiedzi"] == [
            "Aby przygotowac wycene, potrzebuje material, wymiary i ilosc sztuk."]
        # Dwa wywolania modelu (Router + Wycena) -> dwa wpisy Usage, koszt
        # to suma obu (patrz kryteria.koszt_rozmowy).
        assert kryteria.koszt_rozmowy(wynik["uzycia"]) == 25.0
