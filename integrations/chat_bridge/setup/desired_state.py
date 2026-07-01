# -*- coding: utf-8 -*-
# Deklaratywny stan docelowy konfiguracji Chatwoota + budowniczowie payloadow API.
# Bez I/O. Dokladne klucze pol potwierdzone rekonesansem (Task 1).
#
# === NOTATKA Z REKONESANSU (uzupelnic po Task 1) ===
# Inbox IDs: OLX=?, Allegro msg=4, Allegro dispute=6, email/www=?
# automation_rules: event_name / conditions / actions  -> potwierdzone: TAK/NIE
# custom_filters: type / query.payload                 -> potwierdzone: TAK/NIE
import os

# --- Etykiety ---
# Tematyczne (auto z tresci) + segment + pomocnicze.
# (Etykiet zrodlowych olx/allegro/chat-live NIE ma - kanal widac przy ticketcie.)
LABELS = [
    # tematyczne
    {"title": "wycena", "color": "#1f9d55"},
    {"title": "status-zamówienia", "color": "#6cb2eb"},
    {"title": "dostępność-termin", "color": "#3490dc"},
    {"title": "płatność-faktura", "color": "#9561e2"},
    {"title": "transport-dostawa", "color": "#f6993f"},
    {"title": "reklamacja", "color": "#e3342f"},
    {"title": "techniczne", "color": "#8795a1"},
    # segment klienta (b2b juz istnieje na koncie; tworzenie pominie dedup)
    {"title": "b2b", "color": "#2779bd"},
    {"title": "b2c", "color": "#bf9000"},
    {"title": "wewnetrzny", "color": "#606f7b"},
    # pomocnicze
    {"title": "nowy-kontakt", "color": "#38c172"},
    {"title": "pilne", "color": "#e3342f"},
]

# Domeny wewnetrzne (grupa) - maile od nich to korespondencja pracownicza,
# NIE klienci: oznaczamy 'wewnetrzny' i zdejmujemy wszystkie auto-etykiety.
INTERNAL_DOMAINS = ["@woodpower.pl", "@office360circus.pl", "@360circus.pl", "@rsholding.com.pl"]

# Etykiety tematyczne (do zdjecia z maili wewnetrznych).
TOPIC_LABELS = ["wycena", "status-zamówienia", "dostępność-termin", "płatność-faktura",
                "transport-dostawa", "reklamacja", "techniczne"]

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


def _exclude_internal(conditions):
    # Doklej warunki "email NIE zawiera domeny grupowej" (AND) do listy warunkow.
    # Dzieki temu reguly klienckie NIE odpalaja sie dla poczty wewnetrznej -
    # deterministycznie, bez usuwania etykiet po fakcie. Chatwoot sklada warunki
    # lewostronnie: (kw1 OR kw2 ... ) AND not_dom1 AND not_dom2 ...
    if conditions:
        conditions[-1] = dict(conditions[-1], query_operator="and")
    tail = []
    for i, dom in enumerate(INTERNAL_DOMAINS):
        tail.append({
            "attribute_key": "email",
            "filter_operator": "does_not_contain",
            "values": [dom],
            "query_operator": "and" if i < len(INTERNAL_DOMAINS) - 1 else None,
            "custom_attribute_type": "",
        })
    return conditions + tail


def _contains_conditions(values, attribute="content"):
    # Lista warunkow "<attribute> contains X" laczona operatorem OR.
    conds = []
    for i, v in enumerate(values):
        conds.append({
            "attribute_key": attribute,
            "filter_operator": "contains",
            "values": [v],
            "query_operator": "or" if i < len(values) - 1 else None,
            "custom_attribute_type": "",
        })
    return conds


def topic_rule_payload(label, keywords):
    return {
        "name": "Tag: %s" % label,
        "event_name": "message_created",
        "active": True,
        "conditions": _exclude_internal(_contains_conditions(keywords)),
        "actions": [{"action_name": "add_label", "action_params": [label]}],
    }


def new_contact_rule_payload():
    return {
        "name": "Tag: nowy-kontakt",
        "event_name": "conversation_created",
        "active": True,
        "conditions": _exclude_internal([{
            "attribute_key": "status",
            "filter_operator": "equal_to",
            "values": ["open"],
            "query_operator": None,
            "custom_attribute_type": "",
        }]),
        "actions": [{"action_name": "add_label", "action_params": ["nowy-kontakt"]}],
    }


# Auto-powitanie WYLACZNIE dla kanalow OLX + Allegro (NIGDY mail/czat) -
# na poczcie traffiaja tez maile wewnetrzne pracownik<->pracownik, ktorym
# nie wolno auto-odpowiadac. OLX=3, Allegro wiadomosci=4, Allegro dyskusje=6.
AUTORESPONDER_INBOXES = [3, 4, 6]

# Skrzynki imienne - maja wlasne reguly przypisania (inbox 16->Anna, 17->Sylwester),
# wiec wykluczamy je z "przypisz do tego, kto odpisal".
PERSONAL_INBOXES = [16, 17]


def assign_on_reply_rule_payload(personal_inboxes):
    # Gdy agent odpisze na NIEPRZYPISANA rozmowe (poza skrzynkami imiennymi),
    # przypisz ja do niego (last_responding_agent). Po przypisaniu warunek
    # "assignee brak" przestaje pasowac, wiec regula nie zapetla sie.
    conds = [{
        "attribute_key": "assignee_id",
        "filter_operator": "is_not_present",
        "values": [],
        "query_operator": "and",
        "custom_attribute_type": "",
    }]
    for i, inbox_id in enumerate(personal_inboxes):
        conds.append({
            "attribute_key": "inbox_id",
            "filter_operator": "not_equal_to",
            "values": [inbox_id],
            "query_operator": "and" if i < len(personal_inboxes) - 1 else None,
            "custom_attribute_type": "",
        })
    return {
        "name": "Auto-przypisz do odpowiadajacego (nieprzypisane)",
        "event_name": "conversation_updated",
        "active": True,
        "conditions": conds,
        "actions": [{"action_name": "assign_agent", "action_params": ["last_responding_agent"]}],
    }

# Jeden komunikat na kazda nowa rozmowe OLX/Allegro (decyzja: bez osobnego OOO -
# tekst sam wspomina godziny pracy). Wysylany dopiero po wlaczeniu reguly.
GREETING_TEXT = (
    "Witamy,\n\n"
    "Dziękujemy za kontakt! Otrzymaliśmy Twoją wiadomość i odpowiemy na nią "
    "najszybciej, jak to możliwe. Nasze Biuro Obsługi Klienta pracuje w godzinach "
    "8:00 - 16:00 od poniedziałku do piątku.\n\n"
    "Pozdrawiamy\n"
    "Zespół WoodPower\n"
    "[Wiadomość wysłana automatycznie]"
)


def greeting_rule_payload(text):
    # Auto-powitanie: NIEAKTYWNE do czasu przepiecia z Responso; tylko OLX/Allegro.
    return {
        "name": "Auto: powitanie (wylaczone)",
        "event_name": "conversation_created",
        "active": False,
        "conditions": [{
            "attribute_key": "inbox_id",
            "filter_operator": "equal_to",
            "values": list(AUTORESPONDER_INBOXES),
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
        "conditions": _exclude_internal([{
            "attribute_key": "status",
            "filter_operator": "equal_to",
            "values": ["open"],
            "query_operator": None,
            "custom_attribute_type": "",
        }]),
        "actions": [{"action_name": "add_label", "action_params": ["b2c"]}],
    }


def b2b_detect_rule_payload(keywords):
    # Gdy w tresci pojawi sie fraza biznesowa: dodaj b2b i zdejmij b2c.
    return {
        "name": "Segment: wykryto b2b (zamiana z b2c)",
        "event_name": "message_created",
        "active": True,
        "conditions": _exclude_internal(_contains_conditions(keywords)),
        "actions": [
            {"action_name": "add_label", "action_params": ["b2b"]},
            {"action_name": "remove_label", "action_params": ["b2c"]},
        ],
    }


def internal_rule_payload(domains):
    # Mail od nadawcy z domeny grupowej: oznacz 'wewnetrzny'. TYLKO dodanie -
    # reguly klienckie (b2c/nowy-kontakt/tematyczne) maja juz wykluczenie tych
    # domen, wiec nie ma czego usuwac (i nie ma wyscigu nadpisujacego etykiety).
    return {
        "name": "Segment: wykryto wewnetrzny (grupa)",
        "event_name": "message_created",
        "active": True,
        "conditions": _contains_conditions(domains, attribute="email"),
        "actions": [{"action_name": "add_label", "action_params": ["wewnetrzny"]}],
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
    {"name": "🏢 Wewnętrzne", "query": [
        {"attribute_key": "labels", "filter_operator": "equal_to", "values": ["wewnetrzny"], "query_operator": None},
    ]},
]
