# -*- coding: utf-8 -*-
# Test FAZA 1a: wielopozycyjnosc — kilka produktow o TEJ SAMEJ nazwie w jednej wycenie.
# Root cause MD-05c: _merge_dane zwijal kolejny produkt tej samej nazwy w istniejacy
# (nowe id resetowane jako "zmyslone" -> fallback-po-nazwie nadpisywal wymiary).
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qmp.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)


def _reset(conv_id):
    c = db_mod.db()
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (conv_id,))
    c.commit(); c.close()


def test_cztery_parapety_tej_samej_nazwy_nie_zwijaja_sie():
    """Transkrypt 2026-07-10: 4 parapety roznych wymiarow -> 4 osobne pozycje, nie 1.
    Kazdy przychodzi w osobnej turze z kolejnym id (jak robi LLM tura po turze)."""
    conv = 3101
    _reset(conv)
    wymiary = [("120", "35", "3"), ("120", "30", "3"), ("120", "30", "2"), ("150", "35", "2")]
    for i, (d, s, g) in enumerate(wymiary, 1):
        qb._merge_dane(conv, {"pozycje": [{"id": str(i), "produkt": "parapet",
                              "dlugosc": d, "szerokosc": s, "grubosc": g}], "wspolne": {}})
    stan = qb._load_dane(conv)
    assert len(stan["pozycje"]) == 4, "kazdy parapet to osobna pozycja"
    assert [(p["dlugosc"], p["szerokosc"], p["grubosc"]) for p in stan["pozycje"]] == wymiary


def test_dwa_parapety_w_jednej_wiadomosci():
    """Dwa produkty tej samej nazwy w JEDNEJ turze LLM -> dwie pozycje."""
    conv = 3103
    _reset(conv)
    qb._merge_dane(conv, {"pozycje": [
        {"id": "1", "produkt": "parapet", "dlugosc": "120", "szerokosc": "35", "grubosc": "3"},
        {"id": "2", "produkt": "parapet", "dlugosc": "150", "szerokosc": "35", "grubosc": "2"},
    ], "wspolne": {}})
    stan = qb._load_dane(conv)
    assert len(stan["pozycje"]) == 2


def test_korekta_pojedynczego_wymiaru_nie_tworzy_nowej_pozycji():
    """Delta czesciowa bez id (korekta 1 wymiaru) scala sie w istniejaca pozycje, nie duplikuje."""
    conv = 3102
    _reset(conv)
    qb._merge_dane(conv, {"pozycje": [{"id": "1", "produkt": "parapet", "dlugosc": "120",
                          "szerokosc": "35", "grubosc": "3"}], "wspolne": {}})
    qb._merge_dane(conv, {"pozycje": [{"produkt": "parapet", "szerokosc": "40"}], "wspolne": {}})
    stan = qb._load_dane(conv)
    assert len(stan["pozycje"]) == 1, "korekta pojedynczego wymiaru = ta sama pozycja"
    assert stan["pozycje"][0]["szerokosc"] == "40"


def test_nowy_produkt_z_wymyslonym_id_i_wlasnymi_wymiarami():
    """LLM nadaje nowe id spoza stanu + wlasny komplet wymiarow -> nowy produkt (nie zwiniecie)."""
    conv = 3104
    _reset(conv)
    qb._merge_dane(conv, {"pozycje": [{"id": "1", "produkt": "parapet", "dlugosc": "120",
                          "szerokosc": "35", "grubosc": "3"}], "wspolne": {}})
    qb._merge_dane(conv, {"pozycje": [{"id": "2", "produkt": "parapet", "dlugosc": "120",
                          "szerokosc": "30", "grubosc": "2"}], "wspolne": {}})
    stan = qb._load_dane(conv)
    assert len(stan["pozycje"]) == 2
