# -*- coding: utf-8 -*-
# Test: dedup obrazow (sent_images) + wysylka 1a/1b w silniku live-bota.
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_liveimg.db")
os.environ["BOT_LIVE_CW_AGENT_TOKEN"] = "live-tok-img"
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db")
images = importlib.import_module("bots.images"); importlib.reload(images)
lc = importlib.import_module("bots.livechat"); importlib.reload(lc)

_IMG = None


def _plik(nazwa):
    with open(os.path.join(_IMG, nazwa), "wb") as f:
        f.write(b"\xff\xd8\xff")


def setup_function(_):
    # Swiezy katalog obrazow + env na kazdy test (images._dir() czyta env przy wywolaniu).
    global _IMG
    _IMG = tempfile.mkdtemp()
    os.environ["BOT_IMAGES_DIR"] = _IMG
    db_mod.init_db()
    c = db_mod.db()
    c.execute("DELETE FROM live_state"); c.execute("DELETE FROM live_dane")
    c.commit(); c.close()


def test_sent_images_pusty_gdy_brak():
    assert lc._sent_images(1) == set()


def test_mark_i_odczyt_sent_images():
    lc._mark_image_sent(1, "gatunki_porownanie")
    lc._mark_image_sent(1, "sample:dab|lity|ab|olejowane")
    assert lc._sent_images(1) == {"gatunki_porownanie", "sample:dab|lity|ab|olejowane"}


def _mock_env_img(monkeypatch, llm_json):
    calls = {"reply": []}
    monkeypatch.setattr(lc, "cw_conv_status", lambda cid: "pending")
    monkeypatch.setattr(lc, "cw_messages", lambda cid, lim: [{"role": "user", "text": "hej"}])
    monkeypatch.setattr(lc, "cw_contact", lambda cid: {"name": "", "identifier": ""})
    monkeypatch.setattr(lc, "retrieve", lambda q: ["wiedza"])
    monkeypatch.setattr(lc, "cw_bot_handoff", lambda cid, token=None: True)
    def fake_reply(cid, text, image_path=None, image_name=None, image_mime="image/jpeg"):
        calls["reply"].append({"text": text, "image_path": image_path})
        return True
    monkeypatch.setattr(lc, "cw_agent_reply", fake_reply)
    monkeypatch.setattr(lc, "chat", lambda messages, **kw: json.dumps(llm_json))
    return calls


def test_send_image_dolacza_obraz_raz(monkeypatch):
    _plik("gatunki_porownanie.jpg")
    calls = _mock_env_img(monkeypatch, {"odpowiedz": "Oto różnice.", "send_image": "gatunki_porownanie"})
    lc.run_livechat_turn(77, "12", "m1", "różnice gatunków?")
    assert len(calls["reply"]) == 1
    assert calls["reply"][0]["image_path"].endswith("gatunki_porownanie.jpg")
    assert "gatunki_porownanie" in lc._sent_images(77)
    # druga tura z tym samym tagiem -> obraz NIE leci ponownie
    lc.run_livechat_turn(77, "12", "m2", "a jeszcze raz pokaż")
    assert calls["reply"][1]["image_path"] is None


def test_send_image_nieznany_tag_bez_obrazu(monkeypatch):
    calls = _mock_env_img(monkeypatch, {"odpowiedz": "ok", "send_image": "nie_istnieje"})
    lc.run_livechat_turn(77, "12", "m1", "hej")
    assert calls["reply"][0]["image_path"] is None


def test_podsumowanie_dolacza_probke_konfiguracji(monkeypatch):
    _plik("dab_lity_ab_lakierowane.jpg")
    calls = {"reply": []}
    def fake_reply(cid, text, image_path=None, image_name=None, image_mime="image/jpeg"):
        calls["reply"].append({"text": text, "image_path": image_path}); return True
    monkeypatch.setattr(lc, "cw_agent_reply", fake_reply)
    dane = {"pozycje": [{"id": "1", "produkt": "blat", "gatunek": "dąb", "technologia": "lita",
                         "klasa": "A/B", "wykonczenie": "lakier", "ilosc": "1",
                         "dlugosc": "200", "szerokosc": "80", "grubosc": "3"}], "wspolne": {}}
    lc._merge_dane(77, {"odpowiedz": "", "handoff": False, "powod": "", "send_image": "",
                        "pozycje": dane["pozycje"], "wspolne": {}})
    lc._wyslij_podsumowanie(77, lc._load_dane(77))
    # 1. podsumowanie (tekst) + 2. probka (obraz)
    assert calls["reply"][0]["image_path"] is None
    assert "Podsumowuję dane do wyceny" in calls["reply"][0]["text"]
    assert calls["reply"][1]["image_path"].endswith("dab_lity_ab_lakierowane.jpg")
    assert "sample:dab|lity|ab|lakierowane" in lc._sent_images(77)


def test_podsumowanie_bez_pliku_probki_tylko_tekst(monkeypatch):
    calls = {"reply": []}
    def fake_reply(cid, text, image_path=None, image_name=None, image_mime="image/jpeg"):
        calls["reply"].append({"text": text, "image_path": image_path}); return True
    monkeypatch.setattr(lc, "cw_agent_reply", fake_reply)
    # buk lity lakierowane: brak pliku -> tylko tekst podsumowania
    poz = {"id": "1", "produkt": "blat", "gatunek": "buk", "technologia": "lity",
           "klasa": "AB", "wykonczenie": "lakierowane", "ilosc": "1",
           "dlugosc": "200", "szerokosc": "80", "grubosc": "3"}
    lc._merge_dane(77, {"odpowiedz": "", "handoff": False, "powod": "", "send_image": "",
                        "pozycje": [poz], "wspolne": {}})
    lc._wyslij_podsumowanie(77, lc._load_dane(77))
    assert len(calls["reply"]) == 1
    assert calls["reply"][0]["image_path"] is None
