# -*- coding: utf-8 -*-
# Silnik konwersacyjnego bota live-chat: publiczne odpowiedzi do klienta (RAG + persona livechat),
# decyzja o handoffie (wyzwalacze A/B/C/D ze specu), cisza po przekazaniu do agenta.
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
    '"technologia": "", "klasa": "", "ilosc": "", "wykonczenie": "", '
    '"otwory": "", "krawedzie": "", "schody": "", "termin": "", "kontakt": ""}}\n'
    "Ustaw handoff=true gdy: klient prosi o człowieka/konsultanta, pytanie wykracza poza "
    "podaną wiedzę, albo masz KOMPLET danych do wyceny wg checklisty z zasad. "
    "NIE ustawiaj handoff na samo pytanie o cenę — wtedy zbieraj brakujące dane do wyceny. "
    "W 'dane' uzupełniaj wszystko, co klient dotąd podał (całość rozmowy, nie tylko ostatnia "
    "wiadomość). Wymiary zapisuj w centymetrach. Pole 'schody' wypełniaj tylko dla produktu "
    "schody (liczba stopni, wymiar stopnia, podstopnice)."
)

# Twardy wyzwalacz A w kodzie (obok decyzji LLM): prosba o czlowieka.
# Wyzwalacz E (cena) USUNIETY — pytanie o cene uruchamia zbieranie danych (persona), nie handoff.
_HUMAN_RE = re.compile(r"\b(konsultant\w*|człowiek\w*|czlowiek\w*|doradc\w*|pracownik\w*|"
                       r"zadzwoń\w*|zadzwon\w*|oddzwon\w*)\b", re.IGNORECASE)


def _hard_handoff(text):
    """Zwraca powod handoffu gdy tresc klienta trafia w twardy wyzwalacz A, inaczej None."""
    t = text or ""
    if _HUMAN_RE.search(t):
        return "klient prosi o kontakt z konsultantem"
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
    """Parsuje odpowiedz LLM do dict. Toleruje ploty ```json (takze kilka blokow).
    Nie-JSON -> caly tekst jako odpowiedz."""
    txt = (raw or "").strip()
    candidates = re.findall(r"```(?:json)?\s*(.+?)\s*```", txt, re.DOTALL) or [txt]
    for cand in candidates:
        try:
            d = json.loads(cand)
            if not isinstance(d, dict):
                continue
            return {"odpowiedz": (d.get("odpowiedz") or "").strip(),
                    "handoff": bool(d.get("handoff")),
                    "powod": (d.get("powod") or "").strip(),
                    "dane": d.get("dane") if isinstance(d.get("dane"), dict) else {}}
        except Exception:
            continue
    # Fallback: model zignorowal format — traktujemy calosc jako tekst do klienta.
    return {"odpowiedz": txt, "handoff": False, "powod": "", "dane": {}}


_POLA = [("produkt", "Produkt"), ("wymiary", "Wymiary"), ("grubosc", "Grubość"),
         ("gatunek", "Gatunek"), ("technologia", "Technologia"), ("klasa", "Klasa"),
         ("ilosc", "Ilość"), ("wykonczenie", "Wykończenie"),
         ("otwory", "Otwory/wycięcia"), ("krawedzie", "Krawędzie"), ("schody", "Schody"),
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


# --- Straznik kompletnosci danych do wyceny (approach B ze specu) ---
# Pola krytyczne wspolne dla kazdego produktu. Wymiary/grubosc (blat/parapet) albo pole
# 'schody' (schody) dokladane sa zaleznie od typu produktu w _brakujace_pola.
_KRYT_WSPOLNE = ("gatunek", "technologia", "klasa", "ilosc", "wykonczenie", "otwory", "krawedzie")

# Powody handoffu, ktore straznik PRZEPUSZCZA (A: czlowiek, C: poza wiedza) — to nie sa
# roszczenia o "komplet danych", wiec brak pol nie moze ich blokowac.
_POWOD_PRZEPUSC = re.compile(
    r"(człowiek|czlowiek|konsultant|doradc|pracownik|poza (wiedz|zakres)|"
    r"nie wiem|nie potrafi|reklamacj)", re.IGNORECASE)

# Etykiety pol do backstopowego pytania o braki (gdy LLM ustawil handoff mimo brakow).
_ETYKIETY_PYTAN = {
    "produkt": "co dokładnie mamy wycenić (blat, parapet czy schody)",
    "wymiary": "wymiary (długość × szerokość w cm)",
    "grubosc": "grubość (w cm)",
    "gatunek": "gatunek drewna (dąb, jesion lub buk)",
    "technologia": "technologię (lita czy mikrowczep)",
    "klasa": "klasę drewna (A/B, a dla dębu również B/B)",
    "ilosc": "ilość (liczba sztuk)",
    "wykonczenie": "wykończenie (surowe, olejowane czy lakierowane)",
    "otwory": "czy potrzebne są otwory lub wycięcia",
    "krawedzie": "jak wykończyć krawędzie",
    "schody": "szczegóły schodów (liczba stopni, wymiar stopnia, podstopnice)",
}


def _brakujace_pola(dane):
    """Lista brakujacych pol krytycznych do wyceny dla wykrytego produktu
    (kolejnosc = kolejnosc dopytywania). Pusta lista = komplet."""
    dane = dane or {}
    def pusto(k):
        return not str(dane.get(k) or "").strip()
    produkt = str(dane.get("produkt") or "").strip().lower()
    if not produkt:
        return ["produkt"]  # najpierw ustal produkt; reszte pol dopytamy w kolejnej turze
    brak = []
    if "schod" in produkt or "stopni" in produkt or "stopie" in produkt:
        if pusto("schody"):
            brak.append("schody")
    else:
        for k in ("wymiary", "grubosc"):
            if pusto(k):
                brak.append(k)
    for k in _KRYT_WSPOLNE:
        if pusto(k):
            brak.append(k)
    return brak


def _czy_powod_kompletu(powod):
    """True gdy handoff to roszczenie o 'komplet danych' (B) — pilnuje go straznik.
    False dla prosby o czlowieka / pytania poza wiedza (A/C) — przepuszczamy zawsze."""
    return not _POWOD_PRZEPUSC.search(powod or "")


def _pytanie_o_braki(brak):
    """Backstop: krotkie pytanie o max 2 pierwsze brakujace pola (pacing 1-2 na ture)."""
    etyk = [_ETYKIETY_PYTAN.get(k, k) for k in brak[:2]]
    if len(etyk) == 1:
        return "Żeby przygotować wycenę, potrzebuję jeszcze: %s." % etyk[0]
    return "Żeby przygotować wycenę, potrzebuję jeszcze: %s oraz %s." % (etyk[0], etyk[1])


def _do_handoff(conv_id, powod, dane, closing=CLOSING_MSG):
    """Przekazanie rozmowy agentom: NAJPIERW toggle statusu (open), potem notatka i domkniecie.
    Kolejnosc celowa: gdy toggle padnie, rzucamy PRZED wyslaniem czegokolwiek do klienta —
    retry w workerze przebiega czysto, bez zdublowanych wiadomosci."""
    if not cw_bot_handoff(conv_id, token=BOT_LIVE_CW_AGENT_TOKEN):
        raise RuntimeError("livechat: handoff nieudany (conv %s)" % conv_id)
    # Reset licznika tur: gdy agent kiedys odda rozmowe botowi (open->pending), bot startuje od zera.
    c = db()
    c.execute("DELETE FROM live_state WHERE conv_id=?", (conv_id,))
    c.commit(); c.close()
    cw_note(conv_id, _summary_note(dane, powod))
    cw_agent_reply(conv_id, closing)
    log("livechat: handoff conv %s (%s)" % (conv_id, powod))


def run_livechat_turn(conv_id, inbox_id, message_id, content):
    """Pelna tura bota. Rzuca RuntimeError przy braku odpowiedzi LLM (retry w workerze)."""
    # Cisza po handoffie: bot prowadzi TYLKO rozmowy w statusie pending.
    status = cw_conv_status(conv_id)
    if status is None:
        # Nie zgadujemy: bez statusu nie wolno pisac do klienta — retry w workerze.
        raise RuntimeError("livechat: nie mozna odczytac statusu rozmowy (conv %s)" % conv_id)
    if status != "pending":
        log("livechat: conv %s status=%s - bot milczy" % (conv_id, status))
        return

    # Bezpiecznik D: limit tur bota.
    if _bot_turns(conv_id) >= BOT_LIVE_MAX_TURNS:
        _do_handoff(conv_id, "limit tur bota (bezpiecznik)", {})
        return

    # Twardy wyzwalacz A — deterministycznie, bez LLM.
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

    # Wyzwalacze B/C (decyzja LLM) + straznik kompletnosci.
    if out["handoff"]:
        powod = out["powod"] or "decyzja bota"
        brak = _brakujace_pola(out["dane"])
        # Handoff "komplet danych" (B) tylko gdy komplet; prosbe o czlowieka / poza wiedza
        # (A/C) przepuszczamy zawsze. Przy brakach nie oddajemy rozmowy — dopytujemy.
        if brak and _czy_powod_kompletu(powod):
            reply = _pytanie_o_braki(brak)
            if not cw_agent_reply(conv_id, reply):
                raise RuntimeError("livechat: wysylka pytania o braki nieudana (conv %s)" % conv_id)
            _bump_turns(conv_id)
            log("livechat: straznik wstrzymal handoff, braki: %s (conv %s)"
                % (",".join(brak), conv_id))
            return
        _do_handoff(conv_id, powod, out["dane"])
        return

    reply = out["odpowiedz"]
    if not reply:
        raise RuntimeError("livechat: pusta odpowiedz modelu")
    if not cw_agent_reply(conv_id, reply):
        raise RuntimeError("livechat: wysylka odpowiedzi nieudana (conv %s)" % conv_id)
    _bump_turns(conv_id)
    log("livechat: odpowiedz wyslana (conv %s, tura %s)" % (conv_id, _bot_turns(conv_id)))


def handoff_with_apology(conv_id):
    """Sciezka awaryjna (po wyczerpaniu retry): przeprosiny + przekazanie do agenta."""
    _do_handoff(conv_id, "błąd techniczny bota (wyczerpane próby)", {}, closing=APOLOGY_MSG)
