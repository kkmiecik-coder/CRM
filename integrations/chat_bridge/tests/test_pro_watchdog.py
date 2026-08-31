# -*- coding: utf-8 -*-
"""
Watchdog porzuconej rozmowy.

_do_handoff odpala się dziś tylko z jawnej decyzji modelu, z limitu tur albo
z twardych reguł — NIGDY z bezczynności. Skutek z audytu: rozmowy kończą się
w statusie 'pending' z botem jako ostatnim mówiącym i nikt ich nie przejmuje.

Runda poprawek 1 (code review): trzy poprawki krytyczne.
K1 — watchdog MUSI działać wyłącznie na inboksach Debusia Pro (BOT_PRO_INBOXES),
inaczej wycisza stary silnik (bots/quotebot.py) na inboksach live chatu, które
świadomie NIE dostają handoffu przy wejściu i siedzą w pending do pierwszej
odpowiedzi klienta.
W4 — handoff własnym tokenem Pro, nie domyślnym (bota-podpowiadacza).
W5 — druga weryfikacja przez /messages, że ostatnia publiczna wiadomość jest
NAPRAWDĘ od bota (sender.type == 'agent_bot'), nie od człowieka-agenta, który
odpisał i świadomie zaparkował rozmowę (snooze) — message_type=1/outgoing w
podsumowaniu listy rozmów obejmuje OBIE możliwości.
"""
import pytest

import pro_watchdog as w

# Drobne (runda poprawek 2, code review): asercja tożsamości POZA zasięgiem
# fixture'a autouse niżej — ten podmienia `w._jest_pro_inbox` w KAŻDYM teście
# (nawet w TestZawezenieDoInboksowPro::test_uzywa_prawdziwego_predykatu_z_quote_worker,
# który sam też go nadpisuje przed sprawdzeniem), więc ŻADEN test nie sprawdzał
# PRAWDZIWEGO, niepodmienionego stanu importu z pro_watchdog.py. Gdyby ktoś
# zastąpił `from quote_worker import _jest_pro_inbox` lokalną kopią logiki (tą
# samą nazwą, inną/rozjeżdżającą się implementacją), cały plik nadal byłby
# zielony. Ta asercja działa PRZY IMPORCIE modułu testowego (zbieranie testów),
# zanim jakikolwiek fixture (autouse czy nie) w ogóle się uruchomi.
#
# UWAGA: sprawdzamy `__module__`, NIE identyczność obiektu (`is`) — kilka innych
# plików w tym pakiecie (test_quote_worker.py, test_quote_worker_pro_failover.py)
# robi `importlib.reload(quote_worker)` NA POZIOMIE MODUŁU (przy zbieraniu
# testów), co tworzy NOWY obiekt funkcji dla KAŻDEGO `def` w quote_worker.py —
# `is` byłoby więc fałszywie czerwone zależnie od KOLEJNOŚCI zbierania plików
# testowych przez pytest (przy pełnym pakiecie, nie przy tym pliku osobno),
# mimo że import w pro_watchdog.py jest poprawny. `__module__` przeżywa reload
# (funkcja zdefiniowana w quote_worker.py ma `__module__ == "quote_worker"'
# zarówno przed, jak i po jego przeładowaniu) i nadal wykrywa PRAWDZIWĄ
# regresję: lokalna kopia logiki w pro_watchdog.py miałaby
# `__module__ == "pro_watchdog"`.
assert w._jest_pro_inbox.__module__ == "quote_worker", (
    "pro_watchdog._jest_pro_inbox musi pochodzic z 'from quote_worker import "
    "_jest_pro_inbox' (__module__ == 'quote_worker'), nie z lokalnej kopii "
    "logiki w pro_watchdog.py - K1 (code review) mogl(a)by cicho zregresowac "
    "bez wykrycia przez testy nizej, ktore i tak podmieniaja te nazwe "
    "fixture'em/w tescie."
)


@pytest.fixture(autouse=True)
def _domyslnie_wszystkie_inboxy_sa_pro(monkeypatch):
    """Wiekszosc testow w tym pliku sprawdza logike SAMEGO watchdoga (prog ciszy,
    typ ostatniej wiadomosci, druga weryfikacja nadawcy) — nie zawezenia do
    inboksow Pro (K1, patrz TestZawezenieDoInboksowPro nizej), ktore normalnie
    czyta prawdziwy BOT_PRO_INBOXES (pusty w srodowisku testowym). Domyslnie
    pozwalamy wszystkim inboksom, zeby zaden z pozostalych testow nie musial
    tego osobno konfigurowac. Testy zawezenia nadpisuja to jawnie."""
    monkeypatch.setattr(w, "_jest_pro_inbox", lambda inbox_id: True)


def _rozmowa(conv_id, last_msg_type, minut_temu, teraz=1_000_000, inbox_id="5"):
    return {"id": conv_id, "inbox_id": inbox_id, "last_msg_type": last_msg_type,
            "last_msg_ts": teraz - minut_temu * 60}


class _FakeResp:
    """Ten sam wzorzec co test_pro_stan.py::_FakeResp — atrapa odpowiedzi core.chatwoot.cw."""

    def __init__(self, payload, ok=True, status_code=200):
        self._p = payload
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return {"payload": self._p}


def _wiadomosc(sender_type, private=False, message_type=1):
    return {"private": private, "message_type": message_type,
            "sender": {"type": sender_type} if sender_type else None}


class TestZnajdzPorzucone:
    """Filtr tani (bez wywolan API) — patrz tez TestZawezenieDoInboksowPro nizej
    dla filtra po inboksie (K1), dodanego w rundzie poprawek 1."""

    def test_rozmowa_z_botem_na_koncu_po_progu_jest_porzucona(self):
        rozmowy = [_rozmowa(1, "outgoing", 25)]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == [1]

    def test_rozmowa_swiezsza_niz_prog_nie_jest_porzucona(self):
        rozmowy = [_rozmowa(1, "outgoing", 5)]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == []

    def test_ostatnia_wiadomosc_klienta_nie_jest_porzuceniem(self):
        # Klient napisal i czeka — to zadanie kolejki, nie watchdoga.
        rozmowy = [_rozmowa(1, "incoming", 60)]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == []

    def test_brak_znacznika_czasu_nie_wywraca(self):
        rozmowy = [{"id": 1, "inbox_id": "5", "last_msg_type": "outgoing",
                    "last_msg_ts": None}]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == []

    def test_wiele_rozmow_zwracanych_w_kolejnosci(self):
        rozmowy = [_rozmowa(7, "outgoing", 30), _rozmowa(9, "outgoing", 45)]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == [7, 9]

    def test_prawdziwe_api_chatwoota_zwraca_typ_liczbowy_nie_string(self):
        # core.chatwoot._cw_conversations_by_status (a wiec i cw_pending_conversations)
        # niesie last_msg_type PROSTO z pola Chatwoota "message_type": to LICZBA
        # (0=incoming, 1=outgoing), NIE string — patrz sweeper.py/hot_lead_sweeper.py,
        # ktore z tego powodu sprawdzaja OBIE postacie ("in (0, "incoming")" itp.).
        # Test string-owej wersci wyzej sam w sobie NIE wykryje, gdyby ta funkcja
        # dzialala tylko na stringu "outgoing" i w produkcji nigdy nie odpalala.
        rozmowy = [{"id": 3, "inbox_id": "5", "last_msg_type": 1,
                    "last_msg_ts": 1_000_000 - 25 * 60}]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == [3]

    def test_prawdziwy_typ_liczbowy_incoming_nie_jest_porzuceniem(self):
        rozmowy = [{"id": 4, "inbox_id": "5", "last_msg_type": 0,
                    "last_msg_ts": 1_000_000 - 60 * 60}]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == []


class TestZawezenieDoInboksowPro:
    """K1 (runda poprawek 1, code review KRYTYCZNE): watchdog MUSI dzialac
    WYLACZNIE na inboksach Debusia Pro. Filtr uzywa GOTOWEGO predykatu
    quote_worker._jest_pro_inbox — nie wlasnej kopii tej samej logiki (dwie
    kopie latwo sie rozjezdzaja przy przyszlej zmianie)."""

    def test_rozmowa_na_inboksie_pro_jest_porzucona(self, monkeypatch):
        monkeypatch.setattr(w, "_jest_pro_inbox", lambda inbox_id: inbox_id == "5")
        rozmowy = [_rozmowa(1, "outgoing", 25, inbox_id="5")]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == [1]

    def test_rozmowa_spoza_inboksow_pro_nie_jest_porzucona(self, monkeypatch):
        monkeypatch.setattr(w, "_jest_pro_inbox", lambda inbox_id: inbox_id == "5")
        rozmowy = [_rozmowa(1, "outgoing", 25, inbox_id="18")]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == []

    def test_mieszana_lista_zwraca_tylko_inboxy_pro(self, monkeypatch):
        monkeypatch.setattr(w, "_jest_pro_inbox", lambda inbox_id: inbox_id == "5")
        rozmowy = [_rozmowa(1, "outgoing", 25, inbox_id="5"),
                   _rozmowa(2, "outgoing", 25, inbox_id="18")]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == [1]

    def test_uzywa_prawdziwego_predykatu_z_quote_worker(self, monkeypatch):
        # Dowod, ze filtr TO NAPRAWDE quote_worker._jest_pro_inbox (odczytujacy
        # PRAWDZIWY BOT_PRO_INBOXES), nie martwa kopia tej samej logiki.
        import quote_worker
        monkeypatch.setattr(w, "_jest_pro_inbox", quote_worker._jest_pro_inbox)
        monkeypatch.setattr(quote_worker, "BOT_PRO_INBOXES", {"5"})
        rozmowy = [_rozmowa(1, "outgoing", 25, inbox_id="5"),
                   _rozmowa(2, "outgoing", 25, inbox_id="18")]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == [1]


class TestBotNaprawdeMowilOstatni:
    """W5 (runda poprawek 1, code review WAZNE): message_type=1/outgoing w
    PODSUMOWANIU listy rozmow (cw_pending_conversations) obejmuje TAKZE
    czlowieka-agenta. Druga weryfikacja przez /messages (ten sam ksztalt API,
    juz uzywany i testowany w bots_pro.stan.wolno_prowadzic_rozmowe) sprawdza
    sender.type OSTATNIEJ publicznej wiadomosci."""

    def test_ostatnia_wiadomosc_od_bota_zwraca_prawde(self, monkeypatch):
        # UWAGA: monkeypatchujemy `w.cw`, NIE `core.chatwoot.cw` — pro_watchdog.py
        # importuje `cw` PO NAZWIE (`from core.chatwoot import cw, ...`), wiec ma
        # WLASNE, oddzielne wiazanie w swoim namespace, odlaczone od oryginalu
        # zaraz po imporcie modulu.
        monkeypatch.setattr(w, "cw", lambda method, path: _FakeResp(
            [_wiadomosc("agent_bot")]))
        assert w._bot_naprawde_mowil_ostatni(123) is True

    def test_ostatnia_wiadomosc_od_czlowieka_agenta_zwraca_falsz(self, monkeypatch):
        # Dokladnie scenariusz W5: agent odpisal publicznie i (swiadomie albo nie)
        # rozmowa wygladala jak "bot ostatni" w tanim filtrze wyzej.
        monkeypatch.setattr(w, "cw", lambda method, path: _FakeResp(
            [_wiadomosc("user")]))
        assert w._bot_naprawde_mowil_ostatni(123) is False

    def test_prywatna_notatka_po_odpowiedzi_bota_jest_pomijana(self, monkeypatch):
        monkeypatch.setattr(w, "cw", lambda method, path: _FakeResp([
            _wiadomosc("agent_bot"),
            _wiadomosc("user", private=True),
        ]))
        assert w._bot_naprawde_mowil_ostatni(123) is True

    def test_blad_http_zwraca_falsz_ostroznie(self, monkeypatch):
        monkeypatch.setattr(w, "cw",
                            lambda method, path: _FakeResp([], ok=False, status_code=500))
        assert w._bot_naprawde_mowil_ostatni(123) is False

    def test_wyjatek_sieciowy_zwraca_falsz_ostroznie(self, monkeypatch):
        def _rzuca(method, path):
            raise RuntimeError("timeout")

        monkeypatch.setattr(w, "cw", _rzuca)
        assert w._bot_naprawde_mowil_ostatni(123) is False

    def test_pusta_historia_zwraca_falsz(self, monkeypatch):
        monkeypatch.setattr(w, "cw", lambda method, path: _FakeResp([]))
        assert w._bot_naprawde_mowil_ostatni(123) is False

    def test_wiadomosc_systemowa_activity_na_koncu_jest_pomijana_bot_wciaz_ostatni(self, monkeypatch):
        # N2 (runda poprawek 2, code review WAZNE): wiadomosci systemowe Chatwoota
        # ("Konwersacja oznaczona jako oczekujaca", zmiana przypisania, etykiety) sa
        # NIEPRYWATNE i NIE MAJA sender — pierwsza wersja tej funkcji przerywala
        # petle na pierwszej nieprywatnej pozycji od konca, wiec activity na samym
        # koncu dawalo False, mimo ze bot naprawde mowil ostatni PRZED nia. Kolejnosc
        # (najstarsza->najnowsza w liscie, wiec activity na koncu listy): klient, bot,
        # activity(message_type=2, brak sender).
        monkeypatch.setattr(w, "cw", lambda method, path: _FakeResp([
            _wiadomosc("contact"),
            _wiadomosc("agent_bot"),
            _wiadomosc(None, message_type=2),
        ]))
        assert w._bot_naprawde_mowil_ostatni(123) is True

    def test_wiadomosc_systemowa_bez_sender_ale_typu_1_tez_pomijana(self, monkeypatch):
        # Zabezpieczenie NIEZALEZNE od message_type: sam BRAK sender (niezaleznie
        # od zadeklarowanego message_type) tez ma byc pomijany, nie tylko typ=2 —
        # Chatwoot moze nie ustawic tego pola spojnie we wszystkich wersjach API.
        monkeypatch.setattr(w, "cw", lambda method, path: _FakeResp([
            _wiadomosc("agent_bot"),
            _wiadomosc(None, message_type=1),
        ]))
        assert w._bot_naprawde_mowil_ostatni(123) is True

    def test_activity_nie_maskuje_prawdziwej_odpowiedzi_czlowieka(self, monkeypatch):
        # Kontrola negatywna: activity na koncu NIE MA odwracac wyniku, gdy
        # publiczna wiadomosc PRZED nia byla od czlowieka — pomijanie activity nie
        # ma stac sie furtka do false positive w drugim kierunku.
        monkeypatch.setattr(w, "cw", lambda method, path: _FakeResp([
            _wiadomosc("user"),
            _wiadomosc(None, message_type=2),
        ]))
        assert w._bot_naprawde_mowil_ostatni(123) is False

    def test_sama_wiadomosc_activity_bez_niczego_innego_zwraca_falsz(self, monkeypatch):
        monkeypatch.setattr(w, "cw", lambda method, path: _FakeResp([
            _wiadomosc(None, message_type=2),
        ]))
        assert w._bot_naprawde_mowil_ostatni(123) is False


class TestWatchdogOnce:
    """watchdog_once — jedno przejscie, testowalne bez wchodzenia w petle
    (ten sam wzorzec co sweep_once/hot_sweep_once w sweeper.py/hot_lead_sweeper.py)."""

    def test_pomija_rozmowe_gdy_druga_weryfikacja_mowi_ze_to_czlowiek(self, monkeypatch):
        monkeypatch.setattr(w, "cw_pending_conversations",
                            lambda: [_rozmowa(1, "outgoing", 25)])
        monkeypatch.setattr(w, "_jest_pro_inbox", lambda inbox_id: True)
        monkeypatch.setattr(w, "_bot_naprawde_mowil_ostatni", lambda conv_id: False)
        wywolania = []
        monkeypatch.setattr(w, "cw_bot_handoff",
                            lambda conv_id, token=None: wywolania.append((conv_id, token)) or True)

        oddane = w.watchdog_once(1_000_000)

        assert oddane == 0
        assert wywolania == []

    def test_oddaje_rozmowe_gdy_bot_naprawde_mowil_ostatni(self, monkeypatch):
        monkeypatch.setattr(w, "cw_pending_conversations",
                            lambda: [_rozmowa(1, "outgoing", 25)])
        monkeypatch.setattr(w, "_jest_pro_inbox", lambda inbox_id: True)
        monkeypatch.setattr(w, "_bot_naprawde_mowil_ostatni", lambda conv_id: True)
        wywolania = []
        monkeypatch.setattr(w, "cw_bot_handoff",
                            lambda conv_id, token=None: wywolania.append((conv_id, token)) or True)
        monkeypatch.setattr(w, "cw_note", lambda *a, **k: True)

        oddane = w.watchdog_once(1_000_000)

        assert oddane == 1
        assert wywolania == [(1, w.BOT_PRO_CW_AGENT_TOKEN)]

    def test_uzywa_tokenu_pro_nie_domyslnego(self, monkeypatch):
        # W4: token JAWNIE Pro (BOT_PRO_CW_AGENT_TOKEN) — domyslny cw_bot_handoff
        # siegalby po token bota-podpowiadacza, zly dla inboksow Pro.
        import config as config_mod
        monkeypatch.setattr(config_mod, "BOT_PRO_CW_AGENT_TOKEN", "TOKEN-PRO")
        monkeypatch.setattr(w, "BOT_PRO_CW_AGENT_TOKEN", "TOKEN-PRO")
        monkeypatch.setattr(w, "cw_pending_conversations",
                            lambda: [_rozmowa(1, "outgoing", 25)])
        monkeypatch.setattr(w, "_jest_pro_inbox", lambda inbox_id: True)
        monkeypatch.setattr(w, "_bot_naprawde_mowil_ostatni", lambda conv_id: True)
        przekazany_token = []
        monkeypatch.setattr(w, "cw_bot_handoff",
                            lambda conv_id, token=None: przekazany_token.append(token) or True)
        monkeypatch.setattr(w, "cw_note", lambda *a, **k: True)

        w.watchdog_once(1_000_000)

        assert przekazany_token == ["TOKEN-PRO"]

    def test_zostawia_prywatna_notatke_po_udanym_handoffie(self, monkeypatch):
        monkeypatch.setattr(w, "cw_pending_conversations",
                            lambda: [_rozmowa(1, "outgoing", 25)])
        monkeypatch.setattr(w, "_jest_pro_inbox", lambda inbox_id: True)
        monkeypatch.setattr(w, "_bot_naprawde_mowil_ostatni", lambda conv_id: True)
        monkeypatch.setattr(w, "cw_bot_handoff", lambda conv_id, token=None: True)
        notatki = []
        monkeypatch.setattr(w, "cw_note",
                            lambda conv_id, tekst, **k: notatki.append((conv_id, tekst)))

        w.watchdog_once(1_000_000)

        assert len(notatki) == 1
        assert notatki[0][0] == 1

    def test_niepowodzenie_handoffu_jest_logowane_nie_ciche(self, monkeypatch):
        # W4: log sukcesu byl tylko w galezi if — nieudany handoff mogl przejsc bez sladu.
        monkeypatch.setattr(w, "cw_pending_conversations",
                            lambda: [_rozmowa(1, "outgoing", 25)])
        monkeypatch.setattr(w, "_jest_pro_inbox", lambda inbox_id: True)
        monkeypatch.setattr(w, "_bot_naprawde_mowil_ostatni", lambda conv_id: True)
        monkeypatch.setattr(w, "cw_bot_handoff", lambda conv_id, token=None: False)
        logi = []
        monkeypatch.setattr(w, "log", lambda *a: logi.append(" ".join(str(x) for x in a)))

        oddane = w.watchdog_once(1_000_000)

        assert oddane == 0
        assert any("NIEUDANY" in wpis for wpis in logi)


class _OdpowiedzNotatki:
    """Namiastka `requests.Response` — `cw_note` zwraca wlasnie taki obiekt."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ""


class TestKodHttpNotatkiWatchdoga:
    """W2: notatka watchdoga byla owinieta w goly `except Exception: pass`, wiec
    KAZDY kod HTTP przechodzil bez sladu. Bledny albo wygasly BOT_PRO_CW_AGENT_TOKEN
    daje 401 — a wtedy handoff juz sie odbyl (inny token, inna sciezka), rozmowa
    jest 'open', tylko konsultant nie wie DLACZEGO ja dostal. Zly token objawia sie
    w notatkach cisza zamiast bledu."""

    def _kandydat(self, monkeypatch, odpowiedz_notatki):
        monkeypatch.setattr(w, "cw_pending_conversations",
                            lambda: [_rozmowa(1, "outgoing", 25)])
        monkeypatch.setattr(w, "_jest_pro_inbox", lambda inbox_id: True)
        monkeypatch.setattr(w, "_bot_naprawde_mowil_ostatni", lambda conv_id: True)
        monkeypatch.setattr(w, "cw_bot_handoff", lambda conv_id, token=None: True)
        monkeypatch.setattr(w, "cw_note", lambda conv_id, tekst, **k: odpowiedz_notatki)
        logi = []
        monkeypatch.setattr(w, "log", lambda *a: logi.append(" ".join(str(x) for x in a)))
        return logi

    def test_401_notatki_jest_logowane(self, monkeypatch):
        logi = self._kandydat(monkeypatch, _OdpowiedzNotatki(401))

        w.watchdog_once(1_000_000)

        assert any("401" in wpis for wpis in logi)

    def test_udana_notatka_nie_generuje_alarmu(self, monkeypatch):
        logi = self._kandydat(monkeypatch, _OdpowiedzNotatki(200))

        w.watchdog_once(1_000_000)

        assert not any("notatka" in wpis.lower() and "nieudana" in wpis.lower() for wpis in logi)

    def test_handoff_pozostaje_zaliczony_mimo_zlej_notatki(self, monkeypatch):
        """Notatka to sciezka pomocnicza — jej porazka NIE moze cofnac oddania
        rozmowy, ktore juz sie udalo."""
        self._kandydat(monkeypatch, _OdpowiedzNotatki(401))

        assert w.watchdog_once(1_000_000) == 1


class TestWatchdogWylacznik:
    """Minor (runda poprawek 1): <=0 ma WYLACZAC bezpiecznik, nie dawac
    najagresywniejszego zachowania (wzorzec z sweeper.py/hot_lead_sweeper.py)."""

    def test_watchdog_wraca_natychmiast_gdy_bot_pro_inboxes_puste(self, monkeypatch):
        monkeypatch.setattr(w, "BOT_PRO_INBOXES", set())

        def _nigdy_nie_wolane():
            raise AssertionError("watchdog nie powinien wejsc w petle / wolac API")

        monkeypatch.setattr(w, "cw_pending_conversations", _nigdy_nie_wolane)
        w.watchdog()   # ma wrocic, nie zawiesic testu w while True

    def test_watchdog_wraca_natychmiast_gdy_watchdog_minutes_zero(self, monkeypatch):
        monkeypatch.setattr(w, "BOT_PRO_INBOXES", {"5"})
        monkeypatch.setattr(w, "BOT_PRO_WATCHDOG_MINUTES", 0)

        def _nigdy_nie_wolane():
            raise AssertionError("watchdog nie powinien wejsc w petle / wolac API")

        monkeypatch.setattr(w, "cw_pending_conversations", _nigdy_nie_wolane)
        w.watchdog()

    def test_watchdog_wraca_natychmiast_gdy_watchdog_minutes_ujemne(self, monkeypatch):
        monkeypatch.setattr(w, "BOT_PRO_INBOXES", {"5"})
        monkeypatch.setattr(w, "BOT_PRO_WATCHDOG_MINUTES", -5)

        def _nigdy_nie_wolane():
            raise AssertionError("watchdog nie powinien wejsc w petle / wolac API")

        monkeypatch.setattr(w, "cw_pending_conversations", _nigdy_nie_wolane)
        w.watchdog()
