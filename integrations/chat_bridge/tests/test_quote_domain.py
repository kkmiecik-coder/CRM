# -*- coding: utf-8 -*-
# Test FAZA 0 zad. 6: walidacja domenowa po merge. API-01 (schody->handoff), API-02/MD-02 (ilosc),
# MD-01 (spojnosc finishing_id), MD-03 (wariant), MD-04 (kasowanie 'brak'), MD-05 (id spoza stanu),
# MD-07 (minima/pojedyncza liczba).
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qdom.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)

_OPTS = {"finishing_options": [{"id": 5, "full_path": "Lakierowane/Bezbarwne/mat", "price_netto": 10},
                               {"id": 7, "full_path": "Olejowanie/Bezbarwne", "price_netto": 10}]}


# ---- Walidacja domenowa (funkcja czysta) ----

def test_ilosc_niecalkowita_dopytaj():
    dane = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60",
                         "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
                         "ilosc": "2-3", "wykonczenie": "surowe"}], "wspolne": {}}
    msg = qb._walidacja_domenowa(dane, _OPTS)
    assert msg and "sztuk" in msg.lower()


def test_ilosc_z_jednostka_dopytaj():
    dane = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60",
                         "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
                         "ilosc": "2 szt.", "wykonczenie": "surowe"}], "wspolne": {}}
    assert qb._walidacja_domenowa(dane, _OPTS) is not None   # '2 szt.' nie parsuje sie do liczby


def test_wariant_niedostepny_jesion_bb():
    dane = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60",
                         "grubosc": "4", "gatunek": "jesion", "technologia": "lita", "klasa": "B/B",
                         "ilosc": "1", "wykonczenie": "surowe"}], "wspolne": {}}
    msg = qb._walidacja_domenowa(dane, _OPTS)
    assert msg == qb._ALT_NIEDOSTEPNY


def test_wymiar_ponizej_minimum_pyta_o_jednostki():
    dane = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "1,2", "szerokosc": "0,6",
                         "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
                         "ilosc": "1", "wykonczenie": "surowe"}], "wspolne": {}}
    msg = qb._walidacja_domenowa(dane, _OPTS)
    assert msg and ("centymetr" in msg.lower() or "milimetr" in msg.lower())


def test_wymiar_zakres_pyta_o_pojedyncza_liczbe():
    dane = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "120-140", "szerokosc": "60",
                         "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
                         "ilosc": "1", "wykonczenie": "surowe"}], "wspolne": {}}
    msg = qb._walidacja_domenowa(dane, _OPTS)
    assert msg and "liczb" in msg.lower()


def test_dane_poprawne_brak_zastrzezen():
    dane = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60",
                         "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
                         "ilosc": "2", "wykonczenie": "surowe"}], "wspolne": {}}
    assert qb._walidacja_domenowa(dane, _OPTS) is None


# ---- MD-01: spojnosc wykonczenie <-> finishing_id ----

def test_niespojny_finishing_id_wyczyszczony():
    dane = {"pozycje": [{"id": "1", "wykonczenie": "olejowane", "finishing_id": 5}], "wspolne": {}}  # 5=lakier
    zmiana = qb._wyczysc_niespojny_finishing(dane, _OPTS)
    assert zmiana is True
    assert not str(dane["pozycje"][0].get("finishing_id") or "").strip()


def test_spojny_finishing_id_zostaje():
    dane = {"pozycje": [{"id": "1", "wykonczenie": "olejowane", "finishing_id": 7}], "wspolne": {}}  # 7=olej
    assert qb._wyczysc_niespojny_finishing(dane, _OPTS) is False
    assert str(dane["pozycje"][0]["finishing_id"]) == "7"


# ---- MD-04: 'brak' kasuje pole ----

def test_brak_kasuje_pole():
    c = db_mod.db()
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (2001,))
    c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)",
              (2001, json.dumps({"pozycje": [{"id": "1", "produkt": "blat", "otwory": "2 otwory fi 35"}],
                                 "wspolne": {}})))
    c.commit(); c.close()
    stan = qb._merge_dane(2001, {"pozycje": [{"id": "1", "otwory": "brak"}], "wspolne": {}})
    assert not str(stan["pozycje"][0].get("otwory") or "").strip(), "otwory skasowane przez 'brak'"


# ---- MD-05b: wymyslone id spoza stanu nie tworzy duplikatu ----

def test_id_spoza_stanu_traktowany_jak_brak_id():
    c = db_mod.db()
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (2002,))
    c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)",
              (2002, json.dumps({"pozycje": [{"id": "1", "produkt": "blat", "szerokosc": "80"}],
                                 "wspolne": {}})))
    c.commit(); c.close()
    # LLM wymyslil id '9' dla istniejacego (jedynego) blata + korekta szerokosci
    stan = qb._merge_dane(2002, {"pozycje": [{"id": "9", "produkt": "blat", "szerokosc": "90"}], "wspolne": {}})
    assert len(stan["pozycje"]) == 1, "brak duplikatu z wymyslonym id"
    assert stan["pozycje"][0]["szerokosc"] == "90"


# ---- API-01: schody -> handoff po komplecie ----

def _patch(monkeypatch, replies):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [{"role": "user", "text": "tak"}])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {"name": "", "identifier": ""})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb, "chat", lambda messages, **kw:
                        ('{"odpowiedz":"","handoff":false,"pozycje":[],"wspolne":{}}', {"error_class": None}))
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: replies.append(text) or True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: replies.append("__HANDOFF__") or True)
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: replies.append("__NOTE__:" + text) or True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: _OPTS)


# (schody: zachowanie zmienione — wycena jak N desek + handoff tylko dla nietypowych;
#  pokrycie w test_quote_schody.py)
