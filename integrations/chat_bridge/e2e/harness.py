# -*- coding: utf-8 -*-
"""Silnik E2E quote-bota: wstrzykuje tury klienta przez Chatwoot Application API na skrzynke
testowa (inbox 18), deterministycznie wyzwala webhook kandydata (/agent-bot-quote), czeka na
odpowiedz bota (polling) i ocenia scenariusz wg pola `oczekuj`.

Konfiguracja przez ENV (najprosciej uruchamiac w kontenerze z --env-file bridge-candidate.env,
zeby sekrety NIE trafialy do argv/logow):
  CHATWOOT_BASE            baza API (w sieci dockera: http://rails:3000)
  CHATWOOT_ACCOUNT_ID      konto (2)
  CHATWOOT_API_TOKEN       token agenta/admina z dostepem do inboxu 18 (odczyt+wstrzykiwanie)
  BOT_QUOTE_AGENT_WEBHOOK_TOKEN  token webhooka quote-bota (do wyzwalania /agent-bot-quote)
  E2E_INBOX_ID             domyslnie 18
  E2E_WEBHOOK_URL          domyslnie http://quotebot-candidate:5006/agent-bot-quote
  E2E_POLL_TIMEOUT         maks. sekund oczekiwania na odpowiedz bota na ture (domyslnie 60)
  E2E_FIRE_WEBHOOK         "1" (domyslnie) = wyzwalaj webhook recznie; "0" = polegaj na auto-fire Chatwoota
  E2E_MSG_PREFIX           prefiks nazwy kontaktu testowego (domyslnie "E2E")
"""
import os
import re
import time
import json
import html
import requests

CW_BASE = os.environ.get("CHATWOOT_BASE", "http://rails:3000").rstrip("/")
CW_ACC = os.environ.get("CHATWOOT_ACCOUNT_ID", "2")
CW_TOKEN = os.environ["CHATWOOT_API_TOKEN"]
INBOX_ID = int(os.environ.get("E2E_INBOX_ID", "18"))
WEBHOOK_URL = os.environ.get("E2E_WEBHOOK_URL", "http://quotebot-candidate:5006/agent-bot-quote")
WEBHOOK_TOKEN = os.environ.get("BOT_QUOTE_AGENT_WEBHOOK_TOKEN", "")
POLL_TIMEOUT = float(os.environ.get("E2E_POLL_TIMEOUT", "60"))
POLL_INTERVAL = 1.5
SETTLE_QUIET = 5.0   # gdy przez tyle sekund nie przybyla nowa wiadomosc bota -> tura ustabilizowana
FIRE_WEBHOOK = os.environ.get("E2E_FIRE_WEBHOOK", "1") == "1"
MSG_PREFIX = os.environ.get("E2E_MSG_PREFIX", "E2E")


class HarnessError(RuntimeError):
    pass


def _api(method, path, **kw):
    url = "%s/api/v1/accounts/%s%s" % (CW_BASE, CW_ACC, path)
    h = {"api_access_token": CW_TOKEN, "Content-Type": "application/json"}
    r = requests.request(method, url, headers=h, timeout=30, **kw)
    if r.status_code >= 400:
        raise HarnessError("API %s %s -> %s: %s" % (method, path, r.status_code, r.text[:300]))
    return r.json() if r.text.strip() else {}


def _txt(s):
    """HTML -> czysty tekst (bot czasem zwraca <br>/encje); do asercji i podgladu."""
    s = s or ""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s)


# ---------- tworzenie rozmowy ----------

def utworz_rozmowe(nazwa, email=None):
    """Tworzy kontakt (z source_id w inboxie 18) i rozmowe w statusie 'pending'.
    Zwraca (conv_id, contact_id, source_id)."""
    payload = {"inbox_id": INBOX_ID, "name": nazwa}
    if email:
        payload["email"] = email
    d = _api("POST", "/contacts", json=payload)
    p = d.get("payload") or d
    contact = p.get("contact") or p
    contact_id = contact.get("id")
    ci = p.get("contact_inbox") or {}
    source_id = ci.get("source_id")
    if not source_id:
        # niektore wersje zwracaja contact_inboxes na kontakcie
        for x in (contact.get("contact_inboxes") or []):
            if x.get("source_id"):
                source_id = x["source_id"]
                break
    if not contact_id or not source_id:
        raise HarnessError("brak contact_id/source_id w odpowiedzi POST /contacts: %s" % json.dumps(d)[:400])
    conv = _api("POST", "/conversations",
                json={"source_id": source_id, "inbox_id": INBOX_ID,
                      "contact_id": contact_id, "status": "pending"})
    conv_id = conv.get("id") or (conv.get("payload") or {}).get("id")
    if not conv_id:
        raise HarnessError("brak id rozmowy w odpowiedzi POST /conversations: %s" % json.dumps(conv)[:400])
    # upewnij sie, ze pending (bot dziala tylko na pending)
    try:
        _api("POST", "/conversations/%s/toggle_status" % conv_id, json={"status": "pending"})
    except Exception:
        pass
    return conv_id, contact_id, source_id


def status_rozmowy(conv_id):
    d = _api("GET", "/conversations/%s" % conv_id)
    return d.get("status") or (d.get("meta") or {}).get("status") or (d.get("payload") or {}).get("status")


def _wiadomosci(conv_id):
    d = _api("GET", "/conversations/%s/messages" % conv_id)
    return d.get("payload") or d.get("data") or []


def wyslij_ture(conv_id, tekst):
    """Wstrzykuje wiadomosc KLIENTA (incoming). Zwraca message_id."""
    d = _api("POST", "/conversations/%s/messages" % conv_id,
             json={"content": tekst, "message_type": "incoming"})
    mid = d.get("id") or (d.get("payload") or {}).get("id")
    if not mid:
        raise HarnessError("brak id wiadomosci po wstrzyknieciu: %s" % json.dumps(d)[:300])
    return mid


def wyzwol_webhook(conv_id, mid, tekst):
    """Deterministycznie wyzwala ture bota (obok ewentualnego auto-fire Chatwoota; dedup po mid
    w quote_seen chroni przed podwojnym przetworzeniem)."""
    url = WEBHOOK_URL
    if WEBHOOK_TOKEN:
        url += ("&" if "?" in url else "?") + "token=" + WEBHOOK_TOKEN
    body = {"event": "message_created", "message_type": "incoming",
            "id": mid, "content": tekst,
            "conversation": {"id": conv_id, "inbox_id": INBOX_ID},
            "inbox_id": INBOX_ID, "attachments": []}
    try:
        requests.post(url, json=body, timeout=15)
    except Exception as e:
        # nie przerywamy — auto-fire Chatwoota moze i tak zadzialac
        print("   [uwaga] webhook nieudany: %r" % e)


def czekaj_na_odpowiedz(conv_id, znane_ids):
    """Czeka na nowe PUBLICZNE odpowiedzi bota (i notatki) po turze. Zwraca
    (nowe_publiczne:list[str], nowe_notatki:list[str], status:str, wszystkie_ids:set)."""
    t0 = time.monotonic()
    ostatnia_zmiana = t0
    pub, notatki = [], []
    widziane = set(znane_ids)
    while time.monotonic() - t0 < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        try:
            msgs = _wiadomosci(conv_id)
        except Exception as e:
            print("   [uwaga] odczyt wiadomosci nieudany: %r" % e)
            continue
        cos_nowego = False
        for m in msgs:
            mid = m.get("id")
            if mid in widziane:
                continue
            widziane.add(mid)
            mtype = m.get("message_type")
            priv = bool(m.get("private"))
            tresc = _txt(m.get("content"))
            # incoming (klient) = 0/"incoming" -> pomijamy; interesuja nas outgoing bota
            if mtype in (0, "incoming"):
                continue
            if mtype in (2, "activity"):
                continue
            if not tresc.strip():
                continue
            if priv:
                notatki.append(tresc)
            else:
                pub.append(tresc)
            cos_nowego = True
        if cos_nowego:
            ostatnia_zmiana = time.monotonic()
        # ustabilizowanie: mamy jakas publiczna odpowiedz i cisza przez SETTLE_QUIET
        if pub and (time.monotonic() - ostatnia_zmiana) >= SETTLE_QUIET:
            break
    st = None
    try:
        st = status_rozmowy(conv_id)
    except Exception:
        pass
    return pub, notatki, st, widziane


# ---------- ocena ----------

def ocen(sc, pub_all, notatki_all, status_koniec):
    """Zwraca (werdykt, powody). werdykt: PASS | FAIL | REVIEW.
    Deterministyczne asercje z `oczekuj`; scenariusz z `human` -> co najwyzej REVIEW."""
    o = sc.get("oczekuj") or {}
    powody = []
    polaczone = "\n".join(pub_all).lower()
    ostatnia = (pub_all[-1] if pub_all else "").lower()

    min_odp = o.get("min_odp", 1)
    if len(pub_all) < min_odp:
        powody.append("za malo odpowiedzi bota: %d < %d (cisza?)" % (len(pub_all), min_odp))

    for sub in o.get("zawiera", []):
        if sub.lower() not in polaczone:
            powody.append("brak wymaganego fragmentu: %r" % sub)

    for sub in o.get("zawiera_ost", []):
        if sub.lower() not in ostatnia:
            powody.append("ostatnia odpowiedz nie zawiera: %r" % sub)

    for sub in o.get("nie_zawiera", []):
        if sub.lower() in polaczone:
            powody.append("wystapil zakazany fragment: %r" % sub)

    if "status" in o and status_koniec and status_koniec != o["status"]:
        powody.append("status %r != oczekiwany %r" % (status_koniec, o["status"]))

    if o.get("notatka") and not notatki_all:
        powody.append("brak prywatnej notatki (oczekiwano handoffu z notatka)")

    if powody:
        return "FAIL", powody
    if sc.get("human"):
        return "REVIEW", ["do oceny czlowieka: " + sc["human"]]
    return "PASS", []


# ---------- orkiestracja scenariusza ----------

def uruchom_scenariusz(sc, idx=None, total=None):
    """Uruchamia jeden scenariusz od zera (swiezy kontakt/rozmowa). Zwraca dict wyniku."""
    naglowek = "[%s/%s] " % (idx, total) if idx else ""
    print("%s%s %s — %s" % (naglowek, sc["id"], sc.get("kat", ""), sc.get("tytul", "")))
    nazwa = "%s %s %s" % (MSG_PREFIX, sc["id"], int(time.time()))
    email = None
    # scenariusze z jawnym mailem w tresci nie wymagaja maila kontaktu; kontakt tworzymy bez maila
    conv_id, contact_id, _ = utworz_rozmowe(nazwa, email)
    transkrypt = []
    pub_all, notatki_all = [], []
    widziane = set()
    status_koniec = None
    for i, tura in enumerate(sc["tury"], 1):
        mid = wyslij_ture(conv_id, tura)
        if FIRE_WEBHOOK:
            wyzwol_webhook(conv_id, mid, tura)
        pub, notatki, status_koniec, widziane = czekaj_na_odpowiedz(conv_id, widziane)
        pub_all += pub
        notatki_all += notatki
        transkrypt.append({"tura": i, "klient": tura, "bot": pub, "notatki": notatki, "status": status_koniec})
        for b in pub:
            print("      bot> " + b.replace("\n", "\n           "))
        for n in notatki:
            print("      [notatka]> " + n.replace("\n", " ")[:200])
        if not pub:
            print("      [!] brak odpowiedzi bota na ture %d" % i)
    werdykt, powody = ocen(sc, pub_all, notatki_all, status_koniec)
    print("   => %s%s" % (werdykt, ("  (" + "; ".join(powody) + ")") if powody else ""))
    print()
    return {"id": sc["id"], "kat": sc.get("kat"), "tytul": sc.get("tytul"),
            "conv_id": conv_id, "contact_id": contact_id,
            "tworzy_lead": bool(sc.get("tworzy_lead")),
            "werdykt": werdykt, "powody": powody,
            "status_koniec": status_koniec, "transkrypt": transkrypt}
