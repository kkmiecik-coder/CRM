# -*- coding: utf-8 -*-
"""
Telemetria lejka silnika Pro (T1).

Do tej zmiany `bots_pro/` nie emitował ANI JEDNEGO zdarzenia lejka: cały
baseline w tabeli `quote_events` pochodził ze starego silnika (`bots/quotebot.py`),
a stan Pro po czterech dniach produkcji trzeba było odtwarzać ręcznym dumpem
SQLite z kontenera. Bez tych zdarzeń nie da się zmierzyć, czy kolejne naprawy
zadziałały, ani porównać obu silników w tej samej jednostce.

Testy celowo czytają PRAWDZIWĄ tabelę `quote_events` (przez `core.db.db`), a nie
atrapę `log_event`: dowodzą wtedy całej ścieżki — że zdarzenie naprawdę wpada do
tej samej tabeli i z tą samą nazwą co zdarzenia starego silnika, bo to jedyne, co
czyni oba silniki porównywalnymi jednym zapytaniem SQL.

`bots_pro.narzedzia`/`bots_pro.tura` importują `agents` na poziomie modułu, więc
bez SDK cały ten plik ma zostać POMINIĘTY, a nie zerwać kolekcjonowanie testów
(ten sam wzorzec, co w test_pro_narzedzia.py / test_pro_tura.py).
"""
import asyncio
import io
import json
import os
import re
import sys
import types

import pytest

pytest.importorskip("agents")  # patrz docstring modulu

from agents.tool_context import ToolContext

from bots_pro import narzedzia, notatki, podsumowanie, potwierdzenia, stan, tura
from core.db import db, init_db

# `quote_events` powstaje w `core.db.init_db()` (schemat mostka), a nie w
# `stan.init_pro()` (tabele wyłącznie Pro) — w pełnym suite tabela istnieje,
# bo tworzą ją inne testy, ale ten plik ma przechodzić TAKŻE uruchomiony sam.
init_db()
stan.init_pro()


# ---------------------------------------------------------------------------
# Pomocnicze
# ---------------------------------------------------------------------------
def _zdarzenia(conv_id, event=None):
    """Zdarzenia lejka zapisane dla rozmowy, w kolejności zapisu.

    Zwracamy LISTĘ, nie zbiór ani licznik — istotą połowy tych testów jest
    „dokładnie raz", a to widać wyłącznie na liście z powtórzeniami."""
    polaczenie = db()
    try:
        if event:
            wiersze = polaczenie.execute(
                "SELECT event, meta FROM quote_events WHERE conv_id=? AND event=? ORDER BY id",
                (conv_id, event)).fetchall()
        else:
            wiersze = polaczenie.execute(
                "SELECT event, meta FROM quote_events WHERE conv_id=? ORDER BY id",
                (conv_id,)).fetchall()
    finally:
        polaczenie.close()
    return [(w["event"], json.loads(w["meta"]) if w["meta"] else None) for w in wiersze]


def _wolaj(tool, **kwargs):
    """Woła CIAŁO narzędzia SDK tak, jak zrobiłby to Runner — przez
    `on_invoke_tool`, z prawdziwym parsowaniem argumentów (wzorzec z
    test_pro_narzedzia.py)."""
    ctx = ToolContext(context=None, tool_name=tool.name, tool_call_id="test",
                      tool_arguments="{}")
    return asyncio.run(tool.on_invoke_tool(ctx, json.dumps(kwargs)))


def _pozycja(id="1"):
    return {"id": id, "produkt": "blat", "dlugosc": 180, "szerokosc": 60,
            "grubosc": 4, "ilosc": 1, "selected_variant": "dab-lity-ab",
            "gatunek": "Dąb", "technologia": "Lity", "klasa": "A/B",
            "finishing_id": 3, "edges": []}


def _atrapa_wysylki(monkeypatch):
    """Podmienia `bots_pro.wysylka` widziane przez `podsumowanie.wyslij()` —
    tekst ma zostać w CAŁOŚCI (jedna część), żeby test liczył zdarzenia, a nie
    profil kanału (wzorzec z test_pro_podsumowanie.py)."""
    from bots_pro import wysylka as prawdziwa_wysylka
    modul = types.ModuleType("bots_pro.wysylka")
    modul.przygotuj = lambda tekst, persona: [tekst]
    modul.wolno_linkowac = prawdziwa_wysylka.wolno_linkowac
    monkeypatch.setitem(sys.modules, "bots_pro.wysylka", modul)


# ---------------------------------------------------------------------------
# Zdarzenia narzędzi
# ---------------------------------------------------------------------------
class TestPriced:
    def _przygotuj(self, monkeypatch, conv_id, ok=True, pozycje=None):
        stan.ustaw_kontekst(conv_id)
        monkeypatch.setattr(stan, "pozycje", lambda: list(pozycje or [_pozycja()]))
        monkeypatch.setattr(narzedzia.crm_calc, "get_options", lambda: {})
        wynik = ({"ok": True, "totals": {"total_brutto": 1936.71}} if ok
                 else {"ok": False, "errors": [{"code": "X"}]})
        monkeypatch.setattr(narzedzia.crm_calc, "calculate", lambda p, o: wynik)

    def test_udana_wycena_emituje_priced_dokladnie_raz(self, monkeypatch):
        conv_id = 97101
        self._przygotuj(monkeypatch, conv_id)

        _wolaj(narzedzia.policz_wycene)

        assert _zdarzenia(conv_id, "priced") == [
            ("priced", {"kwota": 1936.71, "pozycje": 1})]

    def test_meta_niesie_liczbe_pozycji_ktore_weszly_do_rachunku(self, monkeypatch):
        """Pole, którego stary silnik NIE miał, i jedyny powód, dla którego
        w ogóle je dopisujemy: spór o zwinięcie listy 13 elementów do jednej
        rozstrzyga liczba pozycji W RACHUNKU, nie liczba wymieniona przez
        klienta w wiadomości."""
        conv_id = 97102
        self._przygotuj(monkeypatch, conv_id,
                        pozycje=[_pozycja("1"), _pozycja("2"), _pozycja("3")])

        _wolaj(narzedzia.policz_wycene)

        assert _zdarzenia(conv_id, "priced")[0][1]["pozycje"] == 3

    def test_nieudana_wycena_nie_emituje_priced(self, monkeypatch):
        # Kontrola negatywna: `priced` ma znaczyć „kalkulator oddał cenę".
        # Gdyby leciało też przy ok=False, lejek liczyłby awarie jako sukcesy.
        conv_id = 97103
        self._przygotuj(monkeypatch, conv_id, ok=False)

        _wolaj(narzedzia.policz_wycene)

        assert _zdarzenia(conv_id, "priced") == []


class TestShippingQuoted:
    def _przygotuj(self, monkeypatch, conv_id, wynik):
        stan.ustaw_kontekst(conv_id)
        monkeypatch.setattr(stan, "pozycje", lambda: [_pozycja()])
        monkeypatch.setattr(narzedzia.crm_calc, "shipping_quote",
                            lambda pozycje, kod: wynik)

    def test_udane_oszacowanie_emituje_shipping_quoted_raz(self, monkeypatch):
        conv_id = 97111
        self._przygotuj(monkeypatch, conv_id, {
            "ok": True, "carriers": 2, "carrier_name": "DPD",
            "shipping_netto": 100.0, "shipping_brutto": 123.0})

        _wolaj(narzedzia.policz_wysylke, kod_pocztowy="00-001")

        assert _zdarzenia(conv_id, "shipping_quoted") == [
            ("shipping_quoted", {"carrier": "DPD"})]

    def test_brak_kuriera_dla_gabarytu_nie_emituje_zdarzenia(self, monkeypatch):
        """`ok=True` z `carriers=0` NIE jest oszacowaniem wysyłki (patrz
        docstring narzędzia: to nie znaczy „gratis"). Ten sam warunek co
        w starym silniku — inaczej lejek pokazywałby wysyłkę policzoną tam,
        gdzie jej nie ma."""
        conv_id = 97112
        self._przygotuj(monkeypatch, conv_id, {"ok": True, "carriers": 0})

        _wolaj(narzedzia.policz_wysylke, kod_pocztowy="00-001")

        assert _zdarzenia(conv_id, "shipping_quoted") == []


class TestQuoteSaved:
    def _przygotuj(self, monkeypatch, conv_id):
        stan.ustaw_kontekst(conv_id)
        monkeypatch.setattr(stan, "pozycje", lambda: [_pozycja()])
        monkeypatch.setattr(narzedzia.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(potwierdzenia, "sprawdz_bramke", lambda: {"ok": True})

    def test_zapis_wyceny_emituje_quote_saved_raz_z_numerem(self, monkeypatch):
        conv_id = 97121
        self._przygotuj(monkeypatch, conv_id)
        monkeypatch.setattr(narzedzia.crm_calc, "create_quote",
                            lambda *a, **kw: {"ok": True, "quote_number": "W/2026/123",
                                              "edit_uuid": "uuid-1",
                                              "public_url": "https://x/1"})

        _wolaj(narzedzia.zapisz_wycene, client_id=7)

        assert _zdarzenia(conv_id, "quote_saved") == [
            ("quote_saved", {"nr": "W/2026/123"})]

    def test_nieudane_dopisanie_dostawy_nie_kasuje_quote_saved(self, monkeypatch):
        """Gałąź DOSTAWA_NIEDOPISANA oddaje `ok=False` MIMO wyceny zapisanej
        w CRM. Zdarzenie ma opisywać RZECZYWISTOŚĆ (wycena istnieje), inaczej
        telemetria gubiłaby dokładnie te rozmowy, w których coś poszło nie tak."""
        conv_id = 97122
        self._przygotuj(monkeypatch, conv_id)
        monkeypatch.setattr(stan, "dostawa",
                            lambda: {"kurier": "DPD", "netto": 100.0, "brutto": 123.0})
        monkeypatch.setattr(narzedzia.crm_calc, "create_quote",
                            lambda *a, **kw: {"ok": True, "quote_number": "W/2026/124",
                                              "edit_uuid": "uuid-2"})
        monkeypatch.setattr(narzedzia.crm_calc, "update_quote",
                            lambda *a, **kw: {"ok": False, "error": "BOOM"})
        monkeypatch.setattr(notatki, "wyslij_notatke", lambda cid, tekst, **k: True)
        monkeypatch.setattr("core.chatwoot.cw_bot_handoff", lambda cid, token=None: True)

        wynik = _wolaj(narzedzia.zapisz_wycene, client_id=7)

        assert wynik["error"] == "DOSTAWA_NIEDOPISANA"
        assert _zdarzenia(conv_id, "quote_saved") == [
            ("quote_saved", {"nr": "W/2026/124"})]

    def test_drugi_zapis_w_tej_samej_rozmowie_nie_dubluje_zdarzenia(self, monkeypatch):
        # Bramka WYCENA_JUZ_ZAPISANA (R1) jest jedynym, co pilnuje pojedynczości
        # tego zdarzenia — bez niej model mógłby zapisać wycenę dwa razy.
        conv_id = 97123
        self._przygotuj(monkeypatch, conv_id)
        monkeypatch.setattr(narzedzia.crm_calc, "create_quote",
                            lambda *a, **kw: {"ok": True, "quote_number": "W/2026/125",
                                              "edit_uuid": "uuid-3",
                                              "public_url": "https://x/3"})

        _wolaj(narzedzia.zapisz_wycene, client_id=7)
        _wolaj(narzedzia.zapisz_wycene, client_id=7)

        assert len(_zdarzenia(conv_id, "quote_saved")) == 1


class TestSummarySent:
    def test_wyslane_podsumowanie_emituje_summary_sent_z_liczba_pozycji(self, monkeypatch):
        conv_id = 97131
        stan.ustaw_kontekst(conv_id)
        _atrapa_wysylki(monkeypatch)
        monkeypatch.setattr(stan, "pozycje", lambda: [_pozycja("1"), _pozycja("2")])
        monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(podsumowanie.crm_calc, "calculate",
                            lambda p, o: {"ok": True, "totals": {"total_brutto": 500.0}})
        monkeypatch.setattr(podsumowanie, "cw_agent_reply",
                            lambda cid, tekst, token=None: True)

        assert podsumowanie.wyslij()["ok"] is True
        assert _zdarzenia(conv_id, "summary_sent") == [
            ("summary_sent", {"positions": 2})]

    def test_podsumowanie_ktore_nie_doszlo_nie_emituje_zdarzenia(self, monkeypatch):
        """U1: podpis potwierdzenia zapisuje się dopiero po UDANEJ wysyłce —
        telemetria trzyma się tej samej granicy. Zdarzenie ma znaczyć „klient
        to zobaczył", bo tak znaczy w starym silniku."""
        conv_id = 97132
        stan.ustaw_kontekst(conv_id)
        _atrapa_wysylki(monkeypatch)
        monkeypatch.setattr(stan, "pozycje", lambda: [_pozycja()])
        monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(podsumowanie.crm_calc, "calculate",
                            lambda p, o: {"ok": True, "totals": {"total_brutto": 500.0}})
        monkeypatch.setattr(podsumowanie, "cw_agent_reply",
                            lambda cid, tekst, token=None: False)

        assert podsumowanie.wyslij()["error"] == "PODSUMOWANIE_NIEWYSLANE"
        assert _zdarzenia(conv_id, "summary_sent") == []


class TestConfirmed:
    def _przygotuj(self, monkeypatch, conv_id, pozycje):
        stan.ustaw_kontekst(conv_id)
        monkeypatch.setattr(stan, "pozycje", lambda: list(pozycje))
        monkeypatch.setattr(stan, "dostawa", lambda: {})
        monkeypatch.setattr(stan, "ostatnia_wiadomosc_klienta",
                            lambda: "tak, zgadza się")

    def test_potwierdzenie_emituje_confirmed_raz(self, monkeypatch):
        conv_id = 97141
        pozycje = [_pozycja()]
        self._przygotuj(monkeypatch, conv_id, pozycje)
        stan.zapisz_stan(oczekiwany_podpis=potwierdzenia.podpis(pozycje, {}))

        assert potwierdzenia.potwierdz("tak, zgadza się")["ok"] is True
        assert _zdarzenia(conv_id, "confirmed") == [("confirmed", None)]

    def test_odrzucone_potwierdzenie_nie_emituje_confirmed(self, monkeypatch):
        """Inwariant I2: potwierdzenie jest przypięte do PODPISU TREŚCI, nie do
        faktu wywołania narzędzia — telemetria nie może twierdzić inaczej."""
        conv_id = 97142
        pozycje = [_pozycja()]
        self._przygotuj(monkeypatch, conv_id, pozycje)
        # Podpis z INNEJ grubości = dane zmieniły się od podsumowania.
        inne = [dict(_pozycja(), grubosc=6)]
        stan.zapisz_stan(oczekiwany_podpis=potwierdzenia.podpis(inne, {}))

        wynik = potwierdzenia.potwierdz("tak, zgadza się")

        assert wynik["error"] == "DANE_ZMIENIONE_OD_PODSUMOWANIA"
        assert _zdarzenia(conv_id, "confirmed") == []


# ---------------------------------------------------------------------------
# Zdarzenia tury
# ---------------------------------------------------------------------------
class _Runner:
    """Atrapa `agents.Runner` widzianego przez `bots_pro.tura` — opcjonalnie
    wykonuje efekt uboczny narzędzia (np. `stan.handoff`) przed oddaniem
    odpowiedzi modelu, tak jak zrobiłby to prawdziwy przebieg."""

    def __init__(self, odpowiedz="", efekt=None):
        self._odpowiedz = odpowiedz
        self._efekt = efekt
        self.wywolania = []

    def run_sync(self, agent, tresc, session=None, max_turns=None):
        self.wywolania.append(tresc)
        if self._efekt:
            self._efekt()
        return types.SimpleNamespace(final_output=self._odpowiedz)


@pytest.fixture
def tura_bez_sieci(monkeypatch):
    """Wspólna izolacja tury od Chatwoota: bramka ciszy przepuszcza, kontakt
    pusty, notatka i przełączenie statusu udane, wiadomości do klienta zbierane
    do listy. `stan.handoff` NIE jest podmieniony — to jego emisja i jego
    idempotencja są tu przedmiotem testów."""
    monkeypatch.setattr(stan, "wolno_prowadzic_rozmowe", lambda cid: True)
    import core.chatwoot as core_cw
    monkeypatch.setattr(core_cw, "cw_contact_full", lambda cid: {})
    monkeypatch.setattr(notatki, "cw_note", lambda cid, tekst, token=None: True)
    monkeypatch.setattr(core_cw, "cw_bot_handoff", lambda cid, token=None: True)
    wyslane = []
    monkeypatch.setattr(tura, "cw_agent_reply",
                        lambda cid, tekst, token=None: wyslane.append(tekst) or True)
    return wyslane


class TestHandoff:
    def test_handoff_z_narzedzia_emituje_zdarzenie_raz(self, monkeypatch, tura_bez_sieci):
        conv_id = 97201
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 100)
        monkeypatch.setattr(tura, "BOT_PRO_MAX_BEZ_POSTEPU", 0)
        monkeypatch.setattr(tura, "Runner", _Runner(
            odpowiedz="Przekazuję konsultantowi.",
            efekt=lambda: stan.handoff("klient prosi o czlowieka")))

        tura.uruchom(conv_id, "inbox1", "poproszę człowieka", persona="pro")

        assert _zdarzenia(conv_id, "handoff") == [
            ("handoff", {"powod": "klient prosi o czlowieka"})]

    def test_handoff_z_narzedzia_i_bezpiecznika_liczy_sie_RAZ(self, monkeypatch,
                                                              tura_bez_sieci):
        """Sedno zadania: `tura._oddaj_konsultantowi` woła `stan.handoff`, więc
        emisja w OBU tych miejscach dałaby dwa zdarzenia na jedno przekazanie
        rozmowy. Emitujemy wyłącznie w `stan.handoff`, ZA bramką N7
        (`handoff_w_turze`) — model oddaje rozmowę narzędziem i pisze
        pożegnanie, przez co tura nie zmienia stanu biznesowego i bezpiecznik
        braku postępu oddaje ją drugi raz. Rozmowa jest jedna, zdarzenie jedno."""
        conv_id = 97202
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 100)
        monkeypatch.setattr(tura, "BOT_PRO_MAX_BEZ_POSTEPU", 1)
        monkeypatch.setattr(tura, "Runner", _Runner(
            odpowiedz="Jasne, przekazuję Cię konsultantowi.",
            efekt=lambda: stan.handoff("klient prosi o czlowieka")))

        tura.uruchom(conv_id, "inbox1", "poproszę człowieka", persona="pro")

        assert _zdarzenia(conv_id, "handoff") == [
            ("handoff", {"powod": "klient prosi o czlowieka"})]

    def test_handoff_z_samego_bezpiecznika_tez_emituje_zdarzenie(self, monkeypatch,
                                                                 tura_bez_sieci):
        # Kontrola pozytywna dla drugiego wejścia: gdy model NIE wołał narzędzia,
        # jedynym źródłem handoffu jest bezpiecznik — i on też ma być widoczny.
        conv_id = 97203
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 100)
        monkeypatch.setattr(tura, "BOT_PRO_MAX_BEZ_POSTEPU", 1)
        monkeypatch.setattr(tura, "Runner", _Runner(odpowiedz="Nadal nie wiem."))

        tura.uruchom(conv_id, "inbox1", "hmm", persona="pro")

        zdarzenia = _zdarzenia(conv_id, "handoff")
        assert len(zdarzenia) == 1
        assert "brak postepu" in zdarzenia[0][1]["powod"]


class TestTurnLimit:
    def test_przekroczony_limit_tur_emituje_turn_limit_i_handoff_po_razie(
            self, monkeypatch, tura_bez_sieci):
        conv_id = 97211
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 1)
        monkeypatch.setattr(tura, "BOT_PRO_MAX_BEZ_POSTEPU", 0)
        monkeypatch.setattr(tura, "Runner", _Runner(odpowiedz="odp"))

        tura.uruchom(conv_id, "inbox1", "wiadomosc 1", persona="pro", message_id="m1")
        tura.uruchom(conv_id, "inbox1", "wiadomosc 2", persona="pro", message_id="m2")

        assert [e for e, _ in _zdarzenia(conv_id)] == ["turn_limit", "handoff"]

    def test_tury_w_ramach_limitu_nie_emituja_turn_limit(self, monkeypatch,
                                                         tura_bez_sieci):
        conv_id = 97212
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 5)
        monkeypatch.setattr(tura, "BOT_PRO_MAX_BEZ_POSTEPU", 0)
        monkeypatch.setattr(tura, "Runner", _Runner(odpowiedz="odp"))

        tura.uruchom(conv_id, "inbox1", "wiadomosc 1", persona="pro", message_id="m1")

        assert _zdarzenia(conv_id) == []


# ---------------------------------------------------------------------------
# Odporność
# ---------------------------------------------------------------------------
class TestAwariaTelemetriiNieWywracaTury:
    """`core.events.log_event` ma WŁASNY try/except i nigdy nie rzuca, więc
    świadomie NIE osłaniamy go po raz drugi w `bots_pro/`. Awarię symulujemy
    więc tam, gdzie ona naprawdę zachodzi — na zapisie do bazy — a nie
    podmieniając samo `log_event` na rzucające (taka atrapa testowałaby
    nieistniejącą warstwę osłony i wymuszałaby dopisanie jej na siedmiu
    ścieżkach)."""

    @pytest.fixture
    def baza_telemetrii_pada(self, monkeypatch):
        import core.events as events

        def _padnij():
            raise RuntimeError("quote_events niedostepne")

        monkeypatch.setattr(events, "db", _padnij)

    def test_tura_konczy_sie_normalnie_mimo_bledu_zapisu_zdarzenia(
            self, monkeypatch, tura_bez_sieci, baza_telemetrii_pada):
        conv_id = 97301
        monkeypatch.setattr(tura, "BOT_PRO_MAX_TURNS", 100)
        monkeypatch.setattr(tura, "BOT_PRO_MAX_BEZ_POSTEPU", 1)
        monkeypatch.setattr(tura, "Runner", _Runner(
            odpowiedz="Przekazuję konsultantowi.",
            efekt=lambda: stan.handoff("reklamacja")))

        tura.uruchom(conv_id, "inbox1", "reklamacja", persona="pro")

        # Klient dostał odpowiedź, rozmowa poszła do człowieka — mimo że
        # telemetria nie zapisała nic.
        assert tura_bez_sieci == ["Przekazuję konsultantowi."]
        assert _zdarzenia(conv_id) == []

    def test_narzedzia_dzialaja_mimo_bledu_zapisu_zdarzenia(
            self, monkeypatch, baza_telemetrii_pada):
        conv_id = 97302
        stan.ustaw_kontekst(conv_id)
        monkeypatch.setattr(stan, "pozycje", lambda: [_pozycja()])
        monkeypatch.setattr(narzedzia.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(narzedzia.crm_calc, "calculate",
                            lambda p, o: {"ok": True, "totals": {"total_brutto": 1936.71}})

        wynik = _wolaj(narzedzia.policz_wycene)

        assert wynik["totals"]["total_brutto"] == 1936.71
        assert _zdarzenia(conv_id) == []

    def test_inwariant_I1_dziala_mimo_bledu_zapisu_zdarzenia(
            self, monkeypatch, baza_telemetrii_pada):
        """Telemetria stoi OBOK rejestru kwot G1, nie na jego drodze: kwota
        z kalkulatora ma trafić do `pro_kwoty` niezależnie od tego, czy
        `quote_events` przyjęło zdarzenie."""
        conv_id = 97303
        stan.ustaw_kontekst(conv_id)
        monkeypatch.setattr(stan, "pozycje", lambda: [_pozycja()])
        monkeypatch.setattr(narzedzia.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(narzedzia.crm_calc, "calculate",
                            lambda p, o: {"ok": True, "totals": {"total_brutto": 1936.71}})

        _wolaj(narzedzia.policz_wycene)

        # `pro_kwoty.kwota` jest kolumną TEKSTOWĄ (znormalizowany zapis kwoty),
        # więc rejestr oddaje stringi — porównujemy tak, jak robi to G1.
        assert "1936.71" in stan.znane_kwoty()


class TestNazwyZgodneZeStarymSilnikiem:
    """Cała wartość tej zmiany polega na tym, że oba silniki piszą do JEDNEJ
    tabeli TYMI SAMYMI nazwami — inaczej porównanie Pro ze starym silnikiem
    wymaga tłumaczenia nazw i przestaje być jedną jednostką. Test czyta nazwy
    ze ŹRÓDŁA (kod starego silnika), a nie z drugiej listy literałów."""

    # Sciezki liczone od PLIKU TESTU, nie od cwd — ten test czyta zrodla, a
    # katalog uruchomienia pytesta nie jest w tym repo gwarantowany (blog_seo
    # wymaga wlasnego cwd, patrz CLAUDE.md).
    _KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _WZORZEC = r'log_event\([^,]+,\s*"([a-z_]+)"'

    def _nazwy(self, *sciezki):
        nazwy = set()
        for sciezka in sciezki:
            zrodlo = io.open(os.path.join(self._KORZEN, sciezka), encoding="utf-8").read()
            nazwy |= set(re.findall(self._WZORZEC, zrodlo))
        return nazwy

    def test_kazde_zdarzenie_pro_wystepuje_tez_w_starym_silniku(self):
        nazwy_stare = self._nazwy("bots/quotebot.py")
        nazwy_pro = self._nazwy("bots_pro/narzedzia.py", "bots_pro/podsumowanie.py",
                                "bots_pro/potwierdzenia.py", "bots_pro/stan.py",
                                "bots_pro/tura.py")

        assert nazwy_pro == {"priced", "summary_sent", "confirmed", "quote_saved",
                             "shipping_quoted", "handoff", "turn_limit"}
        assert nazwy_pro <= nazwy_stare


class TestLogZapisuPozycji:
    """Jedyny sposób, żeby na produkcji rozstrzygnąć, czy listę 13 elementów
    zwinęło JEDNO wywołanie modelu, czy TRZYNAŚCIE nadpisujących się zapisów
    (`BOT_PRO_TRACING=0`, a `narzedzia.py` nie loguje wywołań narzędzi wcale).
    Musi wejść PRZED naprawą wyścigu w `pro_dane`, żeby było z czym porównać."""

    def _log_przechwytywacz(self, monkeypatch):
        linie = []
        monkeypatch.setattr(stan, "log", lambda tekst: linie.append(tekst))
        return linie

    def test_zapis_pozycji_loguje_id_i_liczbe_pozycji_po_zapisie(self, monkeypatch):
        stan.ustaw_kontekst(97401)
        linie = self._log_przechwytywacz(monkeypatch)

        stan.zapisz_pozycje("A", produkt="blat")
        stan.zapisz_pozycje("B", produkt="parapet")

        assert "'A'" in linie[0] and "pozycji po zapisie: 1" in linie[0]
        assert "'B'" in linie[1] and "pozycji po zapisie: 2" in linie[1]

    def test_usuniecie_pozycji_tez_loguje_liczbe_po_zapisie(self, monkeypatch):
        stan.ustaw_kontekst(97402)
        stan.zapisz_pozycje("A", produkt="blat")
        stan.zapisz_pozycje("B", produkt="parapet")
        linie = self._log_przechwytywacz(monkeypatch)

        stan.zapisz_pozycje("B", usun=True)

        assert "pozycji po zapisie: 1" in linie[-1]
