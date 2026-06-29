# -*- coding: utf-8 -*-
import importlib
ds = importlib.import_module("setup.desired_state")


def test_labels_maja_tytul_i_kolor():
    assert {l["title"] for l in ds.LABELS} >= {
        "wycena", "dostępność-termin", "płatność-faktura",
        "transport-dostawa", "reklamacja", "techniczne",
        "nowy-kontakt", "pilne",
    }
    for l in ds.LABELS:
        assert l["color"].startswith("#")


def test_keywords_pokrywaja_etykiety_tematyczne():
    for t in ["wycena", "płatność-faktura", "reklamacja"]:
        assert ds.KEYWORDS[t], "brak slow-kluczy dla %s" % t


def test_label_payload_ma_show_on_sidebar():
    p = ds.label_payload({"title": "wycena", "color": "#1f9d55"})
    assert p["title"] == "wycena"
    assert p["color"] == "#1f9d55"
    assert p["show_on_sidebar"] is True


def test_topic_rule_dodaje_etykiete_i_zawiera_slowa():
    p = ds.topic_rule_payload("wycena", ["wycen", "cena"])
    assert p["event_name"] == "message_created"
    # akcja add_label z nazwa etykiety
    acts = p["actions"]
    assert any(a["action_name"] == "add_label" and "wycena" in a["action_params"] for a in acts)
    # warunek zawiera slowa-klucze
    assert "wycen" in str(p["conditions"])


def test_source_rule_wiaze_inbox_i_etykiete():
    p = ds.source_rule_payload("allegro", [4, 6])
    assert p["event_name"] == "conversation_created"
    cond = p["conditions"][0]
    assert cond["attribute_key"] == "inbox_id"
    assert cond["values"] == [4, 6]
    assert any(a["action_name"] == "add_label" and "allegro" in a["action_params"] for a in p["actions"])


def test_greeting_rule_jest_nieaktywna():
    p = ds.greeting_rule_payload("Dzien dobry!")
    assert p["active"] is False
    assert p["event_name"] == "conversation_created"
    assert any(a["action_name"] == "send_message" for a in p["actions"])


def test_b2c_default_dodaje_b2c():
    p = ds.b2c_default_rule_payload()
    assert p["event_name"] == "conversation_created"
    assert any(a["action_name"] == "add_label" and "b2c" in a["action_params"] for a in p["actions"])


def test_b2b_detect_dodaje_b2b_i_usuwa_b2c():
    p = ds.b2b_detect_rule_payload(ds.B2B_KEYWORDS)
    assert p["event_name"] == "message_created"
    acts = {a["action_name"]: a["action_params"] for a in p["actions"]}
    assert "b2b" in acts["add_label"]
    assert "b2c" in acts["remove_label"]
    assert "regon" in str(p["conditions"])


def test_folder_payload_ma_typ_conversation():
    p = ds.folder_payload("Pilne", [{"attribute_key": "labels"}])
    assert p["name"] == "Pilne"
    assert p["type"] == "conversation"
    assert "query" in p
