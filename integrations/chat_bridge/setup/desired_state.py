# -*- coding: utf-8 -*-
# Deklaratywny stan docelowy konfiguracji Chatwoota + budowniczowie payloadow API.
# Bez I/O. Dokladne klucze pol potwierdzone rekonesansem (Task 1).
#
# === NOTATKA Z REKONESANSU (uzupelnic po Task 1) ===
# Inbox IDs: OLX=?, Allegro msg=4, Allegro dispute=6, email/www=?
# automation_rules: event_name / conditions / actions  -> potwierdzone: TAK/NIE
# custom_filters: type / query.payload                 -> potwierdzone: TAK/NIE
import os

# Inbox IDs potwierdzone rekonesansem (account 2, Chatwoot 4.12.1).
# Etykieta zrodlowa -> lista inboxow danego kanalu (allegro = wiadomosci 4 + dyskusje 6).
SOURCE_INBOXES = {
    "olx": [3],
    "allegro": [4, 6],
    "chat-live": [5],
}

# --- Etykiety ---
# Tematyczne (auto z tresci) + zrodlowe (auto z inboxa) + pomocnicze.
LABELS = [
    # tematyczne
    {"title": "wycena", "color": "#1f9d55"},
    {"title": "status-zamówienia", "color": "#6cb2eb"},
    {"title": "dostępność-termin", "color": "#3490dc"},
    {"title": "płatność-faktura", "color": "#9561e2"},
    {"title": "transport-dostawa", "color": "#f6993f"},
    {"title": "reklamacja", "color": "#e3342f"},
    {"title": "techniczne", "color": "#8795a1"},
    # zrodlowe (kanaly zbiorcze)
    {"title": "olx", "color": "#2d9b5a"},
    {"title": "allegro", "color": "#ff5a00"},
    {"title": "chat-live", "color": "#4dc0b5"},
    # segment klienta (b2b juz istnieje na koncie; tworzenie pominie dedup)
    {"title": "b2b", "color": "#2779bd"},
    {"title": "b2c", "color": "#bf9000"},
    # pomocnicze
    {"title": "nowy-kontakt", "color": "#38c172"},
    {"title": "pilne", "color": "#e3342f"},
]

# Frazy sygnalizujace klienta biznesowego (B2B). 'nip' zapisane z kontekstem,
# zeby nie lapac przypadkowych slow zawierajacych "nip".
B2B_KEYWORDS = ["numer nip", "nr nip", "nip:", " nip ", "faktura na firm", "fakture na firm",
                "na firmę", "na firme", "regon", "hurt", "wspolprac", "współprac",
                "dla firmy", "zakup na firm", "b2b"]

# --- Slowa-klucze (contains, bez ogonkow odmiany) ---
KEYWORDS = {
    "wycena": ["wycen", "ile kosztuje", "cena", "koszt", "oferta", "zapytanie"],
    "status-zamówienia": ["status zamowien", "gdzie zamowien", "gdzie jest moje", "numer zamowien",
                          "sledzen", "list przewozow", "numer przesylk", "kiedy dotrze",
                          "co z zamowieniem", "czy wyslal", "czy nadal"],
    "dostępność-termin": ["dostepn", "termin", "kiedy", "na kiedy", "czas realizacji", "ile czeka"],
    "płatność-faktura": ["faktur", "platnos", "przelew", "zaplat", "proform", "paragon", "vat"],
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
            "custom_attribute_type": "",
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


def source_rule_payload(label, inbox_ids):
    # inbox_ids: lista ID inboxow danego kanalu (np. allegro = [4, 6]).
    return {
        "name": "Zrodlo: %s" % label,
        "event_name": "conversation_created",
        "active": True,
        "conditions": [{
            "attribute_key": "inbox_id",
            "filter_operator": "equal_to",
            "values": list(inbox_ids),
            "query_operator": None,
            "custom_attribute_type": "",
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
            "custom_attribute_type": "",
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
            "custom_attribute_type": "",
        }],
        "actions": [{"action_name": "send_message", "action_params": [text]}],
    }


def b2c_default_rule_payload():
    # Domyslnie kazda nowa rozmowa = b2c (konsument). B2B nadpisze regula ponizej.
    return {
        "name": "Segment: domyslnie b2c",
        "event_name": "conversation_created",
        "active": True,
        "conditions": [{
            "attribute_key": "status",
            "filter_operator": "equal_to",
            "values": ["open"],
            "query_operator": None,
            "custom_attribute_type": "",
        }],
        "actions": [{"action_name": "add_label", "action_params": ["b2c"]}],
    }


def b2b_detect_rule_payload(keywords):
    # Gdy w tresci pojawi sie fraza biznesowa: dodaj b2b i zdejmij b2c.
    return {
        "name": "Segment: wykryto b2b (zamiana z b2c)",
        "event_name": "message_created",
        "active": True,
        "conditions": _contains_conditions(keywords),
        "actions": [
            {"action_name": "add_label", "action_params": ["b2b"]},
            {"action_name": "remove_label", "action_params": ["b2c"]},
        ],
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
    {"name": "🔴 Nieodebrane", "query": [
        {"attribute_key": "status", "filter_operator": "equal_to", "values": ["open"], "query_operator": "and"},
        {"attribute_key": "assignee_id", "filter_operator": "is_not_present", "values": [], "query_operator": None},
    ]},
    {"name": "⏳ Czeka na klienta", "query": [
        {"attribute_key": "status", "filter_operator": "equal_to", "values": ["pending"], "query_operator": None},
    ]},
    {"name": "🔥 Pilne", "query": [
        {"attribute_key": "labels", "filter_operator": "equal_to", "values": ["pilne"], "query_operator": "and"},
        {"attribute_key": "status", "filter_operator": "equal_to", "values": ["open"], "query_operator": None},
    ]},
    {"name": "⚠️ Zaległe", "query": [
        {"attribute_key": "status", "filter_operator": "equal_to", "values": ["open"], "query_operator": "and"},
        {"attribute_key": "last_activity_at", "filter_operator": "days_before", "values": [1], "query_operator": None},
    ]},
]
