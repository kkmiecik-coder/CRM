# -*- coding: utf-8 -*-
"""
Przebieg tury: pętla agentów -> guardrail -> wysyłka.

`bots_pro.tura` importuje `agents` na poziomie modułu (Runner, SQLiteSession) —
bez zainstalowanego SDK cały ten plik ma zostać POMINIĘTY (ten sam wzorzec, co
w test_pro_agenci.py / test_pro_narzedzia.py).

Rozstrzygnięcie 1 (Task 6): agenci wyspecjalizowani NIE MAJĄ własnych handoffs
(patrz agenci.py) — jedyną drogą z powrotem do Wyceny po tym, jak rozmowa trafiła
do Wiedzy, jest wejście przez Router OD NOWA w kolejnej turze. TestScenariuszMaterialPotemCena
dowodzi, że to naprawdę działa: prawdziwy Router + prawdziwe agenty + prawdziwy
Runner z Agents SDK, wyłącznie model podmieniony na sterowalną atrapę (żeby test
nie zależał od sieci/klucza API) — NIE atrapa całego Runner.run_sync.
"""
import json
import types

import pytest

pytest.importorskip("agents")  # patrz docstring modulu

from agents.items import ModelResponse
from agents.models.interface import Model
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText,
)

import config as config_mod
from bots_pro import agenci, notatki, stan, tura
from bots_pro.narzedzia import NARZEDZIA_WYCENY

stan.init_pro()

# Atrapy modelu nizej rozpoznaja, KTORY agent je wolal, po LICZBIE NARZEDZI
# (Router 0, Wiedza 2, Wycena — komplet). Liczba dla Wyceny brana z prawdziwego
# zestawu, a nie wpisana na sztywno (runda napraw 4): dopisanie narzedzia — jak
# `wyslij_obraz` w P2 — przestawialo ja i te testy oblewaly z powodu zupelnie
# niezwiazanego z tym, czego dowodza (routing i handoffy).
_NARZEDZI_WYCENY = len(NARZEDZIA_WYCENY)


@pytest.fixture(autouse=True)
def _domyslnie_wolno_prowadzic_rozmowe(monkeypatch):
    """Wiekszosc testow w tym pliku sprawdza logike SAMEJ tury (guardrail, wysylka,
    routing) — nie bramki ciszy po handoffie (patrz TestBramkaCiszyPoHandoffie nizej),
    ktora normalnie odpytuje Chatwoota siecia. Domyslnie pozwalamy botowi mowic (tak
    jak w prawdziwej nowej rozmowie w statusie pending), zeby zaden z pozostalych
    testow nie musial tego osobno mockowac. Testy bramki nadpisuja to jawnie."""
    monkeypatch.setattr(stan, "wolno_prowadzic_rozmowe", lambda conv_id: True)


@pytest.fixture(autouse=True)
def _kontakt_klienta_bez_sieci(monkeypatch):
    """N6: `tura.uruchom` wczytuje teraz kontakt rozmowy z Chatwoota na starcie
    tury. Domyslnie oddajemy pustke, zeby testy SAMEJ tury nie chodzily po
    siec (ten sam powod, co przy `wolno_prowadzic_rozmowe` wyzej). Testy N6
    nadpisuja to jawnie."""
    import core.chatwoot as core_cw
    monkeypatch.setattr(core_cw, "cw_contact_full", lambda conv_id: {
        "name": "", "identifier": "", "email": "", "phone": ""})


# ---------------------------------------------------------------------------
# Atrapa CAŁEGO Runner.run_sync — dla testów logiki tury (retry guardraila,
# brak podwójnej wysyłki), gdzie nie zależy nam na prawdziwym routingu SDK.
# ---------------------------------------------------------------------------
class _FalszywyRunner:
    """Podmienia `agents.Runner` widziany przez `bots_pro.tura` — kolejne wywołania
    `run_sync` zwracają kolejne zaplanowane odpowiedzi, po kolei.

    `rejestruj_kwoty` (opcjonalnie, lista list, po jednej na wywołanie) symuluje
    efekt uboczny narzędzia `policz_wycene` (`stan.zapamietaj_kwoty`) - w prawdziwym
    przebiegu kwoty trafiają do rejestru W TRAKCIE Runner.run_sync. Rejestr żyje w
    `pro_stan`, trwale per ROZMOWA (Task 8, B1 — `stan.ustaw_kontekst` go już NIE
    zeruje), więc kwota zarejestrowana w jednym wywołaniu `run_sync` widoczna jest
    też we WSZYSTKICH kolejnych — także w kolejnej turze tej samej rozmowy (patrz
    TestGuardrailBlokujeWysylke::test_kwota_zarejestrowana_w_turze_1_nie_jest_blokowana_w_turze_2)."""

    def __init__(self, odpowiedzi, rejestruj_kwoty=None):
        self._odpowiedzi = list(odpowiedzi)
        self._rejestruj_kwoty = list(rejestruj_kwoty or [])
        self.wywolania = []   # tresc kazdego wywolania, w kolejnosci
        self.agenci = []      # agent (router) przekazany do kazdego wywolania

    def run_sync(self, agent, tresc, session=None, max_turns=None):
        self.wywolania.append(tresc)
        self.agenci.append(agent)
        if self._rejestruj_kwoty:
            kwoty = self._rejestruj_kwoty.pop(0)
            if kwoty:
                stan.zapamietaj_kwoty(kwoty)
        return types.SimpleNamespace(final_output=self._odpowiedzi.pop(0))


def _wyslane_przechwytywacz(monkeypatch):
    wyslane = []
    monkeypatch.setattr(tura, "cw_agent_reply",
                         lambda conv_id, tekst, token=None: wyslane.append(tekst))
    return wyslane


class TestBramkaCiszyPoHandoffie:
    """Task 7: bot NIE MOZE odezwac sie w rozmowie, ktora `stan.wolno_prowadzic_rozmowe`
    uznaje za zajeta przez czlowieka - ani slowem, ani wywolaniem Routera/LLM."""

    def test_gdy_bramka_zabrania_runner_nie_jest_wolany(self, monkeypatch):
        conv_id = 96201001
        monkeypatch.setattr(stan, "wolno_prowadzic_rozmowe", lambda cid: False)
        fake_runner = _FalszywyRunner(["cokolwiek"])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "wiadomosc klienta", persona="quote")

        assert fake_runner.wywolania == []   # zero wywolan LLM
        assert wyslane == []                 # zero wyslanych wiadomosci

    def test_bramka_dostaje_wlasciwy_conv_id(self, monkeypatch):
        conv_id = 96201002
        przekazane = []
        monkeypatch.setattr(stan, "wolno_prowadzic_rozmowe",
                            lambda cid: przekazane.append(cid) or False)
        monkeypatch.setattr(tura, "Runner", _FalszywyRunner(["x"]))
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "wiadomosc klienta", persona="quote")

        assert przekazane == [conv_id]

    def test_gdy_bramka_pozwala_tura_przebiega_normalnie(self, monkeypatch):
        # Kontrola negatywna: bramka nie ma blokowac normalnego przebiegu, kiedy
        # zwraca True (domyslne zachowanie fixture'a autouse w tym pliku - tu jawnie,
        # dla czytelnosci testu).
        conv_id = 96201003
        monkeypatch.setattr(stan, "wolno_prowadzic_rozmowe", lambda cid: True)
        fake_runner = _FalszywyRunner(["Dziekuje za wiadomosc."])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "wiadomosc klienta", persona="quote")

        assert wyslane == ["Dziekuje za wiadomosc."]
        assert len(fake_runner.wywolania) == 1


class TestSesjaOgraniczaHistorie:
    """Task 8, B5: SQLiteSession bez konfiguracji podaje modelowi CALA historie
    sesji, a Router placi ja drugi raz co ture — koszt i opoznienie (nie
    poprawnosc), rosnace liniowo z dlugoscia rozmowy. SDK (openai-agents==0.22.0)
    wspiera `SessionSettings(limit=...)` ograniczajace okno zwracane przez
    `get_items()` (a wiec i to, co Runner wysyla modelowi) — patrz docstring
    `_sesja` w tura.py."""

    def test_sesja_ma_ustawiony_limit_historii(self):
        sesja = tura._sesja(96301)
        assert sesja.session_settings.limit == config_mod.BOT_PRO_SESSION_ITEMS_LIMIT

    def test_okno_przeciete_w_srodku_pary_narzedzia_nie_wysyla_osieroconego_wpisu(self):
        # K2 (runda poprawek 1, code review): zarzut, ze SessionSettings(limit=...) tnie
        # okno historii W SRODKU pary narzedzia (function_call bez function_call_output,
        # LUB odwrotnie) - SDK mial usuwac WYLACZNIE osierocone function_call
        # (drop_orphan_function_calls), NIGDY osierocone function_call_output, wiec takie
        # wejscie mialoby byc odrzucane przez Responses API (400).
        #
        # SPRAWDZONE reprodukcja NA PRAWDZIWYM Runner.run_sync (nie golym
        # session.get_items() w izolacji - TO faktycznie zwraca osierocony wpis, bo samo
        # nie sprząta par) z realna SQLiteSession o malym limicie i historia specjalnie
        # przecieta W SRODKU pary narzedzia. Wynik: model dostaje CZYSTE wejscie. Powod
        # (patrz tez komentarz przy BOT_PRO_SESSION_ITEMS_LIMIT w config.py):
        # `prepare_input_with_session` (wolane przez Runner.run_sync, NIE golie
        # session.get_items()) ustawia `output_pruning_indexes` WLASNIE wtedy, gdy
        # SessionSettings.limit jest ustawiony - `drop_orphan_function_calls` z tym
        # argumentem czysci OBIE strony pary, nie tylko osierocone wywolania.
        import asyncio

        from agents import Agent, SessionSettings, SQLiteSession
        from agents import Runner as PrawdziwyRunner

        class _ModelPrzechwytujacyWejscie(Model):
            def __init__(self):
                self.ostatnie_wejscie = None

            async def get_response(self, system_instructions, input, model_settings, tools,
                                    output_schema, handoffs, tracing, *, previous_response_id,
                                    conversation_id, prompt):
                self.ostatnie_wejscie = input
                return _wiadomosc_tekstowa("ok", 0)

            def stream_response(self, *a, **k):
                raise NotImplementedError

        model = _ModelPrzechwytujacyWejscie()
        agent = Agent(name="Test", instructions="test", model=model, tools=[])
        sesja = SQLiteSession("k2-repro", ":memory:", session_settings=SessionSettings(limit=2))
        # Historia: para narzedzia (wywolanie+wynik), potem wiadomosc asystenta - limit=2
        # bierze OSTATNIE 2 itemy = [function_call_output, assistant]. Wywolanie WYPADA z
        # okna, wynik zostalby OSIEROCONY, gdyby SDK go nie posprzatal.
        asyncio.run(sesja.add_items([
            {"role": "user", "content": "pytanie 1"},
            {"type": "function_call", "call_id": "c1", "name": "narzedzie", "arguments": "{}",
             "id": "fc_1"},
            {"type": "function_call_output", "call_id": "c1", "output": "{}"},
            {"role": "assistant", "content": "odpowiedz 1"},
        ]))

        wynik = PrawdziwyRunner.run_sync(agent, "pytanie 2", session=sesja, max_turns=5)

        assert wynik.final_output == "ok"
        typy = [it.get("type") for it in model.ostatnie_wejscie if isinstance(it, dict)]
        assert "function_call_output" not in typy, (
            "wejscie do modelu niesie osierocony function_call_output bez pary "
            "function_call: %r" % model.ostatnie_wejscie)


class TestGuardrailZobowiazanBlokujeWysylke:
    """G3 (N9): zakazane zobowiazanie NIE dostaje rundy korekty — jedynym
    wyjsciem jest czlowiek. Do tej rundy guardrail wyjsciowy pilnowal
    WYLACZNIE kwot; "gwarantujemy", "wytrzyma", "mamy atest" wychodzily do
    klienta bez zadnej kontroli."""

    def test_obietnica_nie_trafia_do_klienta_i_konczy_sie_handoffem(self, monkeypatch):
        conv_id = 96131
        fake_runner = _FalszywyRunner(["Ten blat wytrzyma 200 kg, gwarantujemy."])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        powody = []
        monkeypatch.setattr(stan, "handoff", lambda powod: powody.append(powod) or {"ok": True})

        tura.uruchom(conv_id, "inbox1", "Czy blat wytrzyma zlew?", persona="quote")

        assert wyslane == [tura.KOMUNIKAT_HANDOFF]
        assert len(powody) == 1
        assert "zobowi" in powody[0].lower()

    def test_nie_ma_rundy_korekty(self, monkeypatch):
        # Roznica wobec G1: tam druga proba ma sens (kwota moze byc poprawiona
        # na prawdziwa). Tu "napisz to jeszcze raz bez obietnicy" dalby te sama
        # tresc innymi slowami — a pytanie i tak nalezy do czlowieka.
        conv_id = 96132
        fake_runner = _FalszywyRunner(["Gwarantujemy trwalosc.", "druga proba"])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        _wyslane_przechwytywacz(monkeypatch)
        monkeypatch.setattr(stan, "handoff", lambda powod: {"ok": True})

        tura.uruchom(conv_id, "inbox1", "Czy daje Pan gwarancje?", persona="quote")

        assert len(fake_runner.wywolania) == 1

    def test_powod_handoffu_mowi_KTORY_zwrot(self, monkeypatch):
        conv_id = 96133
        monkeypatch.setattr(tura, "Runner", _FalszywyRunner(["Mamy atest higieniczny."]))
        _wyslane_przechwytywacz(monkeypatch)
        powody = []
        monkeypatch.setattr(stan, "handoff", lambda powod: powody.append(powod) or {"ok": True})

        tura.uruchom(conv_id, "inbox1", "Macie atesty?", persona="quote")

        assert "atest" in powody[0]

    def test_odpowiedz_poprawiona_po_G1_tez_przechodzi_przez_G3(self, monkeypatch):
        # Korekta cenowa produkuje NOWY tekst. Gdyby G3 patrzyl wylacznie na
        # pierwsza wersje, obietnica dopisana w drugiej wychodzilaby do klienta
        # przez te sama dziure, ktora G3 mial zamknac.
        conv_id = 96134
        fake_runner = _FalszywyRunner([
            "Cena wynosi 999,00 zł.",                    # 1. proba — kwota spoza rejestru
            "Nie mam ceny, ale blat wytrzyma zlew.",     # 2. proba — cena OK, obietnica NIE
        ])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        powody = []
        monkeypatch.setattr(stan, "handoff", lambda powod: powody.append(powod) or {"ok": True})

        tura.uruchom(conv_id, "inbox1", "Ile kosztuje i czy wytrzyma?", persona="quote")

        assert wyslane == [tura.KOMUNIKAT_HANDOFF]
        assert "zobowi" in powody[0].lower()

    def test_zwykla_odpowiedz_przechodzi_bez_zmian(self, monkeypatch):
        # Kontrola negatywna: G3 nie ma dotykac normalnej rozmowy.
        conv_id = 96135
        monkeypatch.setattr(tura, "Runner",
                            _FalszywyRunner(["Jaka grubość Pana interesuje?"]))
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        monkeypatch.setattr(stan, "handoff",
                            lambda powod: pytest.fail("nie powinno dojsc do handoffu"))

        tura.uruchom(conv_id, "inbox1", "Dzien dobry", persona="quote")

        assert wyslane == ["Jaka grubość Pana interesuje?"]


class TestGuardrailBlokujeWysylke:
    """Guardrail G1 ma NAPRAWDĘ zatrzymać wysyłkę (nie tylko zalogować)."""

    def test_dwie_nieudane_proby_konczy_sie_handoffem_bez_wysylki(self, monkeypatch):
        conv_id = 96101
        fake_runner = _FalszywyRunner([
            "Cena wynosi 999,00 zł.",           # 1. proba - kwota spoza rejestru
            "Nadal potwierdzam: 999,00 zł.",    # 2. proba (po korekcie) - tak samo zla
        ])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        powody = []
        monkeypatch.setattr(stan, "handoff", lambda powod: powody.append(powod) or {"ok": True})

        tura.uruchom(conv_id, "inbox1", "Ile kosztuje blat?", persona="quote")

        # Zadna wersja bledej ceny NIE trafila do klienta — poszedl WYLACZNIE
        # komunikat o przekazaniu rozmowy (U7: wyjscie handoffowe nie jest ciche).
        assert wyslane == [tura.KOMUNIKAT_HANDOFF]
        # Doszlo do oddania rozmowy czlowiekowi - dokladnie raz.
        assert len(powody) == 1
        assert "guardrail" in powody[0].lower()
        # Byly dokladnie dwie proby (pierwsza + jedna korekta), bez trzeciej.
        assert len(fake_runner.wywolania) == 2

    def test_poprawiona_odpowiedz_w_drugiej_probie_zostaje_wyslana(self, monkeypatch):
        conv_id = 96102
        fake_runner = _FalszywyRunner([
            "Cena wynosi 999,00 zł.",                    # 1. proba - zla
            "Przepraszam, nie mam jeszcze gotowej ceny.",  # 2. proba - bez kwoty, OK
        ])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        monkeypatch.setattr(stan, "handoff",
                             lambda powod: pytest.fail("nie powinno dojsc do handoffu"))

        tura.uruchom(conv_id, "inbox1", "Ile kosztuje blat?", persona="quote")

        assert wyslane == ["Przepraszam, nie mam jeszcze gotowej ceny."]

    def test_kwota_z_rejestru_kalkulatora_przechodzi_za_pierwszym_razem(self, monkeypatch):
        # Kontrola negatywna: guardrail nie ma blokowac PRAWDZIWEJ ceny. Rejestracja
        # kwoty [999.0] symuluje to, co w prawdziwym przebiegu robi narzedzie
        # policz_wycene WEWNATRZ Runner.run_sync (patrz docstring _FalszywyRunner).
        conv_id = 96103
        fake_runner = _FalszywyRunner(["Cena wynosi 999,00 zł."], rejestruj_kwoty=[[999.0]])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "Ile kosztuje blat?", persona="quote")

        assert wyslane == ["Cena wynosi 999,00 zł."]
        assert len(fake_runner.wywolania) == 1   # bez korekty - nie bylo naruszenia

    def test_kwota_zarejestrowana_w_turze_1_nie_jest_blokowana_w_turze_2(self, monkeypatch):
        # Task 8, B1: rejestr kwot MUSI przetrwac granice tury (patrz docstring
        # modulu bots_pro/stan.py i TestKwoty w test_pro_stan.py). Tura 1 liczy
        # wycene i wysyla podsumowanie -- symulujemy to rejestracja kwoty
        # [1936.71] W TRAKCIE run_sync (jak w prawdziwym przebiegu
        # policz_wycene/podsumowanie.wyslij, patrz docstring _FalszywyRunner).
        # Tura 2 to OSOBNE wywolanie tura.uruchom (nowa tura TEJ SAMEJ rozmowy,
        # wiec nowe stan.ustaw_kontekst) i NIC nie rejestruje -- dokladnie jak
        # prawdziwe zapisz_wycene, ktore tylko CYTUJE juz ustalona cene, a nie
        # zasila rejestr od nowa. Model naturalnie potwierdza zapis, cytujac
        # cene z tury 1 -- guardrail NIE MOZE tego zablokowac.
        conv_id = 96110
        fake_runner = _FalszywyRunner(
            ["Podsumowanie: 1936,71 zł. Czy potwierdza Pan?", "Wycena na 1936,71 zł zapisana."],
            rejestruj_kwoty=[[1936.71], None])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        monkeypatch.setattr(
            stan, "handoff",
            lambda powod: pytest.fail("guardrail nie powinien zablokowac prawdziwej ceny: %r" % powod))

        tura.uruchom(conv_id, "inbox1", "Poprosze wycene blatu", persona="quote")
        tura.uruchom(conv_id, "inbox1", "Tak, potwierdzam", persona="quote")

        assert wyslane == ["Podsumowanie: 1936,71 zł. Czy potwierdza Pan?",
                           "Wycena na 1936,71 zł zapisana."]
        # Obie tury wywolaly Runnera dokladnie raz - bez korekty guardraila.
        assert len(fake_runner.wywolania) == 2

    def test_pusta_druga_proba_po_naruszeniu_konczy_sie_handoffem_nie_cisza(self, monkeypatch):
        # Runda poprawek 1, W1: sciezka `sprawdz_ceny("") == []` (pusty tekst nie ma
        # zadnych kwot, wiec formalnie "brak naruszen") NIE MOZE zostac odczytana jako
        # "model sie poprawil" - klient ma dostac czlowieka, nie cisze.
        conv_id = 96108
        fake_runner = _FalszywyRunner([
            "Cena wynosi 999,00 zł.",   # 1. proba - zla kwota
            "",                          # 2. proba (korekta) - model NIC nie odpisal
        ])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        powody = []
        monkeypatch.setattr(stan, "handoff", lambda powod: powody.append(powod) or {"ok": True})

        tura.uruchom(conv_id, "inbox1", "Ile kosztuje blat?", persona="quote")

        # Nic bledego ani pustego nie poszlo do klienta — tylko komunikat o
        # przekazaniu rozmowy (U7).
        assert wyslane == [tura.KOMUNIKAT_HANDOFF]
        assert len(powody) == 1   # i klient dostal czlowieka - nie zostal bez odpowiedzi

    def test_niepowodzenie_handoffu_jest_logowane(self, monkeypatch):
        # Drobne z rundy poprawek 1: {"ok": False} ze stan.handoff nie ma wygladac
        # z zewnatrz identycznie jak udany handoff.
        conv_id = 96109
        fake_runner = _FalszywyRunner(["Cena wynosi 999,00 zł.", "Nadal 999,00 zł."])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        _wyslane_przechwytywacz(monkeypatch)
        monkeypatch.setattr(stan, "handoff", lambda powod: {"ok": False})
        logi = []
        monkeypatch.setattr(tura, "log", lambda tekst: logi.append(tekst))

        tura.uruchom(conv_id, "inbox1", "Ile kosztuje blat?", persona="quote")

        assert any("NIEUDANY" in wpis for wpis in logi)


class TestBrakDublowaniaPodsumowania:
    """podsumowanie.wyslij() (wolane jako narzedzie) sam wysyla i zostawia
    final_output puste - tura NIE MOZE wyslac tego jeszcze raz."""

    def test_pusta_odpowiedz_modelu_nic_nie_wysyla(self, monkeypatch):
        conv_id = 96104
        fake_runner = _FalszywyRunner([""])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "cokolwiek", persona="quote")

        assert wyslane == []
        assert len(fake_runner.wywolania) == 1   # bez proby korekty - nie bylo tekstu do sprawdzenia

    def test_niepusty_final_output_po_wyslaniu_podsumowania_tez_nie_jest_wysylany(self, monkeypatch):
        # Runda poprawek 1, W3: wskazowka "zostaw final_output puste" w podsumowanie.py
        # to prosba w prompcie, nie bramka - model MOZE ja zignorowac i dopisac wlasnymi
        # slowami sparafrazowane podsumowanie (nawet z ta sama, prawdziwa cena, ktora G1
        # by przepuscil). Symulujemy to: fikcyjny Runner odtwarza to, co w prawdziwym
        # przebiegu robi narzedzie wyslij_podsumowanie (stan.oznacz_podsumowanie_wyslane)
        # W TRAKCIE run_sync, a POTEM model i tak cos dopisuje w final_output.
        conv_id = 96112

        class _RunnerZPodsumowaniemWTrakcie:
            def run_sync(self, agent, tresc, session=None, max_turns=None):
                stan.oznacz_podsumowanie_wyslane()
                return types.SimpleNamespace(
                    final_output="Wyslalem podsumowanie, czekam na Twoja odpowiedz.")

        monkeypatch.setattr(tura, "Runner", _RunnerZPodsumowaniemWTrakcie())
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "poprosze wycene", persona="quote")

        assert wyslane == []

    def test_nieudane_podsumowanie_i_pusta_odpowiedz_konczy_sie_handoffem_nie_cisza(
            self, monkeypatch):
        # U1 (recenzja koncowa): gdy Chatwoot nie przyjal podsumowania, `wyslij()`
        # NIE oznacza tury jako obsluzonej — wiec zwykla odpowiedz modelu i tak by
        # poszla. Ale model moze nic nie napisac (wskazowka z promptu: "final_output
        # moze byc puste"). Wtedy tura konczy sie BEZ ANI JEDNEJ wiadomosci — ta sama
        # awaria co w audycie. Ma byc handoff, nie cisza.
        conv_id = 96131

        class _RunnerZNieudanymPodsumowaniem:
            def run_sync(self, agent, tresc, session=None, max_turns=None):
                stan.oznacz_podsumowanie_nieudane()
                return types.SimpleNamespace(final_output="")

        monkeypatch.setattr(tura, "Runner", _RunnerZNieudanymPodsumowaniem())
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        powody = []
        monkeypatch.setattr(stan, "handoff", lambda powod: powody.append(powod) or {"ok": True})

        tura.uruchom(conv_id, "inbox1", "poprosze wycene", persona="quote")

        # U7: zamiast ciszy klient dostaje komunikat o przekazaniu rozmowy.
        assert wyslane == [tura.KOMUNIKAT_HANDOFF]
        assert len(powody) == 1

    def test_nieudane_podsumowanie_z_odpowiedzia_modelu_nie_daje_handoffu(self, monkeypatch):
        # Kontrola negatywna: gdy model mimo wszystko cos napisal, klient dostaje
        # wiadomosc — handoff bylby wtedy niepotrzebna eskalacja.
        conv_id = 96132

        class _RunnerZNieudanymPodsumowaniem:
            def run_sync(self, agent, tresc, session=None, max_turns=None):
                stan.oznacz_podsumowanie_nieudane()
                return types.SimpleNamespace(
                    final_output="Przepraszam, sprobuje jeszcze raz za chwile.")

        monkeypatch.setattr(tura, "Runner", _RunnerZNieudanymPodsumowaniem())
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        monkeypatch.setattr(stan, "handoff",
                            lambda powod: pytest.fail("nie powinno dojsc do handoffu"))

        tura.uruchom(conv_id, "inbox1", "poprosze wycene", persona="quote")

        assert wyslane == ["Przepraszam, sprobuje jeszcze raz za chwile."]

    def test_bez_wyslania_podsumowania_zwykla_odpowiedz_nadal_idzie_do_klienta(self, monkeypatch):
        # Kontrola negatywna: bramka W3 nie ma blokowac zwyklych odpowiedzi, w
        # ktorych podsumowanie.wyslij() w ogole nie bylo wolane w tej turze.
        conv_id = 96113
        fake_runner = _FalszywyRunner(["Dziekuje, wracam z odpowiedzia."])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "test", persona="quote")

        assert wyslane == ["Dziekuje, wracam z odpowiedzia."]


class TestBezpiecznikDlugosciRozmowy:
    """Task 8, B2: audyt pokazal, ze stary limit 30 tur (dawne BOT_PRO_MAX_TURNS,
    dzis BOT_PRO_MAX_RUNNER_STEPS — limit ITERACJI SDK wewnatrz JEDNEJ tury, nie
    dlugosci rozmowy) nie uratowal ANI JEDNEJ z 10 zapetlonych rozmow w zbadanym
    shardzie — klienci odpadali przy 10-28 turach. Ten bezpiecznik liczy TURY
    CALEJ ROZMOWY (bots_pro.stan.zarejestruj_ture) i konczy handoffem PRZED
    wywolaniem Routera/LLM, gdy rozmowa przekroczy prog."""

    def test_tury_ponizej_progu_przebiegaja_normalnie(self, monkeypatch):
        conv_id = 96114
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 2)
        fake_runner = _FalszywyRunner(["odp1", "odp2"])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "wiadomosc 1", persona="quote")
        tura.uruchom(conv_id, "inbox1", "wiadomosc 2", persona="quote")

        assert wyslane == ["odp1", "odp2"]
        assert len(fake_runner.wywolania) == 2

    def test_tura_przekraczajaca_prog_konczy_sie_handoffem_bez_wywolania_routera(self, monkeypatch):
        conv_id = 96115
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 2)
        fake_runner = _FalszywyRunner(["odp1", "odp2", "odp3"])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        powody = []
        monkeypatch.setattr(stan, "handoff", lambda powod: powody.append(powod) or {"ok": True})

        tura.uruchom(conv_id, "inbox1", "wiadomosc 1", persona="quote")
        tura.uruchom(conv_id, "inbox1", "wiadomosc 2", persona="quote")
        tura.uruchom(conv_id, "inbox1", "wiadomosc 3", persona="quote")   # 3. > prog 2

        # Trzecia tura NIE wywolala Routera/LLM w ogole — limit przekroczony PRZED nim,
        # ale klient dostal komunikat o przekazaniu rozmowy (U7).
        assert wyslane == ["odp1", "odp2", tura.KOMUNIKAT_HANDOFF]
        assert len(fake_runner.wywolania) == 2
        assert len(powody) == 1
        assert "tur" in powody[0].lower()

    def test_zero_wylacza_bezpiecznik_nie_daje_natychmiastowego_handoffu(self, monkeypatch):
        # Minor (runda poprawek 1): operator wpisujacy 0, zeby WYLACZYC bezpiecznik,
        # nie ma dostac najagresywniejszego ustawienia (handoff od pierwszej tury).
        # BOT_PRO_MAX_BEZ_POSTEPU tez wylaczony — atrapa nizej celowo NIE zmienia
        # stanu (izolujemy dokladnie ZACHOWANIE LICZNIKA TUR, nie oba bezpieczniki naraz).
        conv_id = 96121
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 0)
        monkeypatch.setattr(tura, "BOT_PRO_MAX_BEZ_POSTEPU", 0)
        fake_runner = _FalszywyRunner(["odp1"] * 20)
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        monkeypatch.setattr(stan, "handoff",
                            lambda powod: pytest.fail("bezpiecznik mial byc wylaczony"))

        for i in range(20):
            tura.uruchom(conv_id, "inbox1", "wiadomosc %s" % i, persona="quote")

        assert len(wyslane) == 20


class TestBezpiecznikBrakuPostepu:
    """Task 8, B2: osobny licznik tur BEZ POSTEPU (bez zadnej zmiany stanu
    biznesowego rozmowy — pozycji, wyslanego podsumowania, potwierdzenia,
    zapisanej wyceny), niezalezny od licznika dlugosci rozmowy wyzej."""

    def test_kolejne_tury_bez_zadnej_zmiany_stanu_koncza_sie_handoffem(self, monkeypatch):
        conv_id = 96116
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 100)
        monkeypatch.setattr(tura, "BOT_PRO_MAX_BEZ_POSTEPU", 2)
        fake_runner = _FalszywyRunner(["a", "b"])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        powody = []
        monkeypatch.setattr(stan, "handoff", lambda powod: powody.append(powod) or {"ok": True})

        tura.uruchom(conv_id, "inbox1", "wiadomosc 1", persona="quote")   # 1. bez postepu
        tura.uruchom(conv_id, "inbox1", "wiadomosc 2", persona="quote")   # 2. bez postepu -> prog

        # Odpowiedz WCIAZ wyslana w obu turach — to NIE jest guardrail, bot po
        # prostu nie posuwa sprawy do przodu (np. zapetlone dopytywanie). Po
        # drugiej turze dochodzi komunikat o przekazaniu rozmowy (U7).
        assert wyslane == ["a", "b", tura.KOMUNIKAT_HANDOFF]
        assert len(powody) == 1
        assert "postep" in powody[0].lower()

    def test_zmiana_stanu_resetuje_licznik_braku_postepu(self, monkeypatch):
        conv_id = 96117
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 100)
        monkeypatch.setattr(tura, "BOT_PRO_MAX_BEZ_POSTEPU", 2)

        class _RunnerZapisujacyPozycjeWDrugiejTurze:
            def __init__(self):
                self.wywolania = []

            def run_sync(self, agent, tresc, session=None, max_turns=None):
                self.wywolania.append(tresc)
                if len(self.wywolania) == 2:
                    stan.zapisz_pozycje("1", produkt="blat", dlugosc_cm=100)
                return types.SimpleNamespace(final_output="odp")

        fake_runner = _RunnerZapisujacyPozycjeWDrugiejTurze()
        monkeypatch.setattr(tura, "Runner", fake_runner)
        _wyslane_przechwytywacz(monkeypatch)
        powody = []
        monkeypatch.setattr(stan, "handoff", lambda powod: powody.append(powod) or {"ok": True})

        tura.uruchom(conv_id, "inbox1", "wiadomosc 1", persona="quote")   # bez postepu (1)
        tura.uruchom(conv_id, "inbox1", "wiadomosc 2", persona="quote")   # POSTEP -> reset do 0
        tura.uruchom(conv_id, "inbox1", "wiadomosc 3", persona="quote")   # bez postepu (1, NIE 3)

        assert powody == []   # prog 2 nigdy nie zostal osiagniety DWA RAZY Z RZEDU

    def test_zero_wylacza_bezpiecznik_nie_daje_natychmiastowego_handoffu(self, monkeypatch):
        conv_id = 96122
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 100)
        monkeypatch.setattr(tura, "BOT_PRO_MAX_BEZ_POSTEPU", 0)
        fake_runner = _FalszywyRunner(["a"] * 10)
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        monkeypatch.setattr(stan, "handoff",
                            lambda powod: pytest.fail("bezpiecznik mial byc wylaczony"))

        for i in range(10):
            tura.uruchom(conv_id, "inbox1", "wiadomosc %s" % i, persona="quote")

        assert len(wyslane) == 10


class TestLicznikTurNieMylonyZRetryWorkera:
    """W3 (runda poprawek 1, code review KRYTYCZNE): `quote_worker.process_one`
    po wyjatku przejsciowym wraca wierszem kolejki do 'pending' i woła
    `tura.uruchom` PONOWNIE dla TEJ SAMEJ wiadomosci klienta (ten sam
    message_id) — retry NIE MOZE zuzywac budzetu BOT_PRO_MAX_TURNS, bo kilka
    bledow sieci konczyloby sie przedwczesnym handoffem "limit dlugosci
    rozmowy" bez zadnego udzialu klienta."""

    def test_dwa_wywolania_z_tym_samym_message_id_licza_sie_jako_jedna_tura(self, monkeypatch):
        from core.db import db

        conv_id = 96118
        fake_runner = _FalszywyRunner(["odp1", "odp2"])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "wiadomosc 1", persona="quote", message_id="mid-1")
        tura.uruchom(conv_id, "inbox1", "wiadomosc 1", persona="quote", message_id="mid-1")

        c = db()
        wiersz = c.execute("SELECT tury_rozmowy FROM pro_stan WHERE conv_id=?",
                           (conv_id,)).fetchone()
        c.close()
        assert wiersz["tury_rozmowy"] == 1

    def test_nowy_message_id_liczy_sie_jako_nowa_tura(self, monkeypatch):
        from core.db import db

        conv_id = 96119
        fake_runner = _FalszywyRunner(["odp1", "odp2"])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "wiadomosc 1", persona="quote", message_id="mid-1")
        tura.uruchom(conv_id, "inbox1", "wiadomosc 2", persona="quote", message_id="mid-2")

        c = db()
        wiersz = c.execute("SELECT tury_rozmowy FROM pro_stan WHERE conv_id=?",
                           (conv_id,)).fetchone()
        c.close()
        assert wiersz["tury_rozmowy"] == 2

    def test_brak_message_id_liczy_sie_zawsze_jako_nowa_tura(self, monkeypatch):
        # Bez identyfikatora nie da sie wykryc retry — zachowanie SPRZED W3
        # (kazde wywolanie to nowa tura), zeby wywolania bez message_id (np.
        # istniejace testy w tym pliku) nie zmienily zachowania.
        from core.db import db

        conv_id = 96120
        fake_runner = _FalszywyRunner(["odp1", "odp2"])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "wiadomosc 1", persona="quote")
        tura.uruchom(conv_id, "inbox1", "wiadomosc 2", persona="quote")

        c = db()
        wiersz = c.execute("SELECT tury_rozmowy FROM pro_stan WHERE conv_id=?",
                           (conv_id,)).fetchone()
        c.close()
        assert wiersz["tury_rozmowy"] == 2


class TestPersonaKanaluWTurze:
    """Persona kanalu MUSI trafic do stan.ustaw_kontekst, nie zostac lokalnym
    parametrem - inaczej podsumowanie.wyslij() (ktore czyta stan.persona()) wyslaloby
    sie z domyslnym profilem 'pro' zamiast ALLEGRO_CAPS."""

    def test_persona_z_wywolania_trafia_do_stanu(self, monkeypatch):
        conv_id = 96105
        fake_runner = _FalszywyRunner(["Dziekuje za wiadomosc."])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "test", persona="quote_allegro")

        assert stan.persona() == "quote_allegro"

    def test_link_z_odpowiedzi_wycinany_na_allegro(self, monkeypatch):
        conv_id = 96106
        tekst = "Szczegoly wyceny: https://crm.woodpower.pl/quotes/c/XYZ"
        fake_runner = _FalszywyRunner([tekst])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "poprosze wycene", persona="quote_allegro")

        assert wyslane, "wiadomosc powinna zostac wyslana (bez linku)"
        assert "https://" not in wyslane[0]

    def test_link_zostaje_na_livechat(self, monkeypatch):
        conv_id = 96107
        tekst = "Szczegoly wyceny: https://crm.woodpower.pl/quotes/c/XYZ"
        fake_runner = _FalszywyRunner([tekst])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "poprosze wycene", persona="quote")

        assert "https://crm.woodpower.pl/quotes/c/XYZ" in wyslane[0]


# ---------------------------------------------------------------------------
# Atrapa MODELU (nie Runnera) - dla testu architektury routingu. Prawdziwy
# Router, prawdziwi agenci wyspecjalizowani, prawdziwy Runner.run_sync z SDK;
# jedynie odpowiedzi modelu sa sterowane z testu, zeby nie zalezec od sieci.
# ---------------------------------------------------------------------------
def _wiadomosc_tekstowa(tekst, ident):
    return ModelResponse(
        output=[ResponseOutputMessage(
            id="msg_%s" % ident, status="completed", role="assistant", type="message",
            content=[ResponseOutputText(type="output_text", text=tekst, annotations=[])],
        )],
        usage=Usage(), response_id=None,
    )


def _wywolanie_transferu(nazwa_agenta, ident):
    nazwa_narzedzia = "transfer_to_%s" % nazwa_agenta.lower()
    return ModelResponse(
        output=[ResponseFunctionToolCall(
            type="function_call", call_id="call_%s" % ident, name=nazwa_narzedzia,
            arguments="{}", id="fc_%s" % ident,
        )],
        usage=Usage(), response_id=None,
    )


def _ostatnia_wiadomosc_uzytkownika(input_):
    if isinstance(input_, str):
        return input_
    for pozycja in reversed(input_):
        if isinstance(pozycja, dict) and pozycja.get("role") == "user":
            tresc = pozycja.get("content")
            if isinstance(tresc, str):
                return tresc
    return ""


class _FalszywyModel(Model):
    """Model sterowany slowami kluczowymi z ostatniej wiadomosci klienta - stoi
    w miejscu prawdziwego LLM tylko po to, zeby test nie potrzebowal sieci ani
    klucza API. Rozroznia role po ksztalcie wywolania: router dostaje niepusta
    liste `handoffs` (agenci wyspecjalizowani maja handoffs=[]), a konkretnego
    agenta wyspecjalizowanego po liczbie narzedzi (Wycena=_NARZEDZI_WYCENY,
    Wiedza=2)."""

    def __init__(self):
        self.wywolania = []

    async def get_response(self, system_instructions, input, model_settings, tools,
                            output_schema, handoffs, tracing, *, previous_response_id,
                            conversation_id, prompt):
        licznik = len(self.wywolania)
        # Zapamietujemy tez SUROWY `input` - drobne z rundy poprawek 1: bez tego test
        # scenariusza dowodzilby tylko routingu po slowach kluczowych z BIEZACEJ
        # wiadomosci, a nie tego, ze druga tura NAPRAWDE widziala historie pierwszej
        # (przeszlaby tak samo, gdyby sesja byla po cichu ignorowana).
        self.wywolania.append({"n_handoffs": len(handoffs), "n_tools": len(tools), "input": input})

        # Rozpoznanie PO LICZBIE NARZEDZI (tools=0 => Router), NIE po samej obecnosci
        # handoffs (Task 8, B4: Wiedza dostala WLASNY handoff do Wyceny, wiec `handoffs`
        # jest niepuste TEZ dla niej — sprawdzenie "if handoffs:" jak w poprzedniej wersji
        # tej atrapy zlapaloby wiec Wiedze tak, jakby byla Routerem).
        if len(tools) == 0:
            tekst = _ostatnia_wiadomosc_uzytkownika(input).lower()
            if any(s in tekst for s in ("kosztowac", "cena", "koszt", "ile to")):
                return _wywolanie_transferu("Wycena", licznik)
            return _wywolanie_transferu("Wiedza", licznik)

        if len(tools) == _NARZEDZI_WYCENY:
            return _wiadomosc_tekstowa(
                "Aby przygotowac wycene, potrzebuje material, wymiary i ilosc sztuk.", licznik)
        return _wiadomosc_tekstowa(
            "Dab lity jest twardy i odporny na scieranie.", licznik)

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError


class TestScenariuszMaterialPotemCena:
    """NAJWAZNIEJSZA decyzja Task 6: agenci wyspecjalizowani nie maja wlasnych
    handoffow, wiec droga z Wiedzy do Wyceny istnieje TYLKO miedzy turami, przez
    ponowne wejscie przez Router. Ten test dowodzi, ze to naprawde dziala -
    bez atrapowania samego Runnera (patrz naglowek modulu)."""

    def test_pytanie_o_material_potem_prosba_o_cene_dociera_do_wyceny(self, monkeypatch):
        conv_id = 96201
        fake_model = _FalszywyModel()
        monkeypatch.setattr(agenci, "model_dla_roli", lambda rola: fake_model)
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "Jaki macie dab, czy jest twardy?", persona="quote")
        tura.uruchom(conv_id, "inbox1", "Ile bedzie kosztowac blat 200x60x4?", persona="quote")

        assert len(wyslane) == 2
        assert "twardy" in wyslane[0].lower()
        assert "wycene" in wyslane[1].lower() or "wymiary" in wyslane[1].lower()

        # Router zostal wywolany OD NOWA w KAZDEJ turze. Identyfikujemy go po LICZBIE
        # NARZEDZI (tools=0), NIE po samej obecnosci handoffs (Task 8, B4: Wiedza ma
        # TERAZ TEZ wlasny handoff do Wyceny, wiec n_handoffs>0 nie jest juz unikalne
        # dla Routera — patrz komentarz w _FalszywyModel.get_response wyzej).
        wywolania_routera = [w for w in fake_model.wywolania if w["n_tools"] == 0]
        assert len(wywolania_routera) == 2

        # Router w DRUGIEJ turze naprawde WIDZIAL historie z pierwszej (odpowiedz
        # Wiedzy o twardosci debu) - to dowod, ze routing dziala dzieki SESJI, nie
        # dzieki temu, ze druga wiadomosc akurat zawiera nowe slowo kluczowe. Bez
        # tej asercji test przeszedlby identycznie, gdyby `_sesja()` po cichu
        # ignorowala historie (kazda tura widzialaby TYLKO swoja biezaca wiadomosc).
        wejscie_drugiej_tury = json.dumps(
            wywolania_routera[-1]["input"], default=str, ensure_ascii=False).lower()
        assert "twardy" in wejscie_drugiej_tury

        # Ostatnie wywolanie modelu w calym przebiegu to NAPRAWDE agent Wyceny
        # (komplet NARZEDZIA_WYCENY) - mimo ze poprzednia tura skonczyla sie na
        # Wiedzy (2 narzedzia), ktora nie ma wlasnego handoffu do Wyceny.
        assert fake_model.wywolania[-1]["n_tools"] == _NARZEDZI_WYCENY


class _FalszywyModelZlozonePytanie(Model):
    """Do testu scenariusza (a) z Task 8, B4: pytanie w JEDNEJ wiadomosci laczy
    prosbe o wiedze (material) i o cene. Router (naturalnie, po pierwszej czesci
    zdania) trafia najpierw do Wiedzy — ktora TERAZ (B4) ma WLASNY handoff do
    Wyceny i moze oddac rozmowe DALEJ w TEJ SAMEJ turze, bez czekania na kolejna
    wiadomosc klienta (przed B4 to bylo niemozliwe — patrz TestScenariuszMaterialPotemCena
    wyzej, gdzie ten sam przypadek wymagal DWOCH oddzielnych tur)."""

    def __init__(self):
        self.wywolania = []

    async def get_response(self, system_instructions, input, model_settings, tools,
                            output_schema, handoffs, tracing, *, previous_response_id,
                            conversation_id, prompt):
        licznik = len(self.wywolania)
        self.wywolania.append({"n_tools": len(tools), "n_handoffs": len(handoffs)})
        if len(tools) == 0:
            # Router: zawsze trafia najpierw do Wiedzy - pytanie klienta zaczyna
            # sie od "z czego robicie", nie od prosby o cene.
            return _wywolanie_transferu("Wiedza", licznik)
        if len(tools) == 2:
            # Wiedza (B4): rozpoznaje, ze pytanie wymaga TEZ wyceny i oddaje
            # rozmowe do Wyceny WEWNATRZ TEJ SAMEJ tury - nowy handoff, ktorego
            # przed B4 Wiedza nie miala.
            return _wywolanie_transferu("Wycena", licznik)
        # Wycena (komplet NARZEDZIA_WYCENY) - dokonczenie w tej samej turze.
        return _wiadomosc_tekstowa(
            "Blaty robimy z debu, jesionu i buku. Dla 180x60x4 cm potrzebuje jeszcze "
            "ilosci sztuk i wybranego gatunku, zeby policzyc cene.", licznik)

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError


class TestHandoffWiedzaDoWyceny:
    """Task 8, B4: agent Wiedzy dostal WLASNY handoff do Wyceny (agenci.py) —
    bez atrapowania Runnera, prawdziwy Router + prawdziwi agenci + prawdziwy
    Runner.run_sync z SDK, jak w TestScenariuszMaterialPotemCena."""

    def test_zlozone_pytanie_material_i_cena_dostaje_wycene_w_jednej_turze(self, monkeypatch):
        conv_id = 96202
        fake_model = _FalszywyModelZlozonePytanie()
        monkeypatch.setattr(agenci, "model_dla_roli", lambda rola: fake_model)
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "Z czego robicie blaty i ile wyjdzie 180x60x4?",
                     persona="quote")

        # JEDNO wywolanie tura.uruchom (JEDNA wiadomosc klienta), a odpowiedz
        # przyszla juz od Wyceny - dowod, ze handoff Wiedza -> Wycena zadzialal
        # WEWNATRZ tej samej tury, nie dopiero w nastepnej.
        assert len(wyslane) == 1
        assert "blaty" in wyslane[0].lower()

        # Trasa: Router (0 narzedzi) -> Wiedza (2 narzedzia) -> Wycena (komplet).
        assert [w["n_tools"] for w in fake_model.wywolania] == [0, 2, _NARZEDZI_WYCENY]


class TestZalacznikiTrafiajaDoModelu:
    """U2 (recenzja końcowa): `zalaczniki` były WYŁĄCZNIE w sygnaturze `uruchom`
    (zero użyć w ciele), więc wiadomość samym zdjęciem szła do modelu jako PUSTY
    string, a obrazy do kosza. Webhook celowo przepuszcza wiadomość bez tekstu,
    gdy ma obraz (`webhooks._process_pro`), a klienci WoodPower przysyłają zdjęcia
    rutynowo."""

    def test_sam_obraz_nie_daje_pustego_wejscia(self, monkeypatch):
        conv_id = 96203001
        monkeypatch.setattr(tura.obrazy, "to_data_uri",
                            lambda url, formats=None: "data:image/jpeg;base64,AAA")
        fake_runner = _FalszywyRunner(["Widze zdjecie, prosze o wymiary."])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "", zalaczniki=["https://x/foto.jpg"], persona="olx")

        wejscie = fake_runner.wywolania[0]
        assert wejscie != ""
        assert wejscie == [{"role": "user", "content": [
            {"type": "input_image", "image_url": "data:image/jpeg;base64,AAA"}]}]

    def test_tekst_z_obrazem_leci_razem(self, monkeypatch):
        conv_id = 96203002
        monkeypatch.setattr(tura.obrazy, "to_data_uri",
                            lambda url, formats=None: "data:image/jpeg;base64,BBB")
        fake_runner = _FalszywyRunner(["ok"])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "taki jak na zdjeciu",
                     zalaczniki='["https://x/foto.jpg"]', persona="pro")

        czesci = fake_runner.wywolania[0][0]["content"]
        assert [c["type"] for c in czesci] == ["input_text", "input_image"]

    def test_profil_kanalu_decyduje_o_dozwolonych_formatach(self, monkeypatch):
        conv_id = 96203003
        pytania = []
        monkeypatch.setattr(tura.obrazy, "to_data_uri",
                            lambda url, formats=None: pytania.append(formats) or None)
        monkeypatch.setattr(tura, "Runner", _FalszywyRunner(["ok"]))
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "tekst", zalaczniki=["https://x/a.webp"],
                     persona="allegro")

        assert pytania == [("jpg", "jpeg", "png")]

    def test_bez_zalacznikow_wejscie_zostaje_stringiem(self, monkeypatch):
        conv_id = 96203004
        fake_runner = _FalszywyRunner(["ok"])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "dzien dobry", persona="pro")

        assert fake_runner.wywolania == ["dzien dobry"]


class TestWyjsciaHandoffoweNieSaCiche:
    """U7 (recenzja końcowa): trzy z czterech wyjść handoffowych robiły `return`
    bez ŻADNEJ wysyłki — klient dostawał ciszę, a konsultant nie wiedział,
    dlaczego dostał rozmowę. Każde z czterech ma teraz zostawić wiadomość do
    klienta (przez profil kanału) ORAZ notatkę dla agenta (ta druga siedzi w
    `stan.handoff`, patrz test_pro_notatki.py)."""

    def test_limit_tur_mowi_klientowi_ze_przekazuje(self, monkeypatch):
        conv_id = 96204001
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 1)
        monkeypatch.setattr(tura, "Runner", _FalszywyRunner(["odp1"]))
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        monkeypatch.setattr(stan, "handoff", lambda powod: {"ok": True})

        tura.uruchom(conv_id, "inbox1", "wiadomosc 1", persona="quote")
        tura.uruchom(conv_id, "inbox1", "wiadomosc 2", persona="quote")   # ponad limit

        assert wyslane == ["odp1", tura.KOMUNIKAT_HANDOFF]

    def test_podwojne_naruszenie_guardraila_mowi_klientowi(self, monkeypatch):
        conv_id = 96204002
        monkeypatch.setattr(tura, "Runner",
                            _FalszywyRunner(["Cena to 999,00 zl", "Nadal 999,00 zl"]))
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        monkeypatch.setattr(stan, "handoff", lambda powod: {"ok": True})

        tura.uruchom(conv_id, "inbox1", "ile kosztuje?", persona="quote")

        # Zadna z dwoch halucynacji NIE poszla do klienta, ale klient NIE zostal
        # w ciszy — dostal komunikat o przekazaniu.
        assert wyslane == [tura.KOMUNIKAT_HANDOFF]

    def test_brak_postepu_mowi_klientowi_po_zwyklej_odpowiedzi(self, monkeypatch):
        conv_id = 96204003
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 100)
        monkeypatch.setattr(tura, "BOT_PRO_MAX_BEZ_POSTEPU", 1)
        monkeypatch.setattr(tura, "Runner", _FalszywyRunner(["a"]))
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        monkeypatch.setattr(stan, "handoff", lambda powod: {"ok": True})

        tura.uruchom(conv_id, "inbox1", "wiadomosc", persona="quote")

        assert wyslane == ["a", tura.KOMUNIKAT_HANDOFF]

    def test_komunikat_przechodzi_przez_profil_kanalu(self, monkeypatch):
        """Na Allegro/OLX komunikat MUSI iść przez `wysylka.przygotuj` — inaczej
        omija profil kanału tak samo, jak omijały go dawne (nieistniejące) komunikaty."""
        conv_id = 96204004
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 1)
        monkeypatch.setattr(tura, "Runner", _FalszywyRunner(["odp1"]))
        _wyslane_przechwytywacz(monkeypatch)
        monkeypatch.setattr(stan, "handoff", lambda powod: {"ok": True})
        uzyte_persony = []
        prawdziwa = tura.wysylka.przygotuj
        monkeypatch.setattr(tura.wysylka, "przygotuj",
                            lambda tekst, persona: uzyte_persony.append(persona) or
                            prawdziwa(tekst, persona))

        tura.uruchom(conv_id, "inbox1", "wiadomosc 1", persona="allegro")
        tura.uruchom(conv_id, "inbox1", "wiadomosc 2", persona="allegro")

        assert uzyte_persony == ["allegro", "allegro"]

    def test_handoff_z_narzedzia_bez_odpowiedzi_modelu_nie_zostawia_ciszy(self, monkeypatch):
        """Model sam oddal rozmowe (narzedzie `oddaj_czlowiekowi`, albo
        `przygotuj_zamowienie` na Allegro — U11) i NIC nie napisal. Klient nie
        moze zostac w ciszy tylko dlatego, ze handoff poszedl z narzedzia,
        a nie z bezpiecznika tury."""
        conv_id = 96204006
        monkeypatch.setattr(notatki, "wyslij_notatke", lambda cid, tekst: True)
        monkeypatch.setattr("core.chatwoot.cw_bot_handoff", lambda cid, token=None: True)

        class _RunnerZHandoffemZNarzedzia:
            def run_sync(self, agent, tresc, session=None, max_turns=None):
                stan.handoff("klient prosi o czlowieka")
                return types.SimpleNamespace(final_output="")

        monkeypatch.setattr(tura, "Runner", _RunnerZHandoffemZNarzedzia())
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "prosze o konsultanta", persona="quote")

        assert wyslane == [tura.KOMUNIKAT_HANDOFF]

    def test_handoff_z_narzedzia_z_odpowiedzia_modelu_nie_dubluje_komunikatu(self, monkeypatch):
        # Kontrola negatywna: model napisal wlasne pozegnanie — drugi, sklejony
        # w kodzie komunikat bylby zbedna powtorka.
        conv_id = 96204007
        monkeypatch.setattr(notatki, "wyslij_notatke", lambda cid, tekst: True)
        monkeypatch.setattr("core.chatwoot.cw_bot_handoff", lambda cid, token=None: True)

        class _RunnerZHandoffemIOdpowiedzia:
            def run_sync(self, agent, tresc, session=None, max_turns=None):
                stan.handoff("reklamacja")
                return types.SimpleNamespace(
                    final_output="Rozumiem, przekazuje sprawe konsultantowi.")

        monkeypatch.setattr(tura, "Runner", _RunnerZHandoffemIOdpowiedzia())
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "reklamacja", persona="quote")

        assert wyslane == ["Rozumiem, przekazuje sprawe konsultantowi."]

    def test_nieudane_podsumowanie_bez_odpowiedzi_modelu_konczy_komunikatem(self, monkeypatch):
        conv_id = 96204005
        monkeypatch.setattr(tura, "Runner", _FalszywyRunner([""]))
        wyslane = _wyslane_przechwytywacz(monkeypatch)
        monkeypatch.setattr(stan, "podsumowanie_nieudane", lambda: True)
        monkeypatch.setattr(stan, "handoff", lambda powod: {"ok": True})

        tura.uruchom(conv_id, "inbox1", "tak", persona="quote")

        assert wyslane == [tura.KOMUNIKAT_HANDOFF]


class TestHandoffIdempotentnyWTurze:
    """N7 (rerecenzja gałęzi): model woła narzędzie oddania rozmowy I pisze
    pożegnanie. Tura nie zmienia stanu biznesowego, więc bezpiecznik braku
    postępu oddaje rozmowę DRUGI RAZ: dwie notatki, dwie wiadomości, dwa
    przełączenia statusu — do rozmowy, która jest już w 'open' i należy do
    człowieka. Konsultant dostaje dwie prawie identyczne notatki, klient dwie
    wiadomości pod rząd.

    Bramka `handoff_w_turze() and not odpowiedz` (U11) tego nie łapała, bo
    model COŚ napisał."""

    def _slady_handoffu(self, monkeypatch):
        """Liczy PRAWDZIWE skutki uboczne oddania rozmowy (notatka + toggle) —
        `stan.handoff` NIE jest tu podmieniony, bo to jego idempotencji
        dotyczy ten test."""
        slady = {"notatki": [], "toggle": []}
        monkeypatch.setattr(notatki, "cw_note",
                            lambda cid, tekst, token=None: slady["notatki"].append(tekst) or True)
        monkeypatch.setattr("core.chatwoot.cw_bot_handoff",
                            lambda cid, token=None: slady["toggle"].append(cid) or True)
        return slady

    def test_narzedzie_i_bezpiecznik_nie_oddaja_rozmowy_dwa_razy(self, monkeypatch):
        conv_id = 96131
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 100)
        monkeypatch.setattr(tura, "BOT_PRO_MAX_BEZ_POSTEPU", 1)
        slady = self._slady_handoffu(monkeypatch)

        class _RunnerZHandoffemIPozegnaniem:
            wywolania = []

            def run_sync(self, agent, tresc, session=None, max_turns=None):
                self.wywolania.append(tresc)
                stan.handoff("klient prosi o czlowieka")   # narzedzie oddaj_czlowiekowi
                return types.SimpleNamespace(
                    final_output="Jasne, przekazuje Cie konsultantowi.")

        monkeypatch.setattr(tura, "Runner", _RunnerZHandoffemIPozegnaniem())
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "chce rozmawiac z czlowiekiem", persona="quote")

        assert wyslane == ["Jasne, przekazuje Cie konsultantowi."]
        assert len(slady["notatki"]) == 1
        assert len(slady["toggle"]) == 1

    def test_bezpiecznik_nadal_oddaje_rozmowe_gdy_narzedzie_tego_nie_zrobilo(
            self, monkeypatch):
        # Kontrola negatywna: idempotencja NIE MOŻE uciszyć bezpiecznika w
        # turze, w której handoffu jeszcze nie było.
        conv_id = 96132
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 100)
        monkeypatch.setattr(tura, "BOT_PRO_MAX_BEZ_POSTEPU", 1)
        slady = self._slady_handoffu(monkeypatch)
        monkeypatch.setattr(tura, "Runner", _FalszywyRunner(["kreci sie w kolko"]))
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "wiadomosc", persona="quote")

        assert wyslane == ["kreci sie w kolko", tura.KOMUNIKAT_HANDOFF]
        assert len(slady["notatki"]) == 1
        assert len(slady["toggle"]) == 1

    def test_kolejna_tura_moze_oddac_rozmowe_od_nowa(self, monkeypatch):
        # Idempotencja jest PER TURA (contextvar), nie per rozmowa.
        conv_id = 96133
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 100)
        monkeypatch.setattr(tura, "BOT_PRO_MAX_BEZ_POSTEPU", 1)
        slady = self._slady_handoffu(monkeypatch)
        monkeypatch.setattr(tura, "Runner", _FalszywyRunner(["a", "b"]))
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "wiadomosc 1", persona="quote")
        tura.uruchom(conv_id, "inbox1", "wiadomosc 2", persona="quote")

        assert len(slady["toggle"]) == 2

class TestBramkaIdempotencjiNieUciszaKomunikatu:
    """C2 (runda D): bramka idempotencji z N7 stała na POCZĄTKU
    `_oddaj_konsultantowi`, więc gasiła także `KOMUNIKAT_HANDOFF` — nie tylko
    powtórny handoff. Gdy handoff przyszedł z narzędzia, a wiadomości modelu
    NIE dotarły do klienta (zablokował je guardrail albo padło podsumowanie),
    tura kończyła się CISZĄ: klient nie dostawał ANI JEDNEJ wiadomości i nie
    wiedział, że rozmowę przejmuje człowiek. To ta sama awaria, którą zamykały
    U1/U7/U11 i którą audyt wskazał jako przyczynę porzuceń.

    Reguła: idempotentne są SKUTKI UBOCZNE (notatka + przełączenie statusu),
    a nie wiadomość do klienta. Komunikat pomijamy wyłącznie wtedy, gdy klient
    już dostał w tej turze wypowiedź modelu PO handoffie z narzędzia — wtedy
    pożegnanie napisał sam model (kontrola w `TestHandoffIdempotentnyWTurze`)."""

    def _slady_handoffu(self, monkeypatch):
        slady = {"notatki": [], "toggle": []}
        monkeypatch.setattr(notatki, "cw_note",
                            lambda cid, tekst, token=None: slady["notatki"].append(tekst) or True)
        monkeypatch.setattr("core.chatwoot.cw_bot_handoff",
                            lambda cid, token=None: slady["toggle"].append(cid) or True)
        return slady

    def test_handoff_z_narzedzia_i_podwojne_naruszenie_guardraila_nie_daja_ciszy(
            self, monkeypatch):
        """Sonda rerecenzji (przypadek B): model woła `oddaj_czlowiekowi` i pisze
        zdanie ze zmyśloną kwotą; korekta też z kwotą (typowe — model nie wie, co
        naprawia). Obie wypowiedzi blokuje guardrail, więc do klienta NIE poszło
        nic — komunikat o przekazaniu jest jedyną rzeczą, jaką dostanie."""
        conv_id = 96141
        slady = self._slady_handoffu(monkeypatch)

        class _RunnerZHandoffemINaruszeniami:
            odpowiedzi = ["Cena to 999,00 zl", "Nadal 999,00 zl"]

            def run_sync(self, agent, tresc, session=None, max_turns=None):
                stan.handoff("klient prosi o czlowieka")   # narzedzie oddaj_czlowiekowi
                return types.SimpleNamespace(final_output=self.odpowiedzi.pop(0))

        monkeypatch.setattr(tura, "Runner", _RunnerZHandoffemINaruszeniami())
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "ile kosztuje?", persona="quote")

        assert wyslane == [tura.KOMUNIKAT_HANDOFF]
        assert len(slady["notatki"]) == 1
        assert len(slady["toggle"]) == 1

    def test_handoff_z_narzedzia_i_nieudane_podsumowanie_nie_daja_ciszy(self, monkeypatch):
        """Sonda rerecenzji (przypadek C): handoff z narzędzia, podsumowanie nie
        dotarło do Chatwoota, model nic nie napisał."""
        conv_id = 96142
        slady = self._slady_handoffu(monkeypatch)
        monkeypatch.setattr(stan, "podsumowanie_nieudane", lambda: True)

        class _RunnerZHandoffemBezOdpowiedzi:
            def run_sync(self, agent, tresc, session=None, max_turns=None):
                stan.handoff("nie udalo sie wyslac podsumowania")
                return types.SimpleNamespace(final_output="")

        monkeypatch.setattr(tura, "Runner", _RunnerZHandoffemBezOdpowiedzi())
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "tak", persona="quote")

        assert wyslane == [tura.KOMUNIKAT_HANDOFF]
        assert len(slady["notatki"]) == 1
        assert len(slady["toggle"]) == 1

    def test_komunikat_po_handoffie_z_narzedzia_idzie_przez_profil_kanalu(self, monkeypatch):
        """Komunikat wysyłany z tej ścieżki nadal podlega profilowi kanału —
        sklejony w Pythonie tekst nie może omijać caps-ów Allegro/OLX."""
        conv_id = 96143
        self._slady_handoffu(monkeypatch)
        uzyte_persony = []
        prawdziwa = tura.wysylka.przygotuj
        monkeypatch.setattr(tura.wysylka, "przygotuj",
                            lambda tekst, persona: uzyte_persony.append(persona) or
                            prawdziwa(tekst, persona))

        class _RunnerZHandoffemINaruszeniami:
            odpowiedzi = ["Cena to 999,00 zl", "Nadal 999,00 zl"]

            def run_sync(self, agent, tresc, session=None, max_turns=None):
                stan.handoff("klient prosi o czlowieka")
                return types.SimpleNamespace(final_output=self.odpowiedzi.pop(0))

        monkeypatch.setattr(tura, "Runner", _RunnerZHandoffemINaruszeniami())
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "ile kosztuje?", persona="allegro")

        assert uzyte_persony == ["allegro"]


class TestN6KontaktNaStarcieTury:
    """N6: dane z formularza wstepnego widgetu (e-mail, nazwa) leza na kontakcie
    rozmowy w Chatwoocie, a bot i tak prosil o nie po wycenie. Tura ma je
    wczytac ZANIM zbuduje agentow — inaczej regula KONTAKT w prompcie mowilaby
    o sekcji, ktorej nie ma."""

    def _kontakt(self, monkeypatch, dane):
        import core.chatwoot as core_cw
        monkeypatch.setattr(core_cw, "cw_contact_full", lambda cid: dane)

    def _agent_wyceny(self, router):
        for h in router.handoffs:
            if getattr(h, "name", "") == "Wycena":
                return h
        raise AssertionError("router nie ma agenta Wyceny")

    def test_agent_wyceny_dostaje_email_z_kontaktu_rozmowy(self, monkeypatch):
        conv_id = 96209001
        self._kontakt(monkeypatch, {"name": "TEST S5", "identifier": "",
                                    "email": "test-s5@example.invalid", "phone": ""})
        fake = _FalszywyRunner(["Juz licze."])
        monkeypatch.setattr(tura, "Runner", fake)
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "Poprosze o wycene blatu", persona="quote")

        agent = self._agent_wyceny(fake.agenci[0])
        assert "test-s5@example.invalid" in agent.instructions
        assert "TEST S5" in agent.instructions

    def test_odczyt_dotyczy_tej_rozmowy(self, monkeypatch):
        conv_id = 96209002
        przekazane = []
        import core.chatwoot as core_cw
        monkeypatch.setattr(core_cw, "cw_contact_full",
                            lambda cid: przekazane.append(cid) or {})
        monkeypatch.setattr(tura, "Runner", _FalszywyRunner(["ok"]))
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "cokolwiek", persona="quote")

        assert przekazane == [conv_id]

    def test_pusty_kontakt_nie_dokleja_sekcji(self, monkeypatch):
        # OLX i Allegro: brak formularza wstepnego, wiec kontakt bywa pusty
        # i pytanie o e-mail jest tam uzasadnione.
        conv_id = 96209003
        self._kontakt(monkeypatch, {"name": "", "identifier": "", "email": "", "phone": ""})
        fake = _FalszywyRunner(["ok"])
        monkeypatch.setattr(tura, "Runner", fake)
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "cokolwiek", persona="quote_olx")

        # Kotwica to naglowek SEKCJI: sama fraza „DANE KLIENTA" wystepuje takze
        # w regule KONTAKT, ktora stoi w prompcie zawsze.
        assert "DANE KLIENTA znane systemowi" not in (
            self._agent_wyceny(fake.agenci[0]).instructions)

    def test_gdy_bot_ma_milczec_kontakt_nie_jest_odpytywany(self, monkeypatch):
        # Bramka ciszy konczy ture PRZED wolaniem modelu — nie ma powodu placic
        # przy okazji za odczyt kontaktu z Chatwoota.
        conv_id = 96209004
        przekazane = []
        import core.chatwoot as core_cw
        monkeypatch.setattr(core_cw, "cw_contact_full",
                            lambda cid: przekazane.append(cid) or {})
        monkeypatch.setattr(stan, "wolno_prowadzic_rozmowe", lambda cid: False)
        monkeypatch.setattr(tura, "Runner", _FalszywyRunner(["ok"]))
        _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "cokolwiek", persona="quote")

        assert przekazane == []

    def test_blad_odczytu_kontaktu_nie_przerywa_tury(self, monkeypatch):
        # Klient ma dostac odpowiedz nawet wtedy, gdy odczyt kontaktu padnie —
        # bez danych bot poprosi o e-mail, jak dotad.
        conv_id = 96209005

        def _wybucha(cid):
            raise RuntimeError("Chatwoot padl")

        import core.chatwoot as core_cw
        monkeypatch.setattr(core_cw, "cw_contact_full", _wybucha)
        monkeypatch.setattr(tura, "Runner", _FalszywyRunner(["Dzien dobry."]))
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "cokolwiek", persona="quote")

        assert wyslane == ["Dzien dobry."]
