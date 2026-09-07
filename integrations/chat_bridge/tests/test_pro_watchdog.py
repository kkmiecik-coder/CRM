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
from bots_pro import notatki, stan


class _OdpowiedzNotatki:
    """Namiastka `requests.Response` — `cw_note` zwraca wlasnie taki obiekt."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ""


# Notatka watchdoga sklada sie dzis z BIEZACEGO STANU rozmowy (Z4), wiec ten plik
# dotyka tabel `pro_dane`/`pro_stan`.
stan.init_pro()

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


@pytest.fixture(autouse=True)
def _notatki_nie_wychodza_do_sieci(monkeypatch):
    """Z4: notatke sklada teraz `bots_pro.notatki`, wiec `cw_note` trzeba podmienic
    W TYM module — `pro_watchdog` ma wlasne wiazanie tej nazwy i podmiana `w.cw_note`
    (jak dotad) zostawialaby prawdziwe wywolanie HTTP w sciezce glownej. Domyslnie
    zbieramy tresci notatek do listy; testy, ktore chca innego zachowania, nadpisuja
    to jawnie."""
    monkeypatch.setattr(notatki, "cw_note", lambda conv_id, tekst, **k: _OdpowiedzNotatki(200))


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


def _zbieraj_notatki(monkeypatch):
    """Podmienia `cw_note` w `bots_pro.notatki` (sciezka GLOWNA notatki watchdoga)
    i zwraca liste, do ktorej trafia (conv_id, tresc)."""
    wyslane = []
    monkeypatch.setattr(notatki, "cw_note", lambda conv_id, tekst, **k: (
        wyslane.append((conv_id, tekst)) or _OdpowiedzNotatki(200)))
    return wyslane


def _porzucona(monkeypatch, rozmowy):
    """Ustawia watchdoga tak, zeby `rozmowy` przeszly przez obie bramki do handoffu."""
    monkeypatch.setattr(w, "cw_pending_conversations", lambda: rozmowy)
    monkeypatch.setattr(w, "_jest_pro_inbox", lambda inbox_id: True)
    monkeypatch.setattr(w, "_bot_naprawde_mowil_ostatni", lambda conv_id: True)
    monkeypatch.setattr(w, "cw_bot_handoff", lambda conv_id, token=None: True)


def _rozmowa_z_pozycja(conv, produkt, kwota=None):
    """Zapisuje pozycje (i ewentualnie kwote pokazana klientowi) dla rozmowy `conv`.

    Na koniec PRZESTAWIA kontekst na inna rozmowe — inaczej testy nizej byly bezwartosciowe:
    contextvar zostawiony na `conv` sprawilby, ze notatka zlozylaby sie poprawnie
    NAWET gdyby watchdog w ogole nie ustawial kontekstu."""
    stan.ustaw_kontekst(conv)
    stan.zapisz_pozycje("1", produkt=produkt, dlugosc_cm=180, szerokosc_cm=60,
                        grubosc_cm=4, ilosc=1, selected_variant="dab-lity-ab",
                        wykonczenie="surowe")
    if kwota is not None:
        stan.zapisz_stan(pokazana_kwota=kwota)
    stan.ustaw_kontekst(99_000_000)


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
        # Z4: notatke sklada `bots_pro.notatki`, wiec podmieniamy `cw_note` TAM —
        # `w.cw_note` obsluguje dzis wylacznie sciezke awaryjna.
        monkeypatch.setattr(w, "cw_pending_conversations",
                            lambda: [_rozmowa(1, "outgoing", 25)])
        monkeypatch.setattr(w, "_jest_pro_inbox", lambda inbox_id: True)
        monkeypatch.setattr(w, "_bot_naprawde_mowil_ostatni", lambda conv_id: True)
        monkeypatch.setattr(w, "cw_bot_handoff", lambda conv_id, token=None: True)
        wyslane = _zbieraj_notatki(monkeypatch)

        w.watchdog_once(1_000_000)

        assert len(wyslane) == 1
        assert wyslane[0][0] == 1

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
        # OBIE sciezki daja ten sam kod HTTP: glowna (notatka stanu) i awaryjna.
        monkeypatch.setattr(notatki, "cw_note", lambda conv_id, tekst, **k: odpowiedz_notatki)
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


class TestNotatkaWatchdoga:
    """Z4: watchdog oddaje rozmowe TA SAMA notatka, co handoff z tury —
    z pozycjami, kwota pokazana klientowi i czasem ciszy.

    Zmierzone na produkcji przed ta poprawka: 6 z 6 notatek handoffowych mowilo
    „Zebrane pozycje: brak", a watchdog nie pisal notatki stanu WCALE — szlo
    stad jedno zaszyte zdanie. Konsultantka odtwarzala specyfikacje, czytajac
    caly watek (czasy reakcji: 39 min ... 12 h, raz nigdy)."""

    def test_notatka_zawiera_zebrane_pozycje(self, monkeypatch):
        # TEST ROZNICUJACY: na kodzie sprzed naprawy notatka byla zaszytym zdaniem
        # bez pozycji. Oblewa TAKZE wtedy, gdy ktos usunie `ustaw_kontekst_odczytu`
        # z `_notatka_watchdoga` — `stan.pozycje()` zwroci wtedy PO CICHU pusta
        # liste (odczyty swiadomie nie wolaja `_wymagany_conv_id`) i notatka
        # napisze „Zebrane pozycje: brak" na rozmowie, ktora pozycje MA.
        _rozmowa_z_pozycja(94_101, "parapet debowy")
        _porzucona(monkeypatch, [_rozmowa(94_101, "outgoing", 25)])
        wyslane = _zbieraj_notatki(monkeypatch)

        w.watchdog_once(1_000_000)

        (_, tresc), = wyslane
        assert "Zebrane pozycje:" in tresc
        assert "parapet debowy" in tresc
        assert "180x60x4" in tresc
        assert "Zebrane pozycje: brak" not in tresc

    def test_notatka_zawiera_kwote_pokazana_klientowi(self, monkeypatch):
        _rozmowa_z_pozycja(94_102, "blat", kwota=1010.54)
        _porzucona(monkeypatch, [_rozmowa(94_102, "outgoing", 25)])
        wyslane = _zbieraj_notatki(monkeypatch)

        w.watchdog_once(1_000_000)

        (_, tresc), = wyslane
        assert "Ostatnia kwota pokazana klientowi" in tresc
        assert "1 010,54" in tresc

    def test_notatka_podaje_liczbe_minut_ciszy(self, monkeypatch):
        _porzucona(monkeypatch, [_rozmowa(94_103, "outgoing", 47)])
        wyslane = _zbieraj_notatki(monkeypatch)

        w.watchdog_once(1_000_000)

        (_, tresc), = wyslane
        assert "47 min" in tresc

    def test_rozmowa_bez_pozycji_dostaje_sensowna_notatke_i_nic_nie_zmysla(self, monkeypatch):
        # Rozmowa, w ktorej bot nic nie zdazyl zebrac (3 z 5 rozmow watchdoga na
        # produkcji): notatka ma byc uczciwa — powod jest, a o pozycjach i kwocie
        # ma NIE twierdzic, ze cokolwiek jest.
        _porzucona(monkeypatch, [_rozmowa(94_104, "outgoing", 25)])
        wyslane = _zbieraj_notatki(monkeypatch)

        w.watchdog_once(1_000_000)

        (_, tresc), = wyslane
        assert "Zebrane pozycje: brak" in tresc
        assert "Ostatnia kwota pokazana klientowi" not in tresc
        assert "Wycena w CRM" not in tresc

    def test_nie_twierdzi_ze_brakuje_tylko_potwierdzenia(self, monkeypatch):
        """WIAZACE ZASTRZEZENIE: notatka NIE MOZE sugerowac „brakuje juz tylko
        jego »tak«" na podstawie `oczekiwany_podpis`.

        Ta kolumna ma jednego pisarza (`podsumowanie.wyslij`) i ZERO miejsc
        czyszczacych — przezywa jawna odmowe klienta. W produkcyjnej rozmowie
        4912 klient napisal, ze zestawienie pomija ponad 10 elementow, a podpis
        dalej stal ustawiony przy kwocie osmiokrotnie zanizonej. Notatka
        twierdzaca „czekamy na potwierdzenie" dalaby konsultantce falszywa
        pewnosc dokladnie tam, gdzie potrzebna jest czujnosc."""
        stan.ustaw_kontekst(94_105)
        stan.zapisz_stan(oczekiwany_podpis="sha-cokolwiek", pokazana_kwota=123.55)
        stan.ustaw_kontekst(99_000_000)
        _porzucona(monkeypatch, [_rozmowa(94_105, "outgoing", 25)])
        wyslane = _zbieraj_notatki(monkeypatch)

        w.watchdog_once(1_000_000)

        (_, tresc), = wyslane
        maly = tresc.lower()
        assert "brakuje" not in maly
        assert "czeka" not in maly
        assert "nie potwierdzi" not in maly
        # Sam fakt (kwota, ktora klient zobaczyl) zostaje — to dane, nie ocena.
        assert "123,55" in tresc

    def test_kontekst_nie_przecieka_miedzy_rozmowami_w_jednym_przejsciu(self, monkeypatch):
        # Dwie porzucone rozmowy w JEDNYM `watchdog_once`. Druga notatka MUSI pojsc
        # (dowod, ze bramka „jedna notatka na ture" jej nie zjadla) i NIE MOZE
        # zawierac pozycji pierwszej (dowod, ze kontekst jest przestawiany, a nie
        # ustawiany raz).
        _rozmowa_z_pozycja(94_106, "parapet pierwszy")
        _rozmowa_z_pozycja(94_107, "blat drugi")
        _porzucona(monkeypatch, [_rozmowa(94_106, "outgoing", 25),
                                 _rozmowa(94_107, "outgoing", 30)])
        wyslane = _zbieraj_notatki(monkeypatch)

        w.watchdog_once(1_000_000)

        assert [conv for conv, _ in wyslane] == [94_106, 94_107]
        assert "parapet pierwszy" in wyslane[0][1]
        assert "blat drugi" not in wyslane[0][1]
        assert "blat drugi" in wyslane[1][1]
        assert "parapet pierwszy" not in wyslane[1][1]

    def test_nie_kasuje_flag_tury_trwajacej_rownolegle(self, monkeypatch):
        """Dlatego watchdog uzywa ZAWEZONEGO `ustaw_kontekst_odczytu`, a nie
        pelnego `ustaw_kontekst`.

        Pelna wersja wola `_wyzeruj_flagi_tury`, a `stan._flagi_tury` to slownik
        MODULOWY, wspolny dla calego procesu. Watchdog i worker chodza rownolegle,
        wiec wyzerowanie flag rozmowy z cudzego watku w SRODKU jej tury gasi
        bezpieczniki X2 (drugie podsumowanie, drugi handoff, cisza po pytaniu bota).

        Testujemy WYLACZNIE flage — asercji o `stan.conv_id()` tu nie ma
        swiadomie: `watchdog_once` bieglby w tym samym watku co test, wiec
        kazda taka asercja przechodzilaby zawsze i mowilaby o izolacji
        miedzywatkowej dokladnie nic. Izolacje contextvarow mierzy
        `test_kontekst_watchdoga_nie_przecieka_do_watku_workera` nizej."""
        stan.ustaw_kontekst(94_108)
        stan.oznacz_podsumowanie_wyslane()
        assert stan.podsumowanie_wyslane() is True
        _porzucona(monkeypatch, [_rozmowa(94_108, "outgoing", 25)])
        _zbieraj_notatki(monkeypatch)

        w.watchdog_once(1_000_000)

        assert stan.podsumowanie_wyslane() is True

    def test_nie_zapala_flagi_notatki_tury_trwajacej_rownolegle(self, monkeypatch):
        """Druga polowa tej samej ochrony: watchdog nie moze do `_flagi_tury`
        ani PISAC, ani ich ZEROWAC.

        Zawezenie kontekstu bronilo tylko przed zerowaniem. `wyslij_notatke`
        po udanej wysylce wola `stan.oznacz_notatke_w_turze()`, czyli mutuje
        ten sam slownik modulowy z watku spoza tury. Skutek w waskim oknie
        wyscigu: watchdog przechodzi bramki dla rozmowy X, w tej samej chwili
        klient pisze i worker startuje ture X (`ustaw_kontekst` czysci flagi),
        watchdog zapala `notatka_w_turze` — a worker robiacy zaraz potem
        handoff trafia na bramke N7 i PO CICHU rezygnuje z notatki TUROWEJ.
        Konsultant dostaje notatke watchdoga zamiast notatki o zdarzeniu,
        ktore rozmowe faktycznie oddalo. Stad `wyslij_notatke(...,
        oznacz_ture=False)` dla wolajacych spoza tury."""
        stan.ustaw_kontekst(94_110)
        assert stan.notatka_w_turze() is False
        _porzucona(monkeypatch, [_rozmowa(94_110, "outgoing", 25)])
        wyslane = _zbieraj_notatki(monkeypatch)

        w.watchdog_once(1_000_000)

        assert len(wyslane) == 1, "notatka nie poszla — test nie mierzylby niczego"
        # Kontrola zywotnosci flagi jest wyzej (asercja False przed przejsciem):
        # gdyby watchdog ja zapalil, ta linia bylaby czerwona.
        assert stan.notatka_w_turze() is False

    def test_kontekst_watchdoga_nie_przecieka_do_watku_workera(self, monkeypatch):
        """Watchdog i worker to DWA watki jednego procesu. `stan._conv_id` jest
        contextvarem, wiec przestawienie go w watku watchdoga nie ma prawa
        ruszyc watku workera — ale tylko dopoki kontekst rzeczywiscie mieszka
        w contextvarze. Test jest tu po to, zeby przyszle przeniesienie tego
        stanu do struktury wspoldzielonej nie przeszlo po cichu: skutkiem
        byloby zlozenie notatki z pozycji CUDZEJ rozmowy."""
        import threading

        _rozmowa_z_pozycja(94_111, "blat watchdoga")
        stan.ustaw_kontekst(94_200)           # kontekst „workera" — INNA rozmowa
        _porzucona(monkeypatch, [_rozmowa(94_111, "outgoing", 25)])
        wyslane = _zbieraj_notatki(monkeypatch)

        watek = threading.Thread(target=w.watchdog_once, args=(1_000_000,))
        watek.start()
        watek.join()

        assert len(wyslane) == 1
        assert "blat watchdoga" in wyslane[0][1]
        assert stan.conv_id() == 94_200

    def test_awaria_notatki_stanu_konczy_sie_notatka_awaryjna(self, monkeypatch):
        # Uboga notatka jest lepsza niz zero notatek przy rozmowie, ktora juz lezy
        # u czlowieka — i handoff pozostaje zaliczony.
        _porzucona(monkeypatch, [_rozmowa(94_109, "outgoing", 33)])

        def _wybuch(*a, **k):
            raise RuntimeError("Chatwoot padl")

        monkeypatch.setattr(notatki, "cw_note", _wybuch)
        awaryjne = []
        monkeypatch.setattr(w, "cw_note", lambda conv_id, tekst, **k: (
            awaryjne.append((conv_id, tekst)) or _OdpowiedzNotatki(200)))

        assert w.watchdog_once(1_000_000) == 1
        assert len(awaryjne) == 1
        assert "33 min" in awaryjne[0][1]


class TestTelemetriaHandoffuWatchdoga:
    """P5 (kontrola koncowa): watchdog jest TRZECIM wejsciem handoffu — obok
    `tura._oddaj_konsultantowi` i narzedzia `oddaj_czlowiekowi` — ale jako
    jedyny nie przechodzi przez `stan.handoff`, gdzie stalo jedyne
    `log_event(..., "handoff", ...)`. Oddawal wiec rozmowy NIEWIDZIALNIE dla
    lejka: w probce 12 rozmow produkcyjnych oddal 4 z 9 (4664, 4704, 4952,
    4995), wiec `SELECT COUNT(DISTINCT conv_id) FROM quote_events WHERE
    event='handoff'` liczylby 5 zamiast 9. Rozmowa 4704 — najlepiej
    poprowadzona w calej probce — wygladalaby w raporcie jak rozmowa
    doprowadzona do konca BEZ handoffu, czyli jak sukces lejka.

    Watchdog swiadomie NIE idzie przez `stan.handoff`: ta funkcja rusza flagi
    turowe w slowniku modulowym wspolnym dla procesu, a watchdog chodzi we
    wlasnym watku rownolegle z turami workera (patrz
    `TestKontekstWatchdoga`)."""

    def _kandydat(self, monkeypatch, handoff_udany=True):
        monkeypatch.setattr(w, "cw_pending_conversations",
                            lambda: [_rozmowa(4704, "outgoing", 33)])
        monkeypatch.setattr(w, "_bot_naprawde_mowil_ostatni", lambda conv_id: True)
        monkeypatch.setattr(w, "cw_bot_handoff",
                            lambda conv_id, token=None: handoff_udany)
        zdarzenia = []
        monkeypatch.setattr(w, "log_event", lambda conv_id, event, meta=None: (
            zdarzenia.append((conv_id, event, meta))))
        return zdarzenia

    def test_udany_handoff_watchdoga_trafia_do_telemetrii(self, monkeypatch):
        zdarzenia = self._kandydat(monkeypatch)

        assert w.watchdog_once(1_000_000) == 1

        assert [(cid, ev) for cid, ev, _ in zdarzenia] == [(4704, "handoff")]

    def test_powod_odroznia_watchdoga_od_zwyklego_handoffu(self, monkeypatch):
        # Bez tego zdarzenia watchdoga zlewaja sie w raporcie z decyzja bota i
        # z bezpiecznikami tury — a to trzy rozne zjawiska lejka. Powod jest
        # DOKLADNIE ten sam tekst, ktory dostaje konsultant w notatce.
        zdarzenia = self._kandydat(monkeypatch)

        w.watchdog_once(1_000_000)

        powod = zdarzenia[0][2]["powod"]
        assert "watchdog" in powod
        assert "33 min" in powod

    def test_nieudany_handoff_NIE_trafia_do_telemetrii(self, monkeypatch):
        # Rozmowa, ktorej Chatwoot nie przelaczyl, NIE zostala oddana — wpis w
        # lejku bylby falszywym sukcesem po drugiej stronie. Ta sama zasada, co
        # przy `summary_sent` w podsumowaniu.
        zdarzenia = self._kandydat(monkeypatch, handoff_udany=False)

        assert w.watchdog_once(1_000_000) == 0
        assert zdarzenia == []


class TestMinutyCiszy:
    def test_liczy_pelne_minuty(self):
        assert w._minuty_ciszy(1_000_000 - 25 * 60, 1_000_000) == 25

    def test_brak_znacznika_daje_none(self):
        assert w._minuty_ciszy(None, 1_000_000) is None

    def test_powod_bez_znacznika_uzywa_progu_zamiast_zmyslac_liczbe(self):
        assert "%s min" % w.BOT_PRO_WATCHDOG_MINUTES in w._powod_watchdoga(None)
