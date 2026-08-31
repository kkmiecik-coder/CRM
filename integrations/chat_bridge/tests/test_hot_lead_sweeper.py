# -*- coding: utf-8 -*-
# Test: sweeper "goracy lead" — rozmowa juz oddana agentowi (status open) po cenie bota
# (priced=1), ale klient milczy dluzej niz prog -> notatka priorytetowa (LS-04).
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_hotlead.db"))
import importlib

import config; importlib.reload(config)
cwm = importlib.import_module("core.chatwoot")
db_mod = importlib.import_module("core.db"); db_mod.init_db()
quotebot = importlib.import_module("bots.quotebot"); importlib.reload(quotebot)
pro_stan = importlib.import_module("bots_pro.stan"); pro_stan.init_pro()
hls = importlib.import_module("hot_lead_sweeper"); importlib.reload(hls)


class _Resp:
    def __init__(self, payload):
        self._payload = payload
    def json(self):
        return {"data": {"payload": self._payload}}


def test_cw_open_conversations_parsuje_status_open(monkeypatch):
    def fake_cw(method, path, payload=None):
        assert "status=open" in path
        return _Resp([{"id": 5, "inbox_id": 18, "last_non_activity_message":
                       {"message_type": 1, "created_at": 100}, "timestamp": 100}])
    monkeypatch.setattr(cwm, "cw", fake_cw)
    out = cwm.cw_open_conversations()
    assert out == [{"id": 5, "inbox_id": 18, "last_msg_type": 1, "last_msg_ts": 100}]


def _conv(cid=1, last_type="outgoing", age=999999, now=1_000_000):
    return {"id": cid, "inbox_id": 18, "last_msg_type": last_type, "last_msg_ts": now - age}


def test_otwiera_rozmowe_z_cena_i_cisza_klienta(monkeypatch):
    quotebot._set_priced(77, True)
    monkeypatch.setattr(hls, "cw_open_conversations", lambda: [_conv(cid=77)])
    notes = []
    monkeypatch.setattr(hls, "cw_note", lambda cid, t, **kw: notes.append((cid, t)) or True)
    assert hls.hot_sweep_once(1_000_000) == 1
    assert notes and notes[0][0] == 77


def test_pomija_rozmowe_bez_ceny(monkeypatch):
    quotebot._set_priced(78, False)
    monkeypatch.setattr(hls, "cw_open_conversations", lambda: [_conv(cid=78)])
    monkeypatch.setattr(hls, "cw_note",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("nie powinno wolac")))
    assert hls.hot_sweep_once(1_000_000) == 0


def test_pomija_gdy_ostatnie_slowo_klienta(monkeypatch):
    # last_msg_type incoming = klient napisal cos PO cenie -> bot juz odpowie normalnie, nie sweeper
    quotebot._set_priced(79, True)
    monkeypatch.setattr(hls, "cw_open_conversations", lambda: [_conv(cid=79, last_type="incoming")])
    monkeypatch.setattr(hls, "cw_note",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("nie powinno wolac")))
    assert hls.hot_sweep_once(1_000_000) == 0


def test_pomija_mlodsza_niz_prog(monkeypatch):
    quotebot._set_priced(80, True)
    monkeypatch.setattr(hls, "cw_open_conversations", lambda: [_conv(cid=80, age=10)])
    monkeypatch.setattr(hls, "cw_note",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("nie powinno wolac")))
    assert hls.hot_sweep_once(1_000_000) == 0


def test_sweeper_wylaczony_przez_interval_zero(monkeypatch):
    monkeypatch.setattr(hls, "HOT_LEAD_SWEEP_INTERVAL", 0)
    hls.hot_lead_sweeper()  # brak zawieszenia = sukces


# --- N11: rozmowy Debusia Pro tez sa goracymi leadami -----------------------
#
# Regres wobec starego silnika: mechanizm ratujacy porzucone gorace leady czytal
# WYLACZNIE kolumne `quote_state.priced` (stary silnik), wiec rozmowy Pro byly
# dla niego niewidoczne — nowy silnik pokazywal klientowi cene, rozmowa szla do
# czlowieka, klient milkl, i nikt tego nie podnosil.


def _pro_pokazal_cene(conv_id, podpis="podpis-testowy"):
    """Odpowiednik quotebot._set_priced dla silnika Pro: `oczekiwany_podpis`
    zapisuje `podsumowanie.wyslij()` DOPIERO po udanej wysylce zestawienia
    z cena — dokladnie w tym samym momencie, w ktorym stary silnik ustawial
    `priced` (patrz bots/quotebot.py, tuz po cw_agent_reply z cena)."""
    pro_stan.ustaw_kontekst(conv_id)
    pro_stan.zapisz_stan(oczekiwany_podpis=podpis)


def test_oznacza_rozmowe_pro_ktora_pokazala_cene(monkeypatch):
    quotebot._set_priced(101, False)   # stary silnik: NIE zna tej rozmowy
    _pro_pokazal_cene(101)
    monkeypatch.setattr(hls, "cw_open_conversations", lambda: [_conv(cid=101)])
    notes = []
    monkeypatch.setattr(hls, "cw_note", lambda cid, t, **kw: notes.append((cid, t)) or True)
    assert hls.hot_sweep_once(1_000_000) == 1
    assert notes[0][0] == 101


def test_pomija_rozmowe_pro_bez_pokazanej_ceny(monkeypatch):
    # Rozmowa Pro ISTNIEJE w pro_stan (bot cos w niej robil), ale klient nigdy
    # nie zobaczyl zestawienia z cena — to nie jest goracy lead.
    pro_stan.ustaw_kontekst(102)
    pro_stan.zapisz_stan(tury_rozmowy=3)
    monkeypatch.setattr(hls, "cw_open_conversations", lambda: [_conv(cid=102)])
    monkeypatch.setattr(hls, "cw_note",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("nie powinno wolac")))
    assert hls.hot_sweep_once(1_000_000) == 0


def test_pro_nie_omija_pozostalych_warunkow(monkeypatch):
    # Cena to JEDEN z warunkow, nie przepustka: cisza krotsza niz prog i
    # ostatnie slowo klienta nadal dyskwalifikuja rozmowe, tak samo jak
    # w starym silniku.
    _pro_pokazal_cene(103)
    _pro_pokazal_cene(104)
    monkeypatch.setattr(hls, "cw_open_conversations",
                        lambda: [_conv(cid=103, age=10),
                                 _conv(cid=104, last_type="incoming")])
    monkeypatch.setattr(hls, "cw_note",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("nie powinno wolac")))
    assert hls.hot_sweep_once(1_000_000) == 0


def test_jedno_zapytanie_zbiorcze_a_nie_jedno_na_rozmowe(monkeypatch):
    # Sweeper chodzi po WSZYSTKICH otwartych rozmowach kanalu. Odpytywanie
    # bazy per rozmowa skalowaloby sie z dlugoscia kolejki agenta.
    wywolania = []
    prawdziwa = hls.rozmowy_z_pokazana_cena
    monkeypatch.setattr(hls, "rozmowy_z_pokazana_cena",
                        lambda ids: wywolania.append(list(ids)) or prawdziwa(ids))
    monkeypatch.setattr(hls, "cw_open_conversations",
                        lambda: [_conv(cid=c) for c in (111, 112, 113, 114)])
    monkeypatch.setattr(hls, "cw_note", lambda *a, **k: True)
    hls.hot_sweep_once(1_000_000)
    assert len(wywolania) == 1
    assert wywolania[0] == [111, 112, 113, 114]


def test_awaria_odczytu_pro_nie_zatrzymuje_starego_silnika(monkeypatch):
    # Stan Pro moze w danej instalacji nie istniec (mostek bez Debusia Pro) albo
    # jeszcze nie powstac (wyscig watkow przy starcie bridge.py — init_pro wola
    # quote_worker, sweeper startuje obok). Zaden z tych przypadkow nie ma
    # zatrzymac przejscia sweepera dla rozmow STAREGO silnika.
    quotebot._set_priced(105, True)
    monkeypatch.setattr(hls, "rozmowy_z_pokazana_cena",
                        lambda ids: (_ for _ in ()).throw(RuntimeError("brak pro_stan")))
    monkeypatch.setattr(hls, "cw_open_conversations", lambda: [_conv(cid=105)])
    notes = []
    monkeypatch.setattr(hls, "cw_note", lambda cid, t, **kw: notes.append(cid) or True)
    assert hls.hot_sweep_once(1_000_000) == 1
    assert notes == [105]
