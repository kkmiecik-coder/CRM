# -*- coding: utf-8 -*-
# Deklaratywny stan docelowy konfiguracji Chatwoota + budowniczowie payloadow API.
# Bez I/O. Dokladne klucze pol potwierdzone rekonesansem (Task 1).
#
# === NOTATKA Z REKONESANSU (uzupelnic po Task 1) ===
# Inbox IDs: OLX=?, Allegro msg=4, Allegro dispute=6, email/www=?
# automation_rules: event_name / conditions / actions  -> potwierdzone: TAK/NIE
# custom_filters: type / query.payload                 -> potwierdzone: TAK/NIE
import os

# Inbox IDs potwierdzone rekonesansem (Task 1). Domyslne wartosci z konfiguracji
# mostka; uzupelnic realnymi po Task 1 (zwlaszcza OLX, ktory nie ma stalej w configu).
SOURCE_INBOXES = {
    "olx": int(os.environ.get("CHATWOOT_OLX_INBOX_ID", "3")),
    "allegro": int(os.environ.get("CHATWOOT_ALLEGRO_MSG_INBOX_ID", "4")),
}

# --- Etykiety ---
LABELS = [
    {"title": "wycena", "color": "#1f9d55"},
    {"title": "dostepnosc-termin", "color": "#3490dc"},
    {"title": "platnosc-faktura", "color": "#9561e2"},
    {"title": "transport-dostawa", "color": "#f6993f"},
    {"title": "reklamacja", "color": "#e3342f"},
    {"title": "techniczne", "color": "#8795a1"},
    {"title": "nowy-kontakt", "color": "#38c172"},
    {"title": "pilne", "color": "#e3342f"},
]

# --- Slowa-klucze (contains, bez ogonkow odmiany) ---
KEYWORDS = {
    "wycena": ["wycen", "ile kosztuje", "cena", "koszt", "oferta", "zapytanie"],
    "dostepnosc-termin": ["dostepn", "termin", "kiedy", "na kiedy", "czas realizacji", "ile czeka"],
    "platnosc-faktura": ["faktur", "platnos", "przelew", "zaplat", "proform", "paragon", "vat"],
    "transport-dostawa": ["transport", "dostaw", "wysylk", "kurier", "paczk", "odbior"],
    "reklamacja": ["reklamac", "uszkodz", "wadliw", "zwrot", "niezgodn", "skarg"],
    "techniczne": ["wymiar", "material", "grubosc", "kolor", "rozmiar", "wzor", "jak zamontow"],
    "pilne": ["pilne", "na juz", "dzisiaj", "asap", "jak najszybciej"],
}


def label_payload(label):
    return {"title": label["title"], "color": label["color"], "show_on_sidebar": True}


def _contains_conditions(keywords):
    # Lista warunkow "content contains X" laczona operatorem OR.
    conds = []
    for i, kw in enumerate(keywords):
        conds.append({
            "attribute_key": "content",
            "filter_operator": "contains",
            "values": [kw],
            "query_operator": "or" if i < len(keywords) - 1 else None,
        })
    return conds


def topic_rule_payload(label, keywords):
    return {
        "name": "Tag: %s" % label,
        "event_name": "message_created",
        "active": True,
        "conditions": _contains_conditions(keywords),
        "actions": [{"action_name": "add_label", "action_params": [label]}],
    }


def source_rule_payload(label, inbox_id):
    return {
        "name": "Zrodlo: %s" % label,
        "event_name": "conversation_created",
        "active": True,
        "conditions": [{
            "attribute_key": "inbox_id",
            "filter_operator": "equal_to",
            "values": [inbox_id],
            "query_operator": None,
        }],
        "actions": [{"action_name": "add_label", "action_params": [label]}],
    }


def new_contact_rule_payload():
    return {
        "name": "Tag: nowy-kontakt",
        "event_name": "conversation_created",
        "active": True,
        "conditions": [{
            "attribute_key": "status",
            "filter_operator": "equal_to",
            "values": ["open"],
            "query_operator": None,
        }],
        "actions": [{"action_name": "add_label", "action_params": ["nowy-kontakt"]}],
    }


def greeting_rule_payload(text):
    # Auto-powitanie: NIEAKTYWNE do czasu przepiecia z Responso.
    return {
        "name": "Auto: powitanie (wylaczone)",
        "event_name": "conversation_created",
        "active": False,
        "conditions": [{
            "attribute_key": "status",
            "filter_operator": "equal_to",
            "values": ["open"],
            "query_operator": None,
        }],
        "actions": [{"action_name": "send_message", "action_params": [text]}],
    }


def folder_payload(name, query_payload):
    return {
        "name": name,
        "type": "conversation",
        "query": {"payload": query_payload},
    }


# --- Foldery (custom_filters) ---
# Operatory/atrybuty potwierdzic rekonesansem; ponizej typowy Chatwoot.
FOLDERS = [
    {"name": "Nieodebrane", "query": [
        {"attribute_key": "status", "filter_operator": "equal_to", "values": ["open"], "query_operator": "and"},
        {"attribute_key": "assignee_id", "filter_operator": "is_not_present", "values": [], "query_operator": None},
    ]},
    {"name": "Czeka na klienta", "query": [
        {"attribute_key": "status", "filter_operator": "equal_to", "values": ["pending"], "query_operator": None},
    ]},
    {"name": "Pilne", "query": [
        {"attribute_key": "labels", "filter_operator": "equal_to", "values": ["pilne"], "query_operator": "and"},
        {"attribute_key": "status", "filter_operator": "equal_to", "values": ["open"], "query_operator": None},
    ]},
    {"name": "Zalegle", "query": [
        {"attribute_key": "status", "filter_operator": "equal_to", "values": ["open"], "query_operator": "and"},
        {"attribute_key": "last_activity_at", "filter_operator": "days_before", "values": [1], "query_operator": None},
    ]},
]
