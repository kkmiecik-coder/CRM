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

from bots_pro import agenci, stan, tura

stan.init_pro()


@pytest.fixture(autouse=True)
def _domyslnie_wolno_prowadzic_rozmowe(monkeypatch):
    """Wiekszosc testow w tym pliku sprawdza logike SAMEJ tury (guardrail, wysylka,
    routing) — nie bramki ciszy po handoffie (patrz TestBramkaCiszyPoHandoffie nizej),
    ktora normalnie odpytuje Chatwoota siecia. Domyslnie pozwalamy botowi mowic (tak
    jak w prawdziwej nowej rozmowie w statusie pending), zeby zaden z pozostalych
    testow nie musial tego osobno mockowac. Testy bramki nadpisuja to jawnie."""
    monkeypatch.setattr(stan, "wolno_prowadzic_rozmowe", lambda conv_id: True)


# ---------------------------------------------------------------------------
# Atrapa CAŁEGO Runner.run_sync — dla testów logiki tury (retry guardraila,
# brak podwójnej wysyłki), gdzie nie zależy nam na prawdziwym routingu SDK.
# ---------------------------------------------------------------------------
class _FalszywyRunner:
    """Podmienia `agents.Runner` widziany przez `bots_pro.tura` — kolejne wywołania
    `run_sync` zwracają kolejne zaplanowane odpowiedzi, po kolei.

    `rejestruj_kwoty` (opcjonalnie, lista list, po jednej na wywołanie) symuluje
    efekt uboczny narzędzia `policz_wycene` (`stan.zapamietaj_kwoty`) - w prawdziwym
    przebiegu kwoty trafiają do rejestru W TRAKCIE Runner.run_sync, PO tym, jak
    `tura.uruchom` już wyzerowało rejestr przez `stan.ustaw_kontekst`. Podanie kwot
    do konstruktora _FalszywyRunner z GÓRY (przed wywołaniem uruchom) nic by nie
    dało — rejestr i tak zostałby wyczyszczony na starcie tury."""

    def __init__(self, odpowiedzi, rejestruj_kwoty=None):
        self._odpowiedzi = list(odpowiedzi)
        self._rejestruj_kwoty = list(rejestruj_kwoty or [])
        self.wywolania = []   # tresc kazdego wywolania, w kolejnosci

    def run_sync(self, agent, tresc, session=None, max_turns=None):
        self.wywolania.append(tresc)
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

        # Zadna wersja bledej ceny NIE trafila do klienta.
        assert wyslane == []
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

        assert wyslane == []      # nic bledego (i nic pustego) nie poszlo do klienta
        assert len(powody) == 1   # ale klient dostal czlowieka - nie zostal bez odpowiedzi

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

    def test_bez_wyslania_podsumowania_zwykla_odpowiedz_nadal_idzie_do_klienta(self, monkeypatch):
        # Kontrola negatywna: bramka W3 nie ma blokowac zwyklych odpowiedzi, w
        # ktorych podsumowanie.wyslij() w ogole nie bylo wolane w tej turze.
        conv_id = 96113
        fake_runner = _FalszywyRunner(["Dziekuje, wracam z odpowiedzia."])
        monkeypatch.setattr(tura, "Runner", fake_runner)
        wyslane = _wyslane_przechwytywacz(monkeypatch)

        tura.uruchom(conv_id, "inbox1", "test", persona="quote")

        assert wyslane == ["Dziekuje, wracam z odpowiedzia."]


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
    agenta wyspecjalizowanego po liczbie narzedzi (Wycena=11, Wiedza=2)."""

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

        if handoffs:
            tekst = _ostatnia_wiadomosc_uzytkownika(input).lower()
            if any(s in tekst for s in ("kosztowac", "cena", "koszt", "ile to")):
                return _wywolanie_transferu("Wycena", licznik)
            return _wywolanie_transferu("Wiedza", licznik)

        if len(tools) == 11:
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

        # Router zostal wywolany OD NOWA w KAZDEJ turze (dwa wywolania z handoffs != []).
        wywolania_routera = [w for w in fake_model.wywolania if w["n_handoffs"]]
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
        # (11 narzedzi z NARZEDZIA_WYCENY) - mimo ze poprzednia tura skonczyla
        # sie na Wiedzy (2 narzedzia), ktora nie ma wlasnego handoffu do Wyceny.
        assert fake_model.wywolania[-1]["n_tools"] == 11
