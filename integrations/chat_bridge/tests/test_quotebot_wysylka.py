# -*- coding: utf-8 -*-
# Testy wysylki GlobKurier w quotebocie: helpery stanu/kodu/komunikatu, oferta po zapisie,
# obsluga oszacowania + dopisanie do wyceny.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Detal"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_qwys.db")
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)


def _poz(**kw):
    base = {"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60", "grubosc": "4",
            "gatunek": "dąb", "technologia": "lity", "klasa": "A/B", "ilosc": "1",
            "wykonczenie": "surowe", "finishing_id": ""}
    base.update(kw); return base


# --- helpery stanu / kodu / komunikatu ---

def test_awaiting_postcode_set_get():
    qb._set_awaiting_postcode(900, True)
    assert qb._awaiting_postcode(900) is True
    qb._set_awaiting_postcode(900, False)
    assert qb._awaiting_postcode(900) is False


def test_wyciagnij_kod():
    assert qb._wyciagnij_kod("mój kod to 36-068 proszę") == "36-068"
    assert qb._wyciagnij_kod("Kraków, ul. Długa") is None
    assert qb._wyciagnij_kod("") is None


def test_wysylka_msg_najtansza_z_cena():
    msg = qb._wysylka_msg({"ok": True, "carriers": 3, "carrier_name": "InPost",
                           "shipping_brutto": 104.0})
    assert "InPost" in msg and "104,00 zł" in msg


def test_wysylka_msg_gabaryt_bez_kuriera():
    assert "konsultant" in qb._wysylka_msg({"ok": True, "carriers": 0})


def test_wysylka_msg_blad_api():
    assert "konsultant" in qb._wysylka_msg({"ok": False, "errors": []})


# --- _obsluz_wysylke: oszacowanie + dopisanie do wyceny ---

def test_obsluz_wysylke_podaje_cene_i_dopisuje_do_wyceny(monkeypatch):
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "shipping_quote",
                        lambda p, kod, o=None: {"ok": True, "carriers": 3, "carrier_name": "InPost",
                                                "shipping_netto": 84.55, "shipping_brutto": 104.0})
    captured = {}
    monkeypatch.setattr(qb.crm_calc, "update_quote",
                        lambda uid, p, o, **kw: captured.update(kw) or {"ok": True})
    qb._zapisz_dane(910, {"pozycje": [_poz()], "wspolne": {}})
    qb._set_edit_uuid(910, "UU")
    qb._obsluz_wysylke(910, "36-068")
    assert any("InPost" in r and "104,00 zł" in r for r in replies)
    assert captured["courier_name"] == "InPost"
    assert captured["shipping_brutto"] == 104.0


def test_obsluz_wysylke_gabaryt_bez_kuriera_nie_dopisuje(monkeypatch):
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "shipping_quote", lambda p, kod, o=None: {"ok": True, "carriers": 0})
    monkeypatch.setattr(qb.crm_calc, "update_quote",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("update nie powinien byc wolany")))
    qb._zapisz_dane(911, {"pozycje": [_poz()], "wspolne": {}})
    qb._set_edit_uuid(911, "UU")
    qb._obsluz_wysylke(911, "36-068")
    assert any("konsultant" in r for r in replies)


# --- oferta wysylki po pierwszym zapisie, brak przy aktualizacji ---

def test_pierwszy_zapis_proponuje_wysylke(monkeypatch):
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": True, "client": {"id": 42}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": True, "quote_number": "W/1",
                                                     "public_url": "https://crm/q/a", "edit_uuid": "UU"})
    qb._zapisz_wycene(920, {"pozycje": [_poz()], "wspolne": {}}, {"finishing_options": []},
                      "jan@x.pl", None, "Jan")
    assert any("kod pocztowy" in r for r in replies)   # oferta wysylki poszla
    assert qb._awaiting_postcode(920) is True


def test_aktualizacja_nie_proponuje_wysylki_ponownie(monkeypatch):
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": True, "client": {"id": 42}})
    monkeypatch.setattr(qb.crm_calc, "update_quote",
                        lambda uid, p, o, **kw: {"ok": True, "quote_number": "W/1",
                                                 "public_url": "https://crm/q/a", "edit_uuid": "UU"})
    qb._set_edit_uuid(930, "UU")      # wycena juz istnieje w CRM
    qb._set_quote_saved(930, True)    # ...I klient JUZ raz widzial do niej link -> prawdziwa aktualizacja
    qb._zapisz_wycene(930, {"pozycje": [_poz()], "wspolne": {}}, {"finishing_options": []},
                      "jan@x.pl", None, "Jan")
    assert not any("kod pocztowy" in r for r in replies)
    assert qb._awaiting_postcode(930) is False


# --- przechwycenie kodu w pelnej turze ---

def test_run_quote_turn_lapie_kod_i_woła_wysylke(monkeypatch):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    called = {}
    # MS-12: flage awaiting_postcode gasi teraz _obsluz_wysylke (dopiero po udanej wysylce),
    # nie bramka — tu _obsluz_wysylke jest zamockowane, wiec sprawdzamy tylko, ze zostalo wolane.
    monkeypatch.setattr(qb, "_obsluz_wysylke", lambda c, kod: called.update(conv=c, kod=kod))
    qb._set_awaiting_postcode(940, True)
    qb.run_quote_turn(940, 5, "m1", "mój kod to 36-068")
    assert called == {"conv": 940, "kod": "36-068"}


def test_run_quote_turn_odmowa_kodu_respektuje(monkeypatch):
    replies = []
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "_obsluz_wysylke",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("nie liczymy wysylki przy odmowie")))
    qb._set_awaiting_postcode(941, True)
    qb.run_quote_turn(941, 5, "m1", "nie, dziękuję")
    assert qb._awaiting_postcode(941) is False
    assert any("konsultant" in r for r in replies)
