# -*- coding: utf-8 -*-
"""
Testy silnika odtwarzania (`e2e.replay.odtworz`) — wymagaja zainstalowanego
`agents` SDK (Runner/Agent/Model), dlatego caly plik jest POMIJANY bez niego
(ten sam wzorzec co tests/test_pro_tura.py — importy sa na poziomie modulu).

NAJWAZNIEJSZY temat w tym pliku (TestPrzechwycenieWysylki i dalsze klasy):
harness NIE MOZE pisac do produkcji — ani do Chatwoota, ani do CRM. Runda
poprawek 1 (przeglad zadania) ujawnila DWA niezalezne bledy tej samej klasy:

  K1 — `bots_pro/podsumowanie.py` ma WLASNY, OSOBNY
       `from core.chatwoot import cw_agent_reply` (rozny od tego w tura.py) —
       pierwsza wersja tego harnessu latala TYLKO `tura.cw_agent_reply`, wiec
       KAZDA rozmowa, w ktorej model wolal narzedzie `wyslij_podsumowanie`,
       wysylala PRAWDZIWA wiadomosc do Chatwoota, a jej tresc nawet nie
       trafiala do zmierzonych `odpowiedzi` (harness mierzyl cisze, ktorej
       nie bylo).
  K2 — `bots_pro/narzedzia.py::znajdz_klienta`/`zapisz_wycene`/`popraw_wycene`
       wola `bots.crm_calc.find_or_create_client`/`.create_quote`/
       `.update_quote` — funkcje PISZACE do produkcyjnego CRM. Bez podmiany
       KAZDA rozmowa dochodzaca do etapu kontaktu/zapisu zakladalaby
       realnego klienta pod `client_number="chat-<900000+id>"`.
  K3 — pierwsza wersja testu ponizej podmieniala `core.chatwoot.cw_agent_reply`
       (atrybut MODULU ZRODLOWEGO) — ktorego, jak wyzej, ani tura.py, ani
       podsumowanie.py NIGDY nie wywoluja (obie maja WLASNE, zwiazane przy
       imporcie referencje). Ten test byl wiec bezzebny: przechodzil
       NIEZALEZNIE od tego, czy `replay.odtworz` faktycznie cokolwiek
       przechwytywal.

`cw_agent_reply`/`cw_bot_handoff`/`crm_calc._send` NIGDY nie rzucaja same z
siebie — lapia wyjatki (w tym z `requests.post`) i po cichu zwracaja
False/{"ok": False} + log. To ma DWIE konsekwencje dla testow:
  (a) podmiana WLASCIWEGO atrybutu (tura.cw_agent_reply,
      podsumowanie.cw_agent_reply, crm_calc.find_or_create_client/...) NA
      ATRAPE, KTORA RZUCA, dziala poprawnie — nie ma miedzy moja atrapa a
      wywolujacym kodem zadnego try/except, bo to WLASNIE ta funkcja zostala
      podmieniona w calosci;
  (b) podmiana `requests.post` samego w sobie na atrape, ktora RZUCA, NIE
      dzialaby jako dowod nieszczelnosci — realna funkcja i tak zlapalaby
      wyjatek WEWNATRZ i zwrocila False, przez co pytest nigdy by go nie
      zobaczyl. Dlatego test transportowy nizej (TestZadneWywolanieSieciowe)
      uzywa REJESTRATORA (zapisuje wywolania, nie rzuca), nie atrapy rzucajacej."""
import types

import pytest

pytest.importorskip("agents")  # patrz naglowek modulu

from bots_pro import podsumowanie, potwierdzenia, stan, tura
from bots import crm_calc
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
    """Krytyczny wymog zadania: harness nie moze pisac do produkcji.

    `test_zwykla_odpowiedz_bota_trafia_do_wyniku_przez_wlasciwa_podmiane`
    nizej NIE opiera sie na podmianie `core.chatwoot.cw_agent_reply` (K3 —
    to bylby ten sam bezzebny test, ktory ten harness juz raz mial) — dowodzi
    przechwycenia POZYTYWNIE: tekst z atrapy Runnera pojawia sie w
    `wynik['odpowiedzi']`, co jest mozliwe WYLACZNIE jesli `tura.cw_agent_reply`
    (jedyne miejsce, ktore `tura.uruchom` faktycznie wywoluje) zostalo
    poprawnie podmienione. Prawdziwie NIEZALEZNY, transportowy dowod braku
    wycieku (K1+K2+K3 naraz, bez zalozenia KTOREGO atrybutu pilnowac) jest w
    TestZadneWywolanieSieciowe nizej."""

    def test_zwykla_odpowiedz_bota_trafia_do_wyniku_przez_wlasciwa_podmiane(self, monkeypatch):
        monkeypatch.setattr(
            tura, "Runner",
            _FalszywyRunnerRoutingu(["Dziekuje, potrzebuje jeszcze wymiarow."]))

        rozmowa = {"id": 501, "wiadomosci": [("KLIENT", "poprosze wycene blatu")]}
        wynik = replay.odtworz(rozmowa)

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


class TestZadneWywolanieSieciowe:
    """Test transportowy — K3, sztandarowy dowod braku wycieku. Zamiast ufac
    KTOREMU atrybutowi (co jest latwo pomylic — K1 to WLASNIE taka pomylka:
    `podsumowanie.py` mial WLASNA, niezalezna kopie tego samego importu, ktora
    pierwsza wersja tego harnessu przeoczyla), patchuje sie WARSTWE
    TRANSPORTOWA (`requests.post`/`.request`) — przez nia przechodzi KAZDE
    wywolanie sieciowe w `core.chatwoot.*`/`bots.crm_calc.*`, niezaleznie od
    tego, jak zostalo zaimportowane. REJESTRUJE wywolania zamiast rzucac
    wyjatek — `cw_agent_reply`/`cw_bot_handoff`/`crm_calc._send` lapia
    wyjatki z `requests` WEWNATRZ SIEBIE (nigdy nie rzucaja same z siebie,
    patrz ich docstringi), wiec rzucajaca atrapa na tym poziomie zostalaby po
    cichu polkniena i test 'przeszedlby' NAWET PRZY REALNYM WYCIEKU."""

    def test_pelny_scenariusz_podsumowanie_potwierdzenie_zapis_klienta_nie_dotyka_sieci(
            self, monkeypatch):
        import requests

        wywolania_sieciowe = []

        def _zanotuj(*args, **kwargs):
            wywolania_sieciowe.append((args, kwargs))
            return types.SimpleNamespace(
                status_code=200, text="{}", ok=True, json=lambda: {})

        monkeypatch.setattr(requests, "post", _zanotuj)
        monkeypatch.setattr(requests, "request", _zanotuj)
        monkeypatch.setattr(requests, "put", _zanotuj)
        monkeypatch.setattr(requests, "get", _zanotuj)

        # get_options/calculate MAJA zostac PRAWDZIWE w produkcyjnym replayu
        # (I1 — cena wylacznie z kalkulatora) — ale W TYM TESCIE, ktory
        # sprawdza WYLACZNIE brak wycieku z narzedzi PISZACYCH (K1/K2), sa
        # stubowane lokalnie, zeby test nie zalezal od realnego ksztaltu
        # /api/bot/calculate. Realny kalkulator (bez stubu) jest cwiczony w
        # TestOdtworzTrasaZPrawdziwymRouterem (tam za to caly model jest
        # atrapa) — dwie ODREBNE odpowiedzialnosci, dwa odrebne testy.
        monkeypatch.setattr(crm_calc, "get_options", lambda force=False: {})
        monkeypatch.setattr(crm_calc, "calculate", lambda pozycje, options: {
            "ok": True, "totals": {"total_brutto": 1230.0}, "products": [{}]})

        class _RunnerWolajacyNarzedzia:
            """Symuluje EFEKT UBOCZNY narzedzi SDK, ktore model wolalby w
            prawdziwej rozmowie (wyslij_podsumowanie -> potwierdz ->
            znajdz_klienta -> zapisz_wycene) — bezposrednie wywolanie funkcji
            pod spodem narzedzi, bez prawdziwego modelu (jak
            `_RunnerZPodsumowaniemWTrakcie` w test_pro_tura.py)."""

            def __init__(self):
                self.krok = 0

            def run_sync(self, agent, tresc, session=None, max_turns=None):
                self.krok += 1
                if self.krok == 1:
                    stan.zapisz_pozycje("1", produkt="blat", dlugosc_cm=200,
                                        szerokosc_cm=60, grubosc_cm=4, ilosc=1,
                                        selected_variant="dab-lity-ab")
                    wynik_wyslania = podsumowanie.wyslij()
                    assert wynik_wyslania["ok"] is True
                    return types.SimpleNamespace(
                        final_output="", last_agent=types.SimpleNamespace(name="Wycena"),
                        context_wrapper=types.SimpleNamespace(usage=None))
                # krok 2: klient (druga wiadomosc w rozmowie, patrz nizej)
                # potwierdza — potwierdz() czyta stan.ostatnia_wiadomosc_klienta()
                # (W1), zakladajacy klient + zapisana wycena to K2.
                wynik_potw = potwierdzenia.potwierdz("zgadzam sie na wszystko")
                assert wynik_potw["ok"] is True
                wynik_klienta = crm_calc.find_or_create_client(
                    "test@example.com", None, "Test Klient", client_number="chat-test")
                assert wynik_klienta["ok"] is True
                wynik_wyceny = crm_calc.create_quote(
                    stan.pozycje(), {}, wynik_klienta["client"]["id"])
                assert wynik_wyceny["ok"] is True
                return types.SimpleNamespace(
                    final_output="Wycena zapisana: %s" % wynik_wyceny["edit_uuid"],
                    last_agent=types.SimpleNamespace(name="Wycena"),
                    context_wrapper=types.SimpleNamespace(usage=None))

        monkeypatch.setattr(tura, "Runner", _RunnerWolajacyNarzedzia())

        rozmowa = {"id": 901, "wiadomosci": [
            ("KLIENT", "poprosze wycene blatu dab lity A/B 200x60x4, 1 sztuka"),
            ("KLIENT", "tak, zgadzam sie na wszystko"),
        ]}
        wynik = replay.odtworz(rozmowa)

        # Pozytywny dowod, ze scenariusz FAKTYCZNIE przeszedl przez wszystkie
        # cztery narzedzia (bez tego test moglby "przechodzic" tylko dlatego,
        # ze nic sie nie wydarzylo).
        assert wynik["crm_zapisy_przechwycone"] == 2  # find_or_create_client + create_quote
        assert any("Podsumowanie do potwierdzenia" in o for o in wynik["odpowiedzi"])
        assert any("Wycena zapisana" in o for o in wynik["odpowiedzi"])

        # I WLASCIWY dowod tego testu: ZERO wywolan warstwy transportowej —
        # ani do Chatwoota (wyslanie/handoff/historia), ani do CRM (klient/
        # wycena). get_options/calculate tez nie posiegnely po siec, bo byly
        # stubowane lokalnie (patrz wyzej) — gdyby nie byly, i tak liczylyby
        # sie jako "measuring", nie "writing", wiec i tak NIE sa przedmiotem
        # tego konkretnego testu (patrz TestOdtworzTrasaZPrawdziwymRouterem).
        assert wywolania_sieciowe == []


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

        assert kryteria.koszt_rozmowy(wynik["uzycia"]) == 100 * 1.0 + 20 * 4.0

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
        # to suma obu (patrz kryteria.koszt_rozmowy): input 8+10=18, output 2+5=7.
        assert kryteria.koszt_rozmowy(wynik["uzycia"]) == 18 * 1.0 + 7 * 4.0


class TestOstatniaWiadomoscKlientaZTranskryptu:
    """Runda poprawek 1, W1: `potwierdzenia.potwierdz` czyta
    `stan.ostatnia_wiadomosc_klienta()`, ktora normalnie odpytuje PRAWDZIWY
    Chatwoot (core.chatwoot.cw_messages) o historie rozmowy, ktorej w
    replayu nie ma — bez podmiany KAZDE potwierdzenie w replayu konczyloby
    sie `CYTAT_SPOZA_WIADOMOSCI`, wiec I2 nigdy nie domykaloby sie w
    replayu, a `zawiera_link`/`ma_wyjscie` degenerowaloby sie do samego
    handoffu."""

    def test_zwraca_biezaca_wiadomosc_klienta_nie_puste(self, monkeypatch):
        przechwycone = []

        def _run_sync(agent, tresc, session=None, max_turns=None):
            przechwycone.append(stan.ostatnia_wiadomosc_klienta())
            return types.SimpleNamespace(
                final_output="ok", last_agent=types.SimpleNamespace(name="Wycena"),
                context_wrapper=types.SimpleNamespace(usage=None))

        monkeypatch.setattr(tura, "Runner", types.SimpleNamespace(run_sync=_run_sync))
        rozmowa = {"id": 801, "wiadomosci": [
            ("KLIENT", "pierwsza wiadomosc"), ("KLIENT", "druga wiadomosc")]}

        replay.odtworz(rozmowa)

        assert przechwycone == ["pierwsza wiadomosc", "druga wiadomosc"]

    def test_prawdziwy_cw_messages_nigdy_nie_jest_wolany(self, monkeypatch):
        import core.chatwoot as cw

        def _wybuchnij(*a, **kw):
            raise AssertionError(
                "replay wywolal PRAWDZIWY cw_messages — odpytal Chatwoot o "
                "historie nieistniejacej rozmowy")

        monkeypatch.setattr(cw, "cw_messages", _wybuchnij)

        def _run_sync(agent, tresc, session=None, max_turns=None):
            stan.ostatnia_wiadomosc_klienta()  # symuluje odczyt wewnatrz potwierdz()
            return types.SimpleNamespace(
                final_output="ok", last_agent=None, context_wrapper=None)

        monkeypatch.setattr(tura, "Runner", types.SimpleNamespace(run_sync=_run_sync))
        rozmowa = {"id": 802, "wiadomosci": [("KLIENT", "cokolwiek")]}

        replay.odtworz(rozmowa)  # brak wyjatku == cw_messages nie zostal wolany

    def test_potwierdzenie_i2_faktycznie_dziala_w_replayu(self, monkeypatch):
        # Bez W1 KAZDE potwierdzenie w replayu konczyloby sie
        # CYTAT_SPOZA_WIADOMOSCI — ten test dowodzi, ze I2 NAPRAWDE domyka
        # sie w replayu (nie tylko ze funkcja zwraca cos niepustego).
        #
        # Seedowanie pozycji/podpisu MUSI sie stac WEWNATRZ run_sync (po
        # tym, jak odtworz() juz wywolalo stan.ustaw_kontekst dla TEGO
        # conv_id) — poza nim `stan.zapisz_pozycje` odmowi zapisu (Task 8,
        # K3: `_wymagany_conv_id` rzuca bez ustawionego kontekstu).
        from bots_pro.potwierdzenia import podpis

        def _run_sync(agent, tresc, session=None, max_turns=None):
            stan.zapisz_pozycje("1", produkt="blat", dlugosc_cm=200, szerokosc_cm=60,
                                grubosc_cm=4, ilosc=1, selected_variant="dab-lity-ab")
            stan.zapisz_stan(oczekiwany_podpis=podpis(stan.pozycje()))
            wynik = potwierdzenia.potwierdz("tak, potwierdzam")
            return types.SimpleNamespace(
                final_output=("ok" if wynik["ok"] else wynik["error"]),
                last_agent=None, context_wrapper=None)

        monkeypatch.setattr(tura, "Runner", types.SimpleNamespace(run_sync=_run_sync))
        rozmowa = {"id": 803, "wiadomosci": [("KLIENT", "tak, potwierdzam")]}

        wynik = replay.odtworz(rozmowa)

        assert wynik["odpowiedzi"] == ["ok"]  # NIE "CYTAT_SPOZA_WIADOMOSCI"


class TestPersonaKanalu:
    """Runda poprawek 1, W3: korpus audytu obejmuje OLX/Allegro/Messenger/
    live-chat — `bots_pro.wysylka.przygotuj` egzekwuje profil kanalu (np.
    `links=False` na Allegro), wiec odtwarzanie rozmowy z Allegro domyslna
    persona "pro" mierzyloby "ma link" tam, gdzie z definicji nie ma prawa
    wystapic."""

    def test_domyslna_persona_to_pro(self, monkeypatch):
        przechwycone = []

        def _run_sync(agent, tresc, session=None, max_turns=None):
            przechwycone.append(stan.persona())
            return types.SimpleNamespace(
                final_output="odp", last_agent=None, context_wrapper=None)

        monkeypatch.setattr(tura, "Runner", types.SimpleNamespace(run_sync=_run_sync))
        replay.odtworz({"id": 811, "wiadomosci": [("KLIENT", "test")]})

        assert przechwycone == ["pro"]

    def test_persona_przekazana_jawnie_trafia_do_stanu(self, monkeypatch):
        przechwycone = []

        def _run_sync(agent, tresc, session=None, max_turns=None):
            przechwycone.append(stan.persona())
            return types.SimpleNamespace(
                final_output="odp", last_agent=None, context_wrapper=None)

        monkeypatch.setattr(tura, "Runner", types.SimpleNamespace(run_sync=_run_sync))
        replay.odtworz({"id": 812, "wiadomosci": [("KLIENT", "test")]}, persona="allegro")

        assert przechwycone == ["allegro"]

    def test_link_jest_wycinany_na_allegro_ale_nie_na_pro(self, monkeypatch):
        tekst = "Szczegoly wyceny: https://crm.woodpower.pl/quotes/c/XYZ"
        monkeypatch.setattr(tura, "Runner", _FalszywyRunnerRoutingu([tekst]))
        wynik_pro = replay.odtworz(
            {"id": 813, "wiadomosci": [("KLIENT", "test")]}, persona="pro")
        assert "https://" in wynik_pro["odpowiedzi"][0]

        monkeypatch.setattr(tura, "Runner", _FalszywyRunnerRoutingu([tekst]))
        wynik_allegro = replay.odtworz(
            {"id": 814, "wiadomosci": [("KLIENT", "test")]}, persona="allegro")
        assert "https://" not in wynik_allegro["odpowiedzi"][0]

    def test_nieznana_persona_odmawia_zamiast_cicho_uzyc_domyslnych_caps(self):
        # "quote_olx"/"quote_allegro" ISTNIEJA w bots/channel_caps.py, ale
        # naleza do STAREGO silnika — Pro nigdy ich nie produkuje (patrz
        # quote_worker._PERSONY_SILNIKA_PRO). Cichy fallback na DEFAULT_CAPS
        # bylby dokladnie tym wyciekiem linkow na Allegro, przed ktorym
        # broni sie caly bots_pro.wysylka.
        with pytest.raises(ValueError):
            replay.odtworz({"id": 815, "wiadomosci": [("KLIENT", "test")]},
                           persona="quote_allegro")


class TestGlownyCliOdpornoscIWyjscieJson:
    """Runda poprawek 1, W5: jedna rozmowa z bledem (np. przejsciowy
    RateLimitError) nie ma prawa ukrasc wynikow WSZYSTKICH juz odtworzonych
    rozmow — i porownanie dwoch przebiegow nie ma wymagac diffowania
    wydruku terminala."""

    def test_wyjatek_w_jednej_rozmowie_nie_przerywa_reszty(self, monkeypatch, tmp_path):
        plik = tmp_path / "shard.txt"
        plik.write_text(
            "ROZMOWA #1\n[08:00] KLIENT: pierwsza\n"
            "ROZMOWA #2\n[08:00] KLIENT: druga\n"
            "ROZMOWA #3\n[08:00] KLIENT: trzecia\n",
            encoding="utf-8")

        def _odtworz_z_wyjatkiem_na_drugiej(rozmowa, persona="pro"):
            if rozmowa["id"] == 2:
                raise RuntimeError("symulowany przejsciowy blad dostawcy modelu")
            return {"odpowiedzi": ["odp-%s" % rozmowa["id"]], "handoff": False,
                    "trasa": [], "uzycia": [], "czasy_tur": [0.1],
                    "kwoty_niezgodne": 0, "crm_zapisy_przechwycone": 0}

        monkeypatch.setattr(replay, "odtworz", _odtworz_z_wyjatkiem_na_drugiej)

        # main() nie ma wywalic wyjatku mimo bledu w rozmowie #2.
        replay.main([str(plik)])

    def test_out_zapisuje_json_z_wynikami_i_bledami(self, monkeypatch, tmp_path):
        plik = tmp_path / "shard.txt"
        plik.write_text(
            "ROZMOWA #1\n[08:00] KLIENT: pierwsza\n"
            "ROZMOWA #2\n[08:00] KLIENT: druga\n",
            encoding="utf-8")
        wyjscie = tmp_path / "wyniki.json"

        def _odtworz_z_wyjatkiem_na_drugiej(rozmowa, persona="pro"):
            if rozmowa["id"] == 2:
                raise RuntimeError("symulowany blad")
            return {"odpowiedzi": ["odp"], "handoff": True, "trasa": ["Wycena"],
                    "uzycia": [], "czasy_tur": [0.1], "kwoty_niezgodne": 0,
                    "crm_zapisy_przechwycone": 0}

        monkeypatch.setattr(replay, "odtworz", _odtworz_z_wyjatkiem_na_drugiej)

        replay.main([str(plik), "--out", str(wyjscie)])

        import json
        dane = json.loads(wyjscie.read_text(encoding="utf-8"))
        assert len(dane["wyniki"]) == 1
        assert dane["wyniki"][0]["id"] == 1
        assert len(dane["bledy"]) == 1
        assert dane["bledy"][0]["id"] == 2

    def test_flaga_persona_dociera_do_odtworz(self, monkeypatch, tmp_path):
        plik = tmp_path / "shard.txt"
        plik.write_text("ROZMOWA #1\n[08:00] KLIENT: test\n", encoding="utf-8")

        przekazane_persony = []

        def _fake_odtworz(rozmowa, persona="pro"):
            przekazane_persony.append(persona)
            return {"odpowiedzi": [], "handoff": False, "trasa": [], "uzycia": [],
                    "czasy_tur": [], "kwoty_niezgodne": 0, "crm_zapisy_przechwycone": 0}

        monkeypatch.setattr(replay, "odtworz", _fake_odtworz)

        replay.main([str(plik), "--persona", "olx"])

        assert przekazane_persony == ["olx"]

    def test_bez_argumentow_wypisuje_uzycie_i_nie_wybucha(self, capsys):
        replay.main([])
        wyjscie = capsys.readouterr().out
        assert "Uzycie" in wyjscie
