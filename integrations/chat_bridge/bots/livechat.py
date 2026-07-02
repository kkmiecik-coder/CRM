# -*- coding: utf-8 -*-
# Silnik konwersacyjnego bota live-chat: publiczne odpowiedzi do klienta (RAG + persona livechat),
# decyzja o handoffie (wyzwalacze A-E ze specu), cisza po przekazaniu do agenta.
# Rzuca wyjatkiem przy niepowodzeniu LLM; retry i sciezke awaryjna obsluguje live_worker.
import json
import re
from config import BOT_HISTORY_LIMIT, BOT_LIVE_MAX_TURNS, BOT_LIVE_CW_AGENT_TOKEN
from core.log import log
from core.db import db
from core.chatwoot import (cw_messages, cw_contact, cw_note, cw_agent_reply,
                           cw_conv_status, cw_bot_handoff)
from bots.knowledge import retrieve
from bots.personas import build_system_prompt
from bots.llm import chat

# Komunikaty stale (edytowalne). Bez obietnic czasowych — patrz spec §13.
CLOSING_MSG = "Dziękuję za informacje! Przekazuję rozmowę do konsultanta WoodPower — odpowiemy w tej rozmowie."
APOLOGY_MSG = ("Przepraszam, mam chwilowy problem techniczny z odpowiedzią. "
               "Przekazuję rozmowę do konsultanta WoodPower.")

# Instrukcja formatu odpowiedzi LLM — doklejana do promptu systemowego persony.
_FORMAT = (
    "FORMAT ODPOWIEDZI: odpowiedz WYŁĄCZNIE poprawnym JSON (bez tekstu przed/po):\n"
    '{"odpowiedz": "tekst do klienta", "handoff": false, "powod": "", '
    '"dane": {"produkt": "", "wymiary": "", "grubosc": "", "gatunek": "", '
    '"wykonczenie": "", "ilosc": "", "termin": "", "kontakt": ""}}\n'
    "Ustaw handoff=true gdy: klient prosi o człowieka/konsultanta, pyta o cenę, "
    "pytanie wykracza poza podaną wiedzę, albo masz komplet danych do wyceny. "
    "W 'dane' uzupełniaj wszystko, co klient dotąd podał (całość rozmowy, nie tylko ostatnia wiadomość)."
)

# Twarde wyzwalacze w kodzie (podwojne zabezpieczenie obok decyzji LLM):
# E — temat ceny; A — prosba o czlowieka.
_PRICE_RE = re.compile(r"\b(cen\w*|koszt\w*|ile\s+kosztuje|wycen\w*|drogo|tanio)\b", re.IGNORECASE)
_HUMAN_RE = re.compile(r"\b(konsultant\w*|człowiek\w*|czlowiek\w*|doradc\w*|pracownik\w*|"
                       r"zadzwoń\w*|zadzwon\w*|oddzwon\w*)\b", re.IGNORECASE)


def _hard_handoff(text):
    """Zwraca powod handoffu gdy tresc klienta trafia w twardy wyzwalacz, inaczej None."""
    t = text or ""
    if _HUMAN_RE.search(t):
        return "klient prosi o kontakt z konsultantem"
    if _PRICE_RE.search(t):
        return "pytanie o cenę"
    return None


def _bot_turns(conv_id):
    """Aktualny licznik tur bota dla rozmowy (0 gdy brak wpisu)."""
    c = db()
    row = c.execute("SELECT bot_turns FROM live_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    return row["bot_turns"] if row else 0


def _bump_turns(conv_id):
    """Inkrementuje licznik tur bota (INSERT lub UPDATE)."""
    c = db()
    c.execute("INSERT INTO live_state(conv_id, bot_turns) VALUES(?,1) "
              "ON CONFLICT(conv_id) DO UPDATE SET bot_turns=bot_turns+1", (conv_id,))
    c.commit(); c.close()


def _parse_llm(raw):
    """Parsuje odpowiedz LLM do dict. Toleruje ploty ```json. Nie-JSON -> caly tekst jako odpowiedz."""
    txt = (raw or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", txt, re.DOTALL)
    if m:
        txt = m.group(1)
    try:
        d = json.loads(txt)
        if not isinstance(d, dict):
            raise ValueError("nie-obiekt")
        return {"odpowiedz": (d.get("odpowiedz") or "").strip(),
                "handoff": bool(d.get("handoff")),
                "powod": (d.get("powod") or "").strip(),
                "dane": d.get("dane") if isinstance(d.get("dane"), dict) else {}}
    except Exception:
        # Fallback: model zignorowal format — traktujemy calosc jako tekst do klienta.
        return {"odpowiedz": txt, "handoff": False, "powod": "", "dane": {}}


_POLA = [("produkt", "Produkt"), ("wymiary", "Wymiary"), ("grubosc", "Grubość"),
         ("gatunek", "Gatunek"), ("wykonczenie", "Wykończenie"), ("ilosc", "Ilość"),
         ("termin", "Termin"), ("kontakt", "Kontakt")]


def _summary_note(dane, powod):
    """Prywatna notatka-podsumowanie dla agenta po handoffie."""
    dane = dane or {}
    lines = ["🤖 Bot live-chat — przekazanie do konsultanta", "Powód: %s" % (powod or "-")]
    for key, label in _POLA:
        v = (dane.get(key) or "").strip()
        if v:
            lines.append("%s: %s" % (label, v))
    return "\n".join(lines)


def _do_handoff(conv_id, powod, dane, closing=CLOSING_MSG):
    """Przekazanie rozmowy agentom: NAJPIERW toggle statusu (open), potem notatka i domkniecie.
    Kolejnosc celowa: gdy toggle padnie, rzucamy PRZED wyslaniem czegokolwiek do klienta —
    retry w workerze przebiega czysto, bez zdublowanych wiadomosci."""
    if not cw_bot_handoff(conv_id, token=BOT_LIVE_CW_AGENT_TOKEN):
        raise RuntimeError("livechat: handoff nieudany (conv %s)" % conv_id)
    cw_note(conv_id, _summary_note(dane, powod))
    cw_agent_reply(conv_id, closing)
    log("livechat: handoff conv %s (%s)" % (conv_id, powod))


def run_livechat_turn(conv_id, inbox_id, message_id, content):
    """Pelna tura bota. Rzuca RuntimeError przy braku odpowiedzi LLM (retry w workerze)."""
    # Cisza po handoffie: bot prowadzi TYLKO rozmowy w statusie pending.
    # None (blad API) traktujemy jak pending — wysylka i tak by wtedy padla, retry w workerze.
    status = cw_conv_status(conv_id)
    if status is not None and status != "pending":
        log("livechat: conv %s status=%s - bot milczy" % (conv_id, status))
        return

    # Bezpiecznik D: limit tur bota.
    if _bot_turns(conv_id) >= BOT_LIVE_MAX_TURNS:
        _do_handoff(conv_id, "limit tur bota (bezpiecznik)", {})
        return

    # Twarde wyzwalacze A/E — deterministycznie, bez LLM.
    powod = _hard_handoff(content)
    if powod:
        _do_handoff(conv_id, powod, {})
        return

    history = cw_messages(conv_id, BOT_HISTORY_LIMIT)
    identity = cw_contact(conv_id)
    query = (content or "").strip() or (history[-1]["text"] if history else "")
    knowledge = "\n\n".join(retrieve(query))
    system = build_system_prompt("livechat", knowledge, identity) + "\n\n" + _FORMAT

    messages = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["text"]} for m in history]
    if not history and (content or "").strip():
        messages.append({"role": "user", "content": content})

    raw = chat(messages)
    if not raw:
        raise RuntimeError("livechat: brak odpowiedzi modelu")
    out = _parse_llm(raw)

    # Wyzwalacze B/C (decyzja LLM).
    if out["handoff"]:
        _do_handoff(conv_id, out["powod"] or "decyzja bota", out["dane"])
        return

    reply = out["odpowiedz"]
    if not reply:
        raise RuntimeError("livechat: pusta odpowiedz modelu")
    cw_agent_reply(conv_id, reply)
    _bump_turns(conv_id)
    log("livechat: odpowiedz wyslana (conv %s, tura %s)" % (conv_id, _bot_turns(conv_id)))


def handoff_with_apology(conv_id):
    """Sciezka awaryjna (po wyczerpaniu retry): przeprosiny + przekazanie do agenta."""
    _do_handoff(conv_id, "błąd techniczny bota (wyczerpane próby)", {}, closing=APOLOGY_MSG)
